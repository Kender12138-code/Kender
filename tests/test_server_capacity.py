"""并发容量的单元测试（不起服务、不调模型）。

会话隔离的收益要能用数字说清楚：
- 10 个会话各问一句，应该并行完成（耗时接近单次）
- 同一个会话问 10 句，只能串行（耗时为 N 倍）
这里用假 agent + 100ms 延迟来量化，不花额度。
"""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402

DELAY = 0.1


class _FakeVerdict:
    passed = True
    reason = "ok"


class _FakeAgent:
    def __init__(self):
        self.toolkit = object()


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(server, "SESSIONS", server.OrderedDict())
    monkeypatch.setattr(server, "MAX_SESSIONS", 16)
    monkeypatch.setattr(server, "create_agent", lambda mem: (_FakeAgent(), "m"))

    async def fake_attach(toolkit):
        return []

    monkeypatch.setattr(server, "attach_mcp_tools", fake_attach)

    state = {"current": 0, "max": 0}

    async def fake_reply(agent, model, message, memory):
        state["current"] += 1
        state["max"] = max(state["max"], state["current"])
        await asyncio.sleep(DELAY)
        state["current"] -= 1
        return f"ok:{message}", "", _FakeVerdict(), 1

    monkeypatch.setattr(server, "get_reply_with_review", fake_reply)
    return state


def test_ten_sessions_run_concurrently(isolated):
    async def run():
        t0 = time.perf_counter()
        await asyncio.gather(
            *(server.run_chat_turn(f"q{i}", f"user-{i}") for i in range(10))
        )
        return time.perf_counter() - t0

    elapsed = asyncio.run(run())
    assert isolated["max"] == 10, "10 个不同会话应同时执行"
    # 并行时总耗时接近单次；串行会是 10 倍（1 秒）
    assert elapsed < DELAY * 4, f"并发没生效，耗时 {elapsed:.2f}s"


def test_same_session_is_serial_across_turns(isolated):
    async def run():
        t0 = time.perf_counter()
        await asyncio.gather(
            *(server.run_chat_turn(f"q{i}", "same-user") for i in range(5))
        )
        return time.perf_counter() - t0

    elapsed = asyncio.run(run())
    assert isolated["max"] == 1, "同一会话必须串行"
    assert elapsed >= DELAY * 5 * 0.9, f"串行应耗时约 {DELAY * 5:.1f}s，实际 {elapsed:.2f}s"


def test_eviction_does_not_break_inflight_session(isolated, monkeypatch):
    """会话被 LRU 淘汰时，已经拿到的 session 对象仍能正常用完。"""
    monkeypatch.setattr(server, "MAX_SESSIONS", 2)

    async def run():
        first = await server.get_session("s1")
        await server.get_session("s2")
        await server.get_session("s3")  # 淘汰 s1
        assert "s1" not in server.SESSIONS
        async with first["lock"]:
            return await server.get_reply_with_review(
                first["agent"], first["model"], "淘汰后继续用", first["memory"]
            )

    reply, _trace, _verdict, _rounds = asyncio.run(run())
    assert reply == "ok:淘汰后继续用"
