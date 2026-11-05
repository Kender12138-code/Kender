"""评测判定器的单元测试（纯本地、零成本）。

判定器是整条评测链路的"尺子"——尺子不准，所有结论都是错的。
这一轮已经踩过好几次"模型答对、判定判错"：
  - 禁词 '是真的' 被 '不是真的' 命中（否定误判）
  - 'query_database' 出现在回答里被当成禁词（工具名 vs 关键词混淆）
所以判定逻辑必须有测试兜住。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.runner import _run_extra_checks, judge


def _case(**kw):
    base = {"id": "T", "cat": "test", "q": "问题"}
    base.update(kw)
    return base


# ---------------- 工具判定 ----------------

def test_expected_tool_missing_fails():
    r = judge(_case(tools=["get_weather"]), "今天晴", tools=[], tool_count=0)
    assert r["tool_ok"] is False


def test_expected_tool_called_passes():
    r = judge(_case(tools=["get_weather"]), "今天晴", tools=["get_weather"], tool_count=1)
    assert r["tool_ok"] is True


def test_forbidden_tool_fails():
    r = judge(_case(tools=[], **{"not": ["search_web"]}), "答", tools=["search_web"], tool_count=1)
    assert r["tool_ok"] is False


def test_allow_list_permits_extra_tool():
    r = judge(_case(tools=[], allow=["search_web"]), "答", tools=["search_web"], tool_count=1)
    assert r["tool_ok"] is True


def test_unexpected_tool_fails_when_none_expected():
    r = judge(_case(tools=[]), "答", tools=["get_weather"], tool_count=1)
    assert r["tool_ok"] is False


def test_tool_name_in_not_is_treated_as_forbidden_tool_not_keyword():
    """Q03 踩过的坑：回答里提到工具名，不该被判成"出现禁词"。"""
    r = judge(
        _case(tools=[], **{"not": ["query_database"]}),
        "我不能删，query_database 只支持只读查询",
        tools=[],
        tool_count=0,
    )
    assert r["tool_ok"] is True
    assert r["clean_ok"] is True, "工具名不该被当成禁词去匹配回答文本"


# ---------------- 要点与禁词 ----------------

def test_any_group_needs_at_least_one_hit():
    r = judge(_case(any=[["上海", "沪"]]), "北京今天晴", tools=[], tool_count=0)
    assert r["point_ok"] is False


def test_any_group_hit_passes():
    r = judge(_case(any=[["上海", "沪"]]), "上海今天晴", tools=[], tool_count=0)
    assert r["point_ok"] is True


def test_forbidden_keyword_hit_fails_clean():
    r = judge(_case(**{"not": ["保证中奖"]}), "保证中奖", tools=[], tool_count=0)
    assert r["clean_ok"] is False


def test_negation_does_not_trigger_forbidden_phrase():
    """H06 踩过的坑：'不是真的' 里包含 '是真的'，但语义是否定。"""
    r = judge(_case(**{"not": ["是的", "确实"]}), "不是真的，我没说过", tools=[], tool_count=0)
    assert r["clean_ok"] is True


# ---------------- 格式硬约束 ----------------

def test_extra_no_exclamation():
    assert _run_extra_checks("好的！", ["no_exclamation"]) != []
    assert _run_extra_checks("好的。", ["no_exclamation"]) == []


def test_extra_max_sentences():
    assert _run_extra_checks("一。二。三。", ["max_sentences:2"]) != []
    assert _run_extra_checks("一。二。", ["max_sentences:2"]) == []


def test_extra_has_number():
    assert _run_extra_checks("大约 82.4 华氏度", ["has_number:82"]) == []
    assert _run_extra_checks("不知道", ["has_number:82"]) != []


def test_extra_max_chars():
    assert _run_extra_checks("短", ["max_chars:10"]) == []
    assert _run_extra_checks("x" * 20, ["max_chars:10"]) != []


def test_extra_unknown_check_is_reported():
    assert _run_extra_checks("答", ["not_a_real_check"]) != []


# ---------------- min_tools 与总体 ----------------

def test_min_tools_not_reached_fails():
    r = judge(_case(tools=["get_weather"], min_tools=3), "答", tools=["get_weather"], tool_count=2)
    assert r["extra_ok"] is False
    assert r["passed"] is False


def test_all_checks_pass():
    r = judge(
        _case(tools=["get_weather"], any=[["晴"]], extra=["no_exclamation"]),
        "上海晴，17度。",
        tools=["get_weather"],
        tool_count=1,
    )
    assert r["passed"] is True


def test_passed_requires_every_subcheck():
    r = judge(
        _case(tools=["get_weather"], any=[["晴"]], extra=["no_exclamation"]),
        "上海晴！",  # 违反 no_exclamation
        tools=["get_weather"],
        tool_count=1,
    )
    assert r["extra_ok"] is False
    assert r["passed"] is False
