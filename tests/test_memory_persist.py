"""记忆落盘的回归测试（离线，不依赖 pytest-asyncio）。

背景（2026-09-09 修的第二个 bug）：
    get_reply_with_review 里"本轮没有调用工具"的分支直接 return，
    跳过了 _persist_turn。而"我叫XX""我要去出差"这类陈述恰恰不触发工具，
    结果是长期记忆几乎记不到任何东西。
    审核可以跳过，记忆不能跳过 —— 这里把这条钉死。
"""
import asyncio

import src.agent as agent_mod
from src.agent import CriticVerdict


class _FakeModel:
    pass


def _run(coro):
    return asyncio.run(coro)


def test_未调用工具时仍然写入长期记忆(monkeypatch):
    calls = []

    async def fake_run_once(agent, model, message):
        # 模拟"没调工具"的一轮：返回 (回复, 轨迹, 工具调用次数=0)
        return "好的，我记住了。", "", 0

    async def fake_persist(model, memory, user_message, reply_text, persist=True):
        calls.append((user_message, persist))

    monkeypatch.setattr(agent_mod, "_run_once", fake_run_once)
    monkeypatch.setattr(agent_mod, "_persist_turn", fake_persist)

    memory = {"user_name": None, "key_facts": [], "chat_history": []}
    reply, trace, verdict, rounds = _run(
        agent_mod.get_reply_with_review(
            object(), _FakeModel(), "我叫杨恺，我明天要去体检", memory
        )
    )

    assert reply == "好的，我记住了。"
    assert isinstance(verdict, CriticVerdict)
    # 关键断言：即使没调工具，也必须落一次记忆
    assert calls == [("我叫杨恺，我明天要去体检", True)]


def test_persist_false时不写记忆(monkeypatch):
    """Web 访客会话的隔离开关：persist=False 时一条都不许写。"""
    calls = []

    async def fake_run_once(agent, model, message):
        return "好的", "", 0

    async def fake_persist(model, memory, user_message, reply_text, persist=True):
        calls.append(persist)

    monkeypatch.setattr(agent_mod, "_run_once", fake_run_once)
    monkeypatch.setattr(agent_mod, "_persist_turn", fake_persist)

    memory = {"user_name": None, "key_facts": [], "chat_history": []}
    _run(
        agent_mod.get_reply_with_review(
            object(), _FakeModel(), "随便聊聊", memory, persist=False
        )
    )

    assert calls == [False]
