import json
import os

HISTORY_FILE = "data/kender_memory.json"

def load_memory():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"user_name": None, "key_facts": [], "chat_history": []}

def save_memory(memory):
    os.makedirs("data", exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

def build_memory_prompt(memory):
    parts = []
    if memory.get("user_name"):
        parts.append(f"用户的名字是：{memory['user_name']}")
    if memory.get("key_facts"):
        facts = "\n  - ".join(memory["key_facts"][-5:])
        parts.append(f"关于用户，你已经知道的事实：\n  - {facts}")
    return "\n".join(parts) if parts else "你还不知道用户的名字和背景。"