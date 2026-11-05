"""FastAPI 串行化的单元测试（不起服务、不调模型）。

所有请求共用一个 agent 实例，而 ReActAgent 会按轮次往自己的 memory 追加消息。
并发请求如果不串行，A 的 tool_use 可能插到 B 的对话中间，导致回答串台。
这里验证 run_chat_turn 在同一时刻只跑一个。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402


class _FakeVerdict:
    passed = True
    reason = "ok"


async def _run_two_concurrent(recorder, delay):
    async def fake_reply(agent, model, message, memory):
        recorder["current"] += 1
        recorder["max"] = max(recorder["max"], recorder["current"])
        await asyncio.sleep(delay)
        recorder["order"].append(message)
        recorder["current"] -= 1
        return f"reply:{message}", "", _FakeVerdict(), 1

    original = server.get_reply_with_review
    server.get_reply_with_review = fake_reply
    try:
        return await asyncio.gather(
            server.run_chat_turn("第一条"),
            server.run_chat_turn("第二条"),
        )
    finally:
        server.get_reply_with_review = original


def test_chat_turns_do_not_interleave():
    recorder = {"current": 0, "max": 0, "order": []}
    results = asyncio.run(_run_two_concurrent(recorder, delay=0.05))

    assert recorder["max"] == 1, "两个请求不应该同时进入 agent"
    assert len(results) == 2
    assert results[0][0] == "reply:第一条"
    assert results[1][0] == "reply:第二条"
    # 串行执行时顺序确定；并发时可能反过来
    assert recorder["order"] == ["第一条", "第二条"]


def test_chat_turn_returns_four_values():
    async def fake_reply(agent, model, message, memory):
        return "回答", "轨迹", _FakeVerdict(), 2

    original = server.get_reply_with_review
    server.get_reply_with_review = fake_reply
    try:
        reply, trace, verdict, rounds = asyncio.run(server.run_chat_turn("你好"))
    finally:
        server.get_reply_with_review = original

    assert reply == "回答"
    assert trace == "轨迹"
    assert verdict.passed is True
    assert rounds == 2
