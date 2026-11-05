"""取证守卫的"误伤"回归测试。

第一版守卫只看回答里有没有「数字 + 实时特征词」，结果把
「帮我搜一下」的澄清回答（里面举了天气例子）误判成编造，触发了重写。
修复后必须同时满足：**问题本身在问实时信息** + **回答里出现具体数值**。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import _is_realtime_question, _looks_like_realtime_claim  # noqa: E402


def test_realtime_question_weather():
    assert _is_realtime_question("上海天气怎么样？") is True
    assert _is_realtime_question("今天几度？") is True


def test_realtime_question_news_and_stock():
    assert _is_realtime_question("最近有什么新闻") is True
    assert _is_realtime_question("上证指数多少点") is True


def test_non_realtime_question():
    assert _is_realtime_question("帮我搜一下") is False
    assert _is_realtime_question("ReAct 是什么") is False
    assert _is_realtime_question("你好") is False


def test_guard_does_not_fire_for_non_realtime_question():
    """关键回归：用户在说"帮我搜一下"，回答里举例写了 18°C，不该被当成编造。"""
    question = "帮我搜一下"
    reply = "你想搜什么？比如「上海天气 18°C」这种。"
    should_guard = _is_realtime_question(question) and _looks_like_realtime_claim(reply)
    assert should_guard is False


def test_guard_fires_for_realtime_question_with_bare_data():
    """真正的编造：问天气，没调工具，直接给出 '上海: 🌦️ 18°C'。"""
    question = "上海天气怎么样？"
    reply = "上海: 🌦️ 18°C"
    should_guard = _is_realtime_question(question) and _looks_like_realtime_claim(reply)
    assert should_guard is True
