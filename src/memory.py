import json
import os
from pathlib import Path

# ⚠️ 修复（2026-09-09）：原来用相对路径 "data/..."，一旦进程的工作目录不是项目根目录
# （容器部署、定时任务、别处调用脚本都会遇到），记忆就会写到别的地方或直接丢失，
# 表现为"长期记忆时灵时不灵"。改成基于文件位置推算的绝对路径。
_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
HISTORY_FILE = str(_DATA_DIR / "kender_memory.json")


def load_memory():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"user_name": None, "key_facts": [], "chat_history": []}


def save_memory(memory):
    """写入长期记忆。写入失败要打印原因，绝不静默吞掉——
    记忆丢失是这个项目最容易复发的故障，必须留痕。"""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"[memory-save] 写入失败（记忆未保存）：{type(e).__name__}: {e}")
        return False

def build_memory_prompt(memory):
    parts = []
    if memory.get("user_name"):
        parts.append(f"用户的名字是：{memory['user_name']}")
    if memory.get("key_facts"):
        facts = "\n  - ".join(memory["key_facts"][-5:])
        parts.append(f"关于用户，你已经知道的事实：\n  - {facts}")
    return "\n".join(parts) if parts else "你还不知道用户的名字和背景。"