import json
import os
from datetime import datetime
from pathlib import Path
from ddgs import DDGS
from agentscope.tool import ToolResponse

REMINDER_FILE = "data/reminders.json"


def search_web(query: str, max_results: int = 3) -> ToolResponse:
    """使用联网搜索引擎检索用户问题相关的最新信息。

    当用户询问实时资讯、新闻、天气、股价、最新事件，或明确表示
    "今天/最新/热搜/新闻" 等需要外部数据的内容时，应该调用本工具。
    返回检索到的标题、摘要与来源链接，供你综合后回答用户。

    Args:
        query: 用户想要搜索的关键词或问题。
        max_results: 返回的结果条数，默认 3 条。

    Returns:
        ToolResponse: 包装后的搜索结果文本（AgentScope 要求工具函数必须返回
        ToolResponse 对象或生成器）。content 使用字典列表，与 AgentScope
        内部对 TextBlock 的序列化格式保持一致。
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                text = "没有找到相关信息。"
            else:
                output = []
                for i, r in enumerate(results, 1):
                    output.append(f"{i}. {r.get('title', '无标题')}")
                    output.append(f"   {r.get('body', '无摘要')[:200]}...")
                    output.append(f"   来源：{r.get('href', '')}")
                    output.append("")
                text = "\n".join(output)
    except Exception as e:
        text = f"搜索出错：{e}"

    return ToolResponse(content=[{"type": "text", "text": text}])


def get_weather(city: str) -> ToolResponse:
    """查询指定城市的实时天气。

    当用户询问某地天气、气温、下雨、天气怎么样时，优先调用本工具获取实时结果。
    返回格式：城市 + 天气图标 + 温度，例如"上海: 🌦️  +31°C"。

    Args:
        city: 城市名称，必填，例如"上海"、"北京"。
            如果用户没有说明城市，不要猜测，先向用户追问"请问你想查询哪个城市？"，
            拿到城市后再调用本工具。

    Returns:
        ToolResponse: 实时天气简要信息。
    """
    try:
        from urllib.parse import quote
        from urllib.request import urlopen

        with urlopen(f"https://wttr.in/{quote(city)}?format=3", timeout=10) as resp:
            text = resp.read().decode("utf-8").strip()
    except Exception as e:
        text = f"天气查询失败：{e}"

    return ToolResponse(content=[{"type": "text", "text": text}])


def set_reminder(title: str, remind_time: str) -> ToolResponse:
    """创建一个提醒事项（保存在本地，不需要联网）。

    当用户表达"提醒我…""帮我记一下…""别忘了…""XX点叫我…"这类意图时调用本工具。

    重要：title 与 remind_time 都是必填参数。如果用户的描述里缺少其中任意一个，
    不要猜测、不要用默认值，必须先向用户追问补全，拿到完整信息后再调用本工具。

    Args:
        title: 提醒的具体内容，例如"交实习周报"、"取快递"。
        remind_time: 提醒时间，例如"今晚 20:00"、"明天上午 9 点"、"下周一"。

    Returns:
        ToolResponse: 提醒创建结果，含当前已有的全部提醒列表。
    """
    try:
        os.makedirs("data", exist_ok=True)
        try:
            with open(REMINDER_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            items = []

        items.append(
            {
                "title": title,
                "time": remind_time,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        )
        with open(REMINDER_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

        listing = "\n".join(
            f"{i + 1}. {it['time']} —— {it['title']}" for i, it in enumerate(items)
        )
        text = f"提醒已创建成功。当前共有 {len(items)} 条提醒：\n{listing}"
    except Exception as e:
        text = f"创建提醒失败：{e}"

    return ToolResponse(content=[{"type": "text", "text": text}])


def read_document(file_path: str) -> str:
    """读取本地文档（.txt / .docx / .pdf）的文本内容，最多返回前 5000 字符。

    本函数由 Web 界面在用户上传文件时调用，把文档内容注入到对话中，
    不注册为 Agent 工具（模型无法感知本地文件路径）。

    Args:
        file_path: 待读取文件的本地路径。

    Returns:
        文档文本内容；若格式不支持或读取失败，返回相应的提示信息。
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    try:
        if ext == ".txt":
            with open(path, "r", encoding="utf-8") as f:
                return f.read()[:5000]
        elif ext == ".docx":
            from docx import Document

            doc = Document(path)
            return "\n".join([p.text for p in doc.paragraphs])[:5000]
        elif ext == ".pdf":
            from PyPDF2 import PdfReader

            reader = PdfReader(path)
            text = "".join([page.extract_text() or "" for page in reader.pages[:20]])
            return text[:5000]
        else:
            return f"暂不支持 {ext} 格式"
    except Exception as e:
        return f"读取失败：{e}"


def get_current_date() -> str:
    """返回当前日期与星期，帮助模型感知"今天"的时间信息。"""
    now = datetime.now()
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    return f"今天是{now.year}年{now.month}月{now.day}日，星期{weekdays[now.weekday()]}。"


# ===================== RAG query 改写（提升召回率）=====================
# 用户的问题往往是口语化的（"那个报销怎么弄来着"），
# 直接拿去向量检索容易召回不准。先让模型改写成几条表述不同、
# 语义相同的检索语句，分别检索后合并去重，召回率明显更高。

