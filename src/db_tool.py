"""把"自然语言查本地数据库"接成 Kender 的一个 Agent 工具。

零依赖新增：不改动任何现有文件，只需在 src/agent.py 的 build_toolkit 里注册一行：
    from src.db_tool import query_database
    toolkit.register_tool_function(query_database)

依赖安装：
    pip install openai

环境变量：DASHSCOPE_API_KEY（复用 Kender 现有的 key），DB_PATH（默认 data/kender.db）
"""

from __future__ import annotations

import os
import re
import sqlite3

from agentscope.tool import ToolResponse

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DB_PATH = os.getenv("DB_PATH", "data/kender.db")
MAX_ROWS = 50  # 返回给模型的最大行数，防止撑爆上下文

DENY = re.compile(
    r"\b(drop|delete|update|insert|alter|create|attach|pragma|replace|vacuum)\b", re.I
)

SYSTEM = """你是 SQLite 专家。根据用户问题和表结构，只输出一条 SELECT 语句。
硬规则：
1. 只输出 SQL 本身，不要解释、不要 markdown 代码块、不要以 SQL: 开头
2. 只能查 SELECT，禁止任何写操作
3. 【最重要】如果问题中提到的核心对象（表/实体）在表结构里根本不存在，
   你必须且只能输出这一行：SELECT 'NO_TABLE'
   严禁拿其他表拼一个"看起来像"的查询来敷衍——静默答错比报错危险得多
3b. 如果用户要求的是删除、修改、清空等非查询操作，同样只输出 SELECT 'NO_TABLE'
4. 相对时间（上个月/今年/最近7天）用 date('now', ...) 系列函数表达，不要写死日期
5. 结果必须带 LIMIT {limit}
"""

FEWSHOT = """参考示例：
问题: 上个月销售额最高的前 3 个商品是哪些
SQL: SELECT p.name AS 商品, SUM(o.amount) AS 销售额 FROM orders o JOIN products p ON o.product_id = p.id WHERE o.created_at >= date('now','start of month','-1 month') AND o.created_at < date('now','start of month') GROUP BY p.id ORDER BY 销售额 DESC LIMIT 3;
问题: 查一下库存表中库存不足的商品
SQL: SELECT 'NO_TABLE';
问题: 把所有订单都删掉
SQL: SELECT 'NO_TABLE';
"""


def _client():
    """延迟导入，避免没装 openai 时整个 Kender 起不来。"""
    from openai import OpenAI

    return OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


def _ask(system: str, user: str, model: str = "qwen-plus") -> str:
    r = _client().chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return r.choices[0].message.content


def get_schema(db_path: str = DB_PATH) -> str:
    """抽表结构 + 每表两行样例。

    样例是关键：只给字段名，模型会把 status=1 猜成"成功"，给两行真实数据它就不用猜。
    表很多（几十张）时，这里改成"只返回表名清单"，让模型先用第二次调用确认目标表，
    再把那几张表的结构喂给它（两级策略，避免 schema 撑爆上下文）。
    """
    if not os.path.exists(db_path):
        return f"（数据库文件不存在：{db_path}）"
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    chunks = []
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for t in tables:
            cols = [f"{r[1]}:{r[2]}" for r in con.execute(f"PRAGMA table_info({t})")]
            sample = con.execute(f"SELECT * FROM {t} LIMIT 2").fetchall()
            chunks.append(f"表 {t}({', '.join(cols)})\n  样例行: {sample}")
    finally:
        con.close()
    return "\n".join(chunks) or "（库里没有表）"


def _clean(raw: str) -> str:
    s = raw.strip().strip("`")
    if s.lower().startswith("sql:"):
        s = s[4:]
    return s.replace("```sql", "").replace("```", "").strip().strip("`").rstrip(";").strip()


def get_tables(db_path: str = DB_PATH) -> set:
    """库里真实存在的表名集合。"""
    if not os.path.exists(db_path):
        return set()
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            r[0].lower()
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        con.close()


def _validate(sql: str, limit: int) -> str:
    """六道保险：SELECT-only、危险关键字、表名白名单、强制 LIMIT。"""
    low = sql.lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise ValueError(f"只允许 SELECT，实际得到：{sql[:60]}")
    hit = DENY.search(sql)
    if hit:
        raise ValueError(f"命中危险关键字 {hit.group(0)}，已拦截")
    # 关键防线：防止模型臆造表名后"安静地答错"（实测高发场景）
    used = {m.group(1).lower() for m in re.finditer(r"(?i)\b(?:from|join)\s+([a-z_]\w*)", sql)}
    bad = used - get_tables()
    if bad:
        raise ValueError(
            f"引用了库中不存在的表 {sorted(bad)}，库里只有 {sorted(get_tables())}"
        )
    if "limit" not in low:
        sql = f"{sql} LIMIT {limit}"
    return sql


def nl2sql(question: str, limit: int = MAX_ROWS, repair: int = 1) -> str:
    """自然语言 → 安全 SQL。出错把报错喂回模型自纠，最多 repair 次。"""
    prompt = f"表结构:\n{get_schema()}\n\n{FEWSHOT}\n问题: {question}\nSQL:"
    sysmsg = SYSTEM.format(limit=limit)
    sql = _clean(_ask(sysmsg, prompt))

    for attempt in range(repair + 1):
        try:
            sql = _validate(sql, limit)
            con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            try:
                con.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()  # 不执行，只验语法
            finally:
                con.close()
            return sql
        except Exception as e:  # noqa: BLE001
            if attempt == repair:
                raise
            sql = _clean(
                _client().chat.completions.create(
                    model="qwen-plus",
                    temperature=0,
                    messages=[
                        {"role": "system", "content": sysmsg},
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": sql},
                        {"role": "user", "content": f"这条 SQL 报错：{e}\n请修正后只输出新的 SQL。"},
                    ],
                )
                .choices[0]
                .message.content
            )
    return sql


def query_database(question: str) -> ToolResponse:
    """用自然语言查询本地 SQLite 业务数据库，返回表格结果。

    当用户想查某些业务数据时调用本工具，例如"上个月卖了多少钱"、
    "库存不足的商品有哪些"、"最近一周新增了多少订单"、"哪个品类最好卖"。
    你只需要把用户的原始问题传进来，本工具负责生成并执行 SQL。

    注意：本工具只读，不会修改任何数据；如果 SQL 生成失败会返回错误原因，
    你可以换个说法再试一次，或者告诉用户换个问法。

    Args:
        question: 用户想查的问题，用自然语言描述即可，必填。

    Returns:
        ToolResponse: 包含生成的 SQL 和查询结果的文本（最多 50 行）。
    """
    try:
        sql = nl2sql(question)
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            cur = con.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        finally:
            con.close()

        shown = rows[:MAX_ROWS]
        lines = [" | ".join(map(str, r)) for r in shown]
        text = (
            f"SQL: {sql}\n"
            f"列名: {', '.join(cols)}\n"
            f"共 {len(rows)} 行，展示前 {len(shown)} 行：\n"
            + "\n".join(lines)
        )
        if not shown:
            text += "\n（结果为空，可能是条件太严格，可以考虑换个口径再问）"
        return ToolResponse(content=[{"type": "text", "text": text}])
    except Exception as e:  # noqa: BLE001
        # 关键：不要把异常抛给 Agent 让它崩掉，而是把原因回传，让它自己改问法重试
        return ToolResponse(
            content=[
                {
                    "type": "text",
                    "text": f"查询失败：{e}。请尝试换一种问法，或先问用户补充时间范围、筛选条件。",
                }
            ]
        )


__all__ = ["query_database", "nl2sql", "get_schema"]
