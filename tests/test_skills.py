"""技能机制（客户自己写技能）的回归测试。

离线、不调模型：全部围绕 SKILL.md 的读写、校验和注册。注册部分用真实的
AgentScope Toolkit（它会读 front matter），所以能顺带验证我们的写法确实能被框架解析。
"""
import pytest
from agentscope.tool import Toolkit

import src.skills as skills_mod


@pytest.fixture()
def isolated_skill_dirs(tmp_path, monkeypatch):
    """把两个技能根目录都换到临时目录，避免读到仓库里的示例技能。"""
    custom = tmp_path / "custom"
    shipped = tmp_path / "shipped"
    monkeypatch.setattr(skills_mod, "CUSTOM_SKILLS_DIR", str(custom))
    monkeypatch.setattr(skills_mod, "SHIPPED_SKILLS_DIR", str(shipped))
    return custom, shipped


def _text(res):
    return res.content[0]["text"]


def test_保存后能读到并出现在列表里(isolated_skill_dirs):
    ok, message = skills_mod.save_skill_text("order-flow", "用户问订单相关问题时使用", "1. 先问订单号\n2. 再查库")
    assert ok, message
    assert (isolated_skill_dirs[0] / "order-flow" / "SKILL.md").is_file()

    names = [s["name"] for s in skills_mod.list_skill_details()]
    assert names == ["order-flow"]

    body = _text(skills_mod.read_skill("order-flow"))
    assert "先问订单号" in body


def test_同名重复保存会覆盖正文(isolated_skill_dirs):
    skills_mod.save_skill_text("order-flow", "场景A", "旧步骤")
    skills_mod.save_skill_text("order-flow", "场景B", "新步骤")
    body = _text(skills_mod.read_skill("order-flow"))
    assert "新步骤" in body and "旧步骤" not in body
    assert "场景B" in body


@pytest.mark.parametrize("bad_name", ["../evil", "Bad Name", "中文技能", "", "with_underscore", "a" * 80])
def test_非法技能名一律被拒(isolated_skill_dirs, bad_name):
    ok, message = skills_mod.save_skill_text(bad_name, "描述", "步骤")
    assert ok is False
    assert "技能名不合法" in message
    assert not (isolated_skill_dirs[0]).exists() or not any(isolated_skill_dirs[0].iterdir())


def test_大写技能名被规范化成小写(isolated_skill_dirs):
    ok, _ = skills_mod.save_skill_text("Order-Flow", "描述", "步骤")
    assert ok is True
    assert [s["name"] for s in skills_mod.list_skill_details()] == ["order-flow"]


def test_描述和正文不能为空(isolated_skill_dirs):
    assert skills_mod.save_skill_text("a-skill", "", "步骤")[0] is False
    assert skills_mod.save_skill_text("a-skill", "描述", "   ")[0] is False


def test_正文过长被拒(isolated_skill_dirs):
    too_long = "步" * (skills_mod.MAX_BODY_CHARS + 1)
    ok, message = skills_mod.save_skill_text("a-skill", "描述", too_long)
    assert ok is False
    assert "正文太长" in message


def test_坏技能文件被跳过而不是崩掉(isolated_skill_dirs):
    custom, _ = isolated_skill_dirs
    bad = custom / "broken"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("没有 front matter 的文件", encoding="utf-8")
    good = custom / "fine"
    good.mkdir()
    (good / "SKILL.md").write_text(
        "---\nname: fine\ndescription: 正常技能\n---\n\n步骤", encoding="utf-8"
    )
    names = [s["name"] for s in skills_mod.list_skill_details()]
    assert names == ["fine"]


def test_注册进toolkit并出现在系统提示词里(isolated_skill_dirs):
    skills_mod.save_skill_text("order-flow", "用户问订单时使用", "先问订单号")
    toolkit = Toolkit()
    names = skills_mod.register_skills(toolkit)
    assert names == ["order-flow"]

    prompt = toolkit.get_agent_skill_prompt()
    assert "order-flow" in prompt and "用户问订单时使用" in prompt
    # 注册是幂等的：重复调用只跳过，不抛错
    assert skills_mod.register_skills(toolkit) == []


def test_保存工具让技能在当前会话立即生效(isolated_skill_dirs):
    toolkit = Toolkit()
    save_skill, _, _ = skills_mod.make_skill_tools(toolkit)
    assert _text(save_skill("order-flow", "用户问订单时使用", "先问订单号")).startswith("技能 order-flow 已保存")

    assert "order-flow" in toolkit.skills
    assert "order-flow" in toolkit.get_agent_skill_prompt()

    # 覆盖同名技能时，toolkit 里不能残留旧描述
    save_skill("order-flow", "用户问退款时使用", "先问退款单号")
    assert toolkit.skills["order-flow"]["description"] == "用户问退款时使用"


def test_停用后不再出现在清单里且可重新启用(isolated_skill_dirs):
    skills_mod.save_skill_text("order-flow", "描述", "步骤")

    ok, message = skills_mod.set_skill_disabled("order-flow", True)
    assert ok and "已停用" in message
    assert skills_mod.list_skill_details() == []
    # 是"已停用"而不是"不存在"——提示要能区分开，否则用户会以为技能丢了
    assert "已停用" in _text(skills_mod.read_skill("order-flow"))

    ok, message = skills_mod.set_skill_disabled("order-flow", False)
    assert ok and "已重新启用" in message
    assert [s["name"] for s in skills_mod.list_skill_details()] == ["order-flow"]


def test_停用的技能不会被注册进toolkit(isolated_skill_dirs):
    skills_mod.save_skill_text("a-skill", "描述", "步骤")
    skills_mod.set_skill_disabled("a-skill", True)

    toolkit = Toolkit()
    assert skills_mod.register_skills(toolkit) == []
    assert "a-skill" not in toolkit.skills


def test_删除自建技能(isolated_skill_dirs):
    skills_mod.save_skill_text("order-flow", "描述", "步骤")
    ok, message = skills_mod.delete_skill_text("order-flow")
    assert ok and "已删除" in message
    assert skills_mod.list_skill_details() == []
    assert not (isolated_skill_dirs[0] / "order-flow").exists()


def test_随仓库发布的技能只能停用不能删除(isolated_skill_dirs):
    _, shipped = isolated_skill_dirs
    skill_dir = shipped / "shipped-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: shipped-skill\ndescription: 随仓库发布的技能\n---\n\n步骤", encoding="utf-8"
    )

    ok, message = skills_mod.delete_skill_text("shipped-skill")
    assert ok is False and "不能删除" in message
    assert skill_dir.exists()

    # 但可以停用它
    assert skills_mod.set_skill_disabled("shipped-skill", True)[0] is True
    assert skills_mod.list_skill_details() == []


def test_管理工具会同步当前会话(isolated_skill_dirs):
    toolkit = Toolkit()
    save_skill, delete_skill, set_skill_enabled = skills_mod.make_skill_tools(toolkit)

    save_skill("order-flow", "描述", "步骤")
    assert "order-flow" in toolkit.skills

    assert "已停用" in _text(set_skill_enabled("order-flow", False))
    assert "order-flow" not in toolkit.skills

    assert "已重新启用" in _text(set_skill_enabled("order-flow", True))
    assert "order-flow" in toolkit.skills

    assert "已删除" in _text(delete_skill("order-flow"))
    assert "order-flow" not in toolkit.skills


def test_读不存在的技能给出可用清单(isolated_skill_dirs):
    skills_mod.save_skill_text("order-flow", "描述", "步骤")
    message = _text(skills_mod.read_skill("nope"))
    assert "没有名为 nope 的技能" in message
    assert "order-flow" in message
