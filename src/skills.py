"""Kender 的技能机制：让 agent 能被"教"会新流程（客户自己写技能）。

一个技能 = 一个目录 + 一份 SKILL.md（YAML front matter 里必须有 name 和
description）。注册进 AgentScope 的 Toolkit 后，ReActAgent 每次回复都会把
「技能名 + 描述 + 目录」拼进系统提示词（见 agentscope/agent/_react_agent.py 的
sys_prompt 属性）；模型判断要用某个技能时，再调 read_skill 读完整正文。
这就是渐进式披露：先给索引，再给正文，不把所有技能全文塞进上下文。

两类技能目录：
- skills/        随仓库发布、能进 git（示例技能）
- data/skills/   运行时由用户或 Kender 自己写出来的（data/ 已 gitignore）

为什么对写入校验这么严：技能正文是"写进模型自己的指令"，等于让模型给自己下命令。
名字限死小写连字符（顺带挡掉 ../ 这类路径穿越）、描述必填限长（它是唯一参与
"该不该用这个技能"判断的字段）、正文限长（每轮都可能被读进上下文）、总数设上限
（防止攒成垃圾场）。宁可拒绝一次写入，也不要把脏技能塞进系统提示词。
"""
from __future__ import annotations

import re
import json
import shutil
from pathlib import Path
from typing import Callable

from agentscope.tool import ToolResponse

from .paths import data_path, ensure_data_dir

SHIPPED_SKILLS_DIR = str(Path(__file__).resolve().parents[1] / "skills")
CUSTOM_SKILLS_DIR = data_path("skills")

MAX_SKILLS = 50
MAX_BODY_CHARS = 8000
MAX_DESCRIPTION_CHARS = 300
DISABLED_FILE_NAME = "_disabled.json"
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _text(message: str) -> ToolResponse:
    return ToolResponse(content=[{"type": "text", "text": message}])


def _parse_skill_md(path: Path) -> dict:
    """读一份 SKILL.md，返回 {name, description, body, dir, path}；不合法抛 ValueError。"""
    import frontmatter  # 与 AgentScope 的 register_agent_skill 用同一个库，口径一致

    post = frontmatter.load(str(path))
    name = str(post.get("name") or "").strip()
    description = str(post.get("description") or "").strip()
    if not name or not description:
        raise ValueError("front matter 缺少 name 或 description")
    return {
        "name": name,
        "description": description,
        "body": post.content.strip(),
        "dir": str(path.parent),
        "path": str(path),
    }


def _scan(base_dir: str) -> list[dict]:
    """扫一个技能根目录；坏技能只打印告警，不能让整个 agent 起不来。"""
    base = Path(base_dir)
    if not base.is_dir():
        return []
    found: list[dict] = []
    for child in sorted(base.iterdir()):
        skill_md = child / "SKILL.md"
        if not child.is_dir() or not skill_md.is_file():
            continue
        try:
            found.append(_parse_skill_md(skill_md))
        except Exception as exc:  # noqa: BLE001
            print(f"[skills] 跳过 {child.name}：{exc}")
    return found


def _merged_skills() -> list[dict]:
    """扫出来的全部技能（含已停用的）；同名时以先扫到的为准（仓库发布的优先）。"""
    merged: dict[str, dict] = {}
    for item in _scan(SHIPPED_SKILLS_DIR) + _scan(CUSTOM_SKILLS_DIR):
        if item["name"] in merged:
            print(f"[skills] 忽略重复技能 {item['name']}（{item['path']}）")
            continue
        merged[item["name"]] = item
    return list(merged.values())


def _disabled_path() -> Path:
    return Path(CUSTOM_SKILLS_DIR) / DISABLED_FILE_NAME


def disabled_skill_names() -> set[str]:
    """读停用名单（data/skills/_disabled.json）；文件缺失或损坏时按"没人被停用"处理。"""
    try:
        data = json.loads(_disabled_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()
    return {str(x) for x in data} if isinstance(data, list) else set()


def _write_disabled(names: set[str]) -> None:
    ensure_data_dir()
    path = _disabled_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(names), ensure_ascii=False, indent=2), encoding="utf-8")


def find_skill_any(name: str) -> dict | None:
    """不看停用状态地找技能本身（删除 / 启停这类管理操作要用它）。"""
    for item in _merged_skills():
        if item["name"] == name:
            return item
    return None


def list_skill_details() -> list[dict]:
    """返回所有**启用中**的技能。"""
    disabled = disabled_skill_names()
    return [s for s in _merged_skills() if s["name"] not in disabled]


def find_skill(name: str) -> dict | None:
    for item in list_skill_details():
        if item["name"] == name:
            return item
    return None


