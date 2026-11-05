"""FastAPI 会话隔离的单元测试（不起服务、不调模型）。

两个要保证的性质：
1. **同会话串行**：一个会话的 agent 不是并发安全的（memory 按轮追加），
   并发请求会让 A 的 tool_use 插进 B 的对话。
2. **不同会话并行**：A 用户问长问题时，B 用户不该干等。
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402


class _FakeVerdict:
    passed = True
    reason = "ok"


class _FakeAgent:
    def __init__(self):
        self.toolkit = object()


@pytest.fixture(autouse=True)
def isolated_sessions(monkeypatch):
    """每个用例独立的会话表 + 假的 agent 工厂。"""
    monkeypatch.setattr(server, "SESSIONS", server.OrderedDict())
    monkeypatch.setattr(server, "MAX_SESSIONS", 8)
    monkeypatch.setattr(server, "create_agent", lambda mem: (_FakeAgent(), "fake-model"))

    async def fake_attach(toolkit):
        return []

    monkeypatch.setattr(server, "attach_mcp_tools", fake_attach)
    yield


def _patch_reply(monkeypatch, recorder, delay):
    async def fake_reply(agent, model, message, memory):
        recorder["current"] += 1
        recorder["max"] = max(recorder["max"], recorder["current"])
        await asyncio.sleep(delay)
        recorder["order"].append(message)
        recorder["current"] -= 1
        return f"reply:{message}", "", _FakeVerdict(), 1

    monkeypatch.setattr(server, "get_reply_with_review", fake_reply)


def test_same_session_is_serialized(monkeypatch):
    recorder = {"current": 0, "max": 0, "order": []}
    _patch_reply(monkeypatch, recorder, delay=0.05)

    async def run():
        return await asyncio.gather(
            server.run_chat_turn("第一条", "s1"),
            server.run_chat_turn("第二条", "s1"),
        )

    asyncio.run(run())
    assert recorder["max"] == 1, "同一会话的两个请求不应该同时进入 agent"
    assert recorder["order"] == ["第一条", "第二条"]


def test_different_sessions_run_in_parallel(monkeypatch):
    recorder = {"current": 0, "max": 0, "order": []}
    _patch_reply(monkeypatch, recorder, delay=0.1)

    async def run():
        return await asyncio.gather(
            server.run_chat_turn("甲的提问", "s1"),
            server.run_chat_turn("乙的提问", "s2"),
        )

    results = asyncio.run(run())
    assert recorder["max"] == 2, "不同会话应该能并行，否则一个人就能卡住所有人"
    assert {r[0] for r in results} == {"reply:甲的提问", "reply:乙的提问"}


def test_each_session_has_its_own_agent():
    async def run():
        a = await server.get_session("s1")
        b = await server.get_session("s2")
        a2 = await server.get_session("s1")
        return a, b, a2

    a, b, a2 = asyncio.run(run())
    assert a is a2, "同一 id 应复用同一个会话"
    assert a["agent"] is not b["agent"], "不同会话必须用不同 agent"
    assert a["memory"] is not b["memory"], "不同会话必须用不同记忆"


def test_session_lru_eviction(monkeypatch):
    monkeypatch.setattr(server, "MAX_SESSIONS", 2)

    async def run():
        await server.get_session("s1")
        await server.get_session("s2")
        await server.get_session("s3")  # 触发淘汰
        return list(server.SESSIONS.keys())

    keys = asyncio.run(run())
    assert keys == ["s2", "s3"], "最久未使用的会话应先被淘汰"


def test_empty_session_id_falls_back_to_default():
    async def run():
        return await server.get_session("   ")

    session = asyncio.run(run())
    assert session is server.SESSIONS["default"]