REWRITE_PROMPT = """你是检索优化助手。请把用户的问题改写成 {n} 条【表述不同但语义相同】的检索语句，用于提升向量检索的召回率。

要求：
- 每条都必须保留原问题的关键实体和意图，不要改变原意
- 用中文，简洁，每条不超过 30 字
- 只输出一个 JSON 数组字符串，不要任何解释、不要 markdown 代码块
  例如：["语句一", "语句二", "语句三"]

用户的问题：{query}

输出 JSON 数组："""

# 语料低于这个片段数就不做 query 改写（省一次 LLM 调用）
REWRITE_MIN_CHUNKS = 8

_rewrite_model = None


def _get_rewrite_model():
    """懒加载改写用的模型（只有第一次检索时才创建，避免拖慢启动）。"""
    global _rewrite_model
    if _rewrite_model is None:
        from agentscope.model import DashScopeChatModel
        from dotenv import load_dotenv

        load_dotenv()
        _rewrite_model = DashScopeChatModel(
            model_name="qwen-plus",
            api_key=os.getenv("DASHSCOPE_API_KEY"),
        )
    return _rewrite_model


async def _model_text(model, prompt: str) -> str:
    """调用模型取回完整文本（兼容流式生成器返回）。"""
    from collections.abc import AsyncGenerator

    res = await model(messages=[{"role": "user", "content": prompt}])
    if isinstance(res, AsyncGenerator):
        text = ""
        async for chunk in res:
            content = chunk["content"] if isinstance(chunk, dict) else None
            if isinstance(content, list):
                text = "".join(
                    str(b.get("text", ""))
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
        return text
    content = res["content"] if isinstance(res, dict) else None
    if isinstance(content, list):
        return "".join(
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return "" if content is None else str(content)


async def expand_query(query: str, n: int = 3) -> list:
    """把用户问题改写成 n 条同义检索语句。

    任何一步失败都降级为 [原问题] —— 改写是"优化"，
    绝不能因为优化失败就让检索整个不可用。
    """
    try:
        text = await _model_text(
            _get_rewrite_model(), REWRITE_PROMPT.format(query=query, n=n)
        )
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:-1]).strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
        data = json.loads(cleaned)
        if not isinstance(data, list):
            return [query]
        out = []
        for item in data:
            if isinstance(item, str) and item.strip() and item.strip() not in out:
                out.append(item.strip())
            if len(out) >= n:
                break
        return out or [query]
    except Exception as e:
        print(f"[query-rewrite] 改写失败，降级为原问题：{e}")
        return [query]


async def retrieve_document(query: str, k: int = 4) -> ToolResponse:
    """从用户已上传的本地文档中检索与问题最相关的片段（真正的 RAG 检索）。

    当用户的问题涉及之前上传过的文档内容（例如"根据我上传的文档…"、
    "我的简历里写了什么"、"总结一下我上传的文档"、"文档里提到的 XX 是什么"）时，
    应该调用本工具从向量库中检索最相关的片段，再结合片段回答。如果用户尚未上传
    任何文档，本工具会提示其先上传 TXT / DOCX / PDF 文件。

    注意：本工具基于 FAISS 向量检索（分块 + DashScope Embedding），与联网搜索
    search_web 是两套独立能力，请按问题性质选择调用。

    检索前会先用模型把问题改写成多条同义语句（query 改写），
    分别检索后合并去重，以提升召回率；改写失败会自动降级为原问题检索。

    Args:
        query: 要检索的问题或关键词。
        k: 返回的文档片段数量，默认 4 条。

    Returns:
        ToolResponse: 检索到的文档片段（或提示用户先上传文档）。content 使用
        字典列表，与 AgentScope 内部对 TextBlock 的序列化格式保持一致。
    """
    from .rag import retrieve, index_exists, chunk_count

    if not index_exists():
        text = "你还没有上传任何文档，无法检索。请先在界面左侧上传 TXT / DOCX / PDF 文档。"
        return ToolResponse(content=[{"type": "text", "text": text}])

    # 只在语料达到一定规模时才做 query 改写：
    # 小语料下原始问题通常已经能命中，改写只会白白多花一次 LLM 调用。
    total = chunk_count()
    if total >= REWRITE_MIN_CHUNKS:
        queries = [query] + [q for q in await expand_query(query) if q != query]
        print(f"[rag] 索引 {total} 个片段，启用 query 改写：{queries}")
    else:
        queries = [query]
        print(f"[rag] 索引仅 {total} 个片段（< {REWRITE_MIN_CHUNKS}），跳过 query 改写")
    chunks = []
    seen = set()
    for q in queries:
        try:
            for c in retrieve(q, k=k):
                key = c[:80]
                if key not in seen:
                    seen.add(key)
                    chunks.append(c)
        except Exception as e:
            print(f"[query-rewrite] 检索「{q}」失败：{e}")

    if not chunks:
        text = "在已上传的文档中没有检索到相关内容。"
    else:
        output = [f"【文档片段 {i + 1}】\n{c}\n" for i, c in enumerate(chunks)]
        text = "\n".join(output)

    return ToolResponse(content=[{"type": "text", "text": text}])
