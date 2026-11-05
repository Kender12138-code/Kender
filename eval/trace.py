"""评测轨迹落库（SQLite）。

## 为什么要有这个

`results.jsonl` 是"一次一文件"，跑十次就有十个文件，想回答
「E06 最近五次分别怎么答的」「哪个工具最容易失败」只能手工 grep。

SQLite 把每次运行拍平成两张表：

    runs   一次用例 = 一行（问题、回答、耗时、通过与否、判分）
    steps  一次工具调用 = 一行（工具名、入参、返回）

之后所有分析都是 SQL：

    -- 最近 7 天通过率
    SELECT date(created_at), AVG(passed) FROM runs GROUP BY 1;
    -- 最慢的用例
    SELECT case_id, AVG(latency_s) FROM runs GROUP BY 1 ORDER BY 2 DESC;
    -- 某个工具失败率
    SELECT tool, SUM(output LIKE '%失败%') FROM steps GROUP BY 1;

只依赖标准库 sqlite3，不需要额外依赖。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "results" / "kender_trace.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    case_id     TEXT NOT NULL,
    question    TEXT,
    reply       TEXT,
    tools       TEXT,
    tool_calls  INTEGER,
    latency_s   REAL,
    rounds      INTEGER,
    passed      INTEGER,
    llm_score   INTEGER,
    critic_ok   INTEGER,
    tool_error  INTEGER,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    case_id     TEXT NOT NULL,
    step        INTEGER,
    tool        TEXT,
    args        TEXT,
    output      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_case ON runs(case_id);
CREATE INDEX IF NOT EXISTS idx_steps_case ON steps(case_id);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    return conn


def save_run(result: dict, run_id: str, db_path: Path | None = None) -> None:
    """写入一次用例结果 + 它的全部工具调用步骤。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (run_id, case_id, question, reply, tools, tool_calls,"
            " latency_s, rounds, passed, llm_score, critic_ok, tool_error, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                result.get("id"),
                result.get("question"),
                (result.get("reply") or "")[:2000],
                json.dumps(result.get("tools_used") or [], ensure_ascii=False),
                result.get("tool_call_count", 0),
                result.get("latency_s", 0.0),
                result.get("rounds", 1),
                1 if result.get("passed") else 0,
                result.get("llm_score"),
                1 if result.get("critic_passed") else 0,
                1 if result.get("tool_error") else 0,
                now,
            ),
        )
        for step in result.get("steps") or []:
            conn.execute(
                "INSERT INTO steps (run_id, case_id, step, tool, args, output, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    result.get("id"),
                    step.get("step"),
                    step.get("tool"),
                    (step.get("args") or "")[:1000],
                    (step.get("output") or "")[:1500],
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def recent_runs(limit: int = 20, db_path: Path | None = None,
                since: str | None = None) -> list[dict]:
    """取最近的运行记录。

    since 形如 "2026-11-05 21:55"（本地时间字符串，和 created_at 同格式）：
    只看某个时间点之后的运行。修完 bug 想验证"现在稳不稳"时用得上，
    否则历史失败会一直拉低通过率。
    """
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if since:
            rows = conn.execute(
                "SELECT * FROM runs WHERE created_at >= ? ORDER BY id DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def trace_of(case_id: str, limit: int = 5, db_path: Path | None = None) -> list[dict]:
    """取出某个用例最近几次的工具调用轨迹。"""
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        run_ids = [
            r["run_id"]
            for r in conn.execute(
                "SELECT DISTINCT run_id FROM runs WHERE case_id=? ORDER BY id DESC LIMIT ?",
                (case_id, limit),
            ).fetchall()
        ]
        out = []
        for rid in run_ids:
            steps = [
                dict(r)
                for r in conn.execute(
                    "SELECT step, tool, args, output FROM steps"
                    " WHERE run_id=? AND case_id=? ORDER BY step",
                    (rid, case_id),
                ).fetchall()
            ]
            out.append({"run_id": rid, "steps": steps})
        return out
    finally:
        conn.close()