def save_skill_text(name: str, description: str, body: str) -> tuple[bool, str]:
    """把一份技能写到 data/skills/<name>/SKILL.md。

    技能名会被规范化成小写（模型偶尔会写成 Order-Flow，直接拒绝太苛刻），
    规范化之后仍不合法才拒绝。

    Returns:
        (是否成功, 给模型看的说明)
    """
    import frontmatter

    name = (name or "").strip().lower()
    description = (description or "").strip()
    body = (body or "").strip()

    if not SKILL_NAME_RE.match(name):
        return False, "技能名不合法：只能用字母、数字和连字符，且以字母或数字开头（会自动转小写，例如 order-flow）。"
    if not description:
        return False, "description 不能为空：它决定 Kender 什么时候会自动用这个技能，要写清触发场景。"
    if len(description) > MAX_DESCRIPTION_CHARS:
        return False, f"description 太长（{len(description)} 字 > 上限 {MAX_DESCRIPTION_CHARS}），压缩到一两句话。"
    if not body:
        return False, "技能正文不能为空：请写出可执行的步骤。"
    if len(body) > MAX_BODY_CHARS:
        return False, f"技能正文太长（{len(body)} 字 > 上限 {MAX_BODY_CHARS}），请精简步骤。"

    existing = find_skill(name)
    custom_root = Path(CUSTOM_SKILLS_DIR)
    if existing and Path(existing["path"]).parent.parent != custom_root:
        return False, f"技能名 {name} 已被随仓库发布的技能占用，请换个名字。"
    if not existing and len(list_skill_details()) >= MAX_SKILLS:
        return False, f"技能总数已达上限 {MAX_SKILLS} 个，请先删掉不再需要的技能。"

    ensure_data_dir()
    skill_dir = custom_root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, name=name, description=description)
    (skill_dir / "SKILL.md").write_text(frontmatter.dumps(post), encoding="utf-8")
    return True, f"技能 {name} 已保存到 {skill_dir / 'SKILL.md'}"


def delete_skill_text(name: str) -> tuple[bool, str]:
    """删掉一个自建技能（data/skills/<name>）。

    随仓库发布的技能不允许删（那是代码资产，删了会让别人的环境不一致），只能停用。
    """
    name = (name or "").strip().lower()
    item = find_skill_any(name)
    if not item:
        return False, f"没有名为 {name} 的技能。"

    skill_dir = Path(item["path"]).parent
    if skill_dir.parent != Path(CUSTOM_SKILLS_DIR):
        return False, f"{name} 是随仓库发布的技能，不能删除；可以改成停用（set_skill_enabled）。"

    shutil.rmtree(skill_dir)
    # 停用名单里残留同名条目的话一并清掉，否则以后新建同名技能一出生就是停用的
    names = disabled_skill_names()
    if name in names:
        names.discard(name)
        _write_disabled(names)
    return True, f"技能 {name} 已删除（{skill_dir}）。"


def set_skill_disabled(name: str, disabled: bool) -> tuple[bool, str]:
    """停用 / 启用一个技能：只改停用名单，不动 SKILL.md 内容。"""
    name = (name or "").strip().lower()
    if not find_skill_any(name):
        return False, f"没有名为 {name} 的技能。"

    names = disabled_skill_names()
    if disabled and name not in names:
        names.add(name)
        _write_disabled(names)
        return True, f"技能 {name} 已停用（文件保留，随时可以再启用）。"
    if not disabled and name in names:
        names.discard(name)
        _write_disabled(names)
        return True, f"技能 {name} 已重新启用。"
    return True, f"技能 {name} 本来就是{'停用' if disabled else '启用'}状态，未做改动。"


def register_skills(toolkit) -> list[str]:
    """把技能注册进 AgentScope 的 Toolkit（同名重复注册只跳过，不抛错）。"""
    registered: list[str] = []
    for item in list_skill_details():
        try:
            toolkit.register_agent_skill(item["dir"])
            registered.append(item["name"])
        except ValueError as exc:
            print(f"[skills] 跳过 {item['name']}：{exc}")
    return registered


def list_skills() -> ToolResponse:
    """列出当前所有可用技能（技能名 + 什么时候该用）。

    当你不确定用户的任务该不该套用某个技能时，先调用本工具看清单。

    Returns:
        ToolResponse: 技能清单；没有任何技能时说明这一点。
    """
    all_skills = _merged_skills()
    disabled = disabled_skill_names()
    enabled = [s for s in all_skills if s["name"] not in disabled]
    paused = [s["name"] for s in all_skills if s["name"] in disabled]

    if not enabled:
        text = "当前还没有任何启用的技能。"
    else:
        lines = [f"- {item['name']}：{item['description']}" for item in enabled]
        text = "当前可用技能：\n" + "\n".join(lines)
    if paused:
        text += "\n\n已停用（不在技能清单里，需要时可以用 set_skill_enabled 打开）：" + "、".join(paused)
    return _text(text)


