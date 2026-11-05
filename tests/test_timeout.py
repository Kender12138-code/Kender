"""单轮超时的单元测试（不联网、不花额度）。

背景：`agent.reply()` 没有超时保护时，模型或工具卡住会让请求无限挂起，
Web 端一个请求就能把 worker 占死。这里用 50ms 的超时 + 一个睡 5 秒的假
agent 验证：超时会被转成可读提示，而不是抛出去。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.agent as agent_mod  # noqa: E402


class _SlowAgent:
    async def reply(self, msg):  # noqa: ANN001
        await asyncio.sleep(5)
        return "永远不会到这里"


class _BoomAgent:
    async def reply(self, msg):  # noqa: ANN001
        raise RuntimeError("模型挂了")


def test_timeout_returns_readable_message(monkeypatch):
    monkeypatch.setattr(agent_mod, "TURN_TIMEOUT", 0.05)
    reply, trace, calls = asyncio.run(agent_mod._run_once(_SlowAgent(), None, "你好"))
    assert "超时" in reply
    assert trace == ""
    assert calls == 0


def test_model_exception_is_swallowed(monkeypatch):
    monkeypatch.setattr(agent_mod, "TURN_TIMEOUT", 5)
    reply, trace, calls = asyncio.run(agent_mod._run_once(_BoomAgent(), None, "你好"))
    assert "出错了" in reply
    assert calls == 0


def test_timeout_message_mentions_seconds(monkeypatch):
    monkeypatch.setattr(agent_mod, "TURN_TIMEOUT", 0.05)
    reply, _, _ = asyncio.run(agent_mod._run_once(_SlowAgent(), None, "你好"))
    assert "秒" in reply
