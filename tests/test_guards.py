"""编造防护的单元测试（纯本地）。

背景：2026-11-05 发现 Kender 会在"用户问天气"时**不调工具**、直接照抄
get_weather 的返回格式编一条数据（如 `上海: 🌦️ 18°C`），耗时仅 0.9 秒。
因为 `get_reply_with_review` 原本"没调工具就跳过 Critic"，这条假数据能直接放行。

修复：`_looks_like_realtime_claim` 粗筛「数字 + 实时特征词」的组合，
命中就强制重写（要求先取证再回答）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import _looks_like_realtime_claim  # noqa: E402


def test_detects_bare_weather_format():
    # 就是线上真实出现的那条假数据
    assert _looks_like_realtime_claim("上海: 🌦️ 18°C") is True


def test_detects_chinese_unit():
    assert _looks_like_realtime_claim("上海今天气温 17 摄氏度") is True


def test_detects_index_and_price():
    assert _looks_like_realtime_claim("上证指数今天收于 3025 点") is True
    assert _looks_like_realtime_claim("这只股票股价 12.3 元") is True


def test_allows_pure_chat_without_numbers():
    assert _looks_like_realtime_claim("今天天气不错，适合出门。") is False


def test_allows_technical_explanation():
    assert _looks_like_realtime_claim("ReAct 是推理-行动-观察的循环") is False


def test_allows_year_mention_without_realtime_marker():
    # 有数字但没有实时特征词，不该误伤
    assert _looks_like_realtime_claim("我在 2026 年开始做这个项目") is False


def test_empty_reply_is_not_a_claim():
    assert _looks_like_realtime_claim("") is False