def read_skill(name: str) -> ToolResponse:
    """读取某个技能的完整步骤（SKILL.md 正文）。

    当用户的任务命中技能清单里某条描述时，先调用本工具读它的正文，再照着正文执行，
    不要凭印象做。

    Args:
        name: 技能名，必须是技能清单里出现过的名字（见 list_skills）。

    Returns:
        ToolResponse: 技能的完整步骤；技能不存在时返回当前可用技能列表。
    """
    name = (name or "").strip().lower()
    if name in disabled_skill_names() and find_skill_any(name):
        return _text(f"技能 {name} 当前已停用。如果确实要用，先让用户用 set_skill_enabled 把它打开。")

    item = find_skill(name)
    if not item:
        available = "、".join(s["name"] for s in list_skill_details()) or "（当前没有任何技能）"
        return _text(f"没有名为 {name} 的技能。当前可用技能：{available}")
    return _text(f"# 技能 {item['name']}\n{item['description']}\n\n{item['body']}")


def make_skill_tools(toolkit) -> tuple[Callable[..., ToolResponse], ...]:
    """生成绑定到某个 toolkit 的技能管理工具：(save_skill, delete_skill, set_skill_enabled)。

    为什么要工厂而不是直接写模块级函数：Kender 的 Web 界面每个会话各建一套
    agent / toolkit（见 src/ui.py），技能改了要立刻在"当前这个会话"生效，就得注册回
    这个会话的 toolkit。用一个模块级全局变量的话，A 会话改的技能会作用到 B 会话去。
    """

    def _sync_register(name: str) -> str:
        """把磁盘上的技能同步进当前会话的 toolkit。"""
        item = find_skill_any(name)
        if not item:
            return "（没找到技能目录，未能同步到当前会话）"
        try:
            # 同名覆盖时先移除旧条目，否则 toolkit 里留的是旧 description
            toolkit.remove_agent_skill(name)
        except Exception:  # noqa: BLE001
            pass
        try:
            toolkit.register_agent_skill(item["dir"])
            return "（已在当前会话立即生效）"
        except Exception as exc:  # noqa: BLE001
            return f"（同步到当前会话失败：{exc}；重启后仍会生效）"

    def save_skill(name: str, description: str, body: str) -> ToolResponse:
        """把一套可复用的做法保存成技能，之后遇到同类任务会按它执行。

        只有在用户明确要求"记住这套做法 / 以后都按这个来"时才调用；写之前先用一句话
        跟用户确认，不要把一次性的闲聊或没验证过的做法存成技能。

        Args:
            name: 技能名，字母/数字/连字符，例如 order-flow（大写会自动转成小写）。
            description: 什么时候该用这个技能，一到两句话，写清触发场景。
            body: 技能正文，可执行的步骤，一步一行，写清输入、输出和注意点。

        Returns:
            ToolResponse: 保存结果；成功时会在当前会话立即生效。
        """
        ok, message = save_skill_text(name, description, body)
        if not ok:
            return _text(f"技能未保存：{message}")
        return _text(message + _sync_register((name or "").strip().lower()))

    def delete_skill(name: str) -> ToolResponse:
        """删掉一个自己写的技能（随仓库发布的技能删不掉，只能停用）。

        只在用户明确要求删除某个技能时调用；删之前先用一句话确认——删了不能恢复。

        Args:
            name: 要删除的技能名。

        Returns:
            ToolResponse: 删除结果；成功时当前会话也会同步移除它。
        """
        ok, message = delete_skill_text(name)
        if not ok:
            return _text(message)
        toolkit.remove_agent_skill((name or "").strip().lower())
        return _text(message + "（当前会话已同步移除）")

    def set_skill_enabled(name: str, enabled: bool) -> ToolResponse:
        """停用或重新启用一个技能（只改开关，不动技能内容）。

        用户说"先别用这个技能""把某个技能关掉"时调用它，而不是删除——文件会留着。

        Args:
            name: 技能名。
            enabled: true = 启用，false = 停用（停用后不再出现在技能清单里）。

        Returns:
            ToolResponse: 操作结果；当前会话会同步生效。
        """
        ok, message = set_skill_disabled(name, disabled=not enabled)
        if not ok:
            return _text(message)
        key = (name or "").strip().lower()
        if enabled:
            return _text(message + _sync_register(key))
        toolkit.remove_agent_skill(key)
        return _text(message + "（当前会话已同步停用）")

    return save_skill, delete_skill, set_skill_enabled
