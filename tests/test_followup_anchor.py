"""追问锚定的单元测试（纯本地）。

背景：多轮填槽时用户只回"上海"，qwen-plus 有约一半概率把同一个问题再问一遍
（eval 的 MT03 稳定复现）。修复方式是：检测到"上一轮是问句 + 这轮是短回答"时，
把上下文显式写进本轮输入。这里验证触发条件足够保守——不能把正常短句也改掉。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.agent as agent_mod  # noqa: E402


class _Mem:
    def __init__(self, messages):
        self._messages = messages

    async def get_memory(self):
        return self._messages


class _Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class _Agent:
    def __init__(self, messages):
        self.memory = _Mem(messages)


def _anchor(messages, user_msg):
    return asyncio.run(agent_mod._anchor_short_followup(_Agent(messages), user_msg))


def test_short_answer_to_question_is_anchored():
    msgs = [
        _Msg("user", "帮我查一下天气"),
        _Msg("assistant", [{"type": "text", "text": "请问你想查询哪个城市的天气？"}]),
    ]
    out = _anchor(msgs, "上海")
    assert out != "上海"
    assert "上海" in out
    assert "不要再重复提问" in out


def test_long_message_is_not_anchored():
    msgs = [_Msg("assistant", [{"type": "text", "text": "哪个城市？"}])]
    out = _anchor(msgs, "帮我查一下上海和北京今天的气温对比")
    assert out == "帮我查一下上海和北京今天的气温对比"


def test_message_with_punctuation_is_not_anchored():
    msgs = [_Msg("assistant", [{"type": "text", "text": "哪个城市？"}])]
    out = _anchor(msgs, "上海。")
    assert out == "上海。"


def test_last_assistant_not_question_is_not_anchored():
    msgs = [_Msg("assistant", [{"type": "text", "text": "好的，已经记下了。"}])]
    out = _anchor(msgs, "上海")
    assert out == "上海"


def test_empty_memory_is_not_anchored():
    assert _anchor([], "上海") == "上海"
