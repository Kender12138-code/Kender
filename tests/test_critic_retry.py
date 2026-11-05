"""Critic 重写路径的单元测试（纯本地，不花 API 额度）。

覆盖 2026-11-05 修的两个问题：
1. 打回重写后返回的轨迹丢了工具调用 —— 由 get_reply_with_review 内部修复，
   这里测它的两个支撑函数。
2. 重写时模型看不到工具原始数据，退化成复读 —— 靠 _collect_tool_outputs
   把 Observation 塞回提示词，靠 _looks_like_echo 兜住"复读"这种退化输出。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import _collect_tool_outputs, _looks_like_echo  # noqa: E402


class _FakeMemory:
    def __init__(self, messages):
        self._messages = messages

    async def get_memory(self):
        return self._messages


class _FakeMsg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class _FakeAgent:
    def __init__(self, messages):
        self.memory = _FakeMemory(messages)


def test_echo_detects_raw_tool_output():
    tool = "深圳: 🌦️  +28°C"
    # 空格被归一化后与工具输出一致 → 判定为复读
    assert _looks_like_echo("深圳: 🌦️ +28°C", tool) is True


def test_echo_allows_natural_answer():
    tool = "深圳: 🌦️  +28°C"
    reply = "深圳今天多云转晴，气温 28 度，出门记得带伞。"
    assert _looks_like_echo(reply, tool) is False


def test_empty_reply_is_degenerate():
    assert _looks_like_echo("   ", "任何工具输出") is True


def test_long_reply_never_treated_as_echo():
    tool = "A" * 500
    assert _looks_like_echo("A" * 200, tool) is False


def test_collect_tool_outputs_joins_multiple_results():
    messages = [
        _FakeMsg("user", "深圳和上海天气"),
        _FakeMsg("assistant", [{"type": "tool_use", "name": "get_weather", "input": {}}]),
        _FakeMsg("system", [{"type": "tool_result",
                             "output": [{"type": "text", "text": "深圳: +28°C"}]}]),
        _FakeMsg("system", [{"type": "tool_result",
                             "output": [{"type": "text", "text": "上海: +18°C"}]}]),
    ]
    out = asyncio.run(_collect_tool_outputs(_FakeAgent(messages)))
    assert "深圳" in out and "+28°C" in out
    assert "上海" in out and "+18°C" in out
    assert "---" in out  # 多次结果用分隔符拼起来


def test_collect_tool_outputs_ignores_non_tool_messages():
    messages = [
        _FakeMsg("user", "你好"),
        _FakeMsg("assistant", [{"type": "text", "text": "你好呀"}]),
    ]
    assert asyncio.run(_collect_tool_outputs(_FakeAgent(messages))) == ""
