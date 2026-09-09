"""临时诊断脚本：只测「长期记忆抽取」这一段，不跑完整 Agent。

用法（在 kender 目录）：python diag_memory.py
"""
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from agentscope.model import DashScopeChatModel

from src.agent import _extract_user_info, _call_model_text
from src.memory import load_memory, save_memory, HISTORY_FILE

MODEL_NAME = os.getenv("KENDER_MODEL", "qwen-plus")


async def main():
    model = DashScopeChatModel(
        model_name=MODEL_NAME,
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        stream=True,
    )
    print("memory file:", Path(HISTORY_FILE).resolve())

    # 1. 先测最底层的模型文本调用是否还能拿到文本
    try:
        t = await _call_model_text(model, "请只输出 JSON：{\"ok\": true}")
        print("[call_model_text] ->", repr(t[:120]))
    except Exception as e:
        print("[call_model_text] EXCEPTION:", type(e).__name__, e)
        return

    # 2. 再测结构化抽取（两个用例：说名字 / 不说名字）
    mem = load_memory()
    print("existing facts:", mem.get("key_facts"))
    cases = [
        ("我叫李四，我下周三要去深圳出差，另外我不吃香菜", "用例A（带名字）"),
        ("我养了一只叫豆豆的猫，平时喜欢打羽毛球", "用例B（不带名字）"),
    ]
    for msg, label in cases:
        try:
            name, facts = await _extract_user_info(
                model, msg, "好的，我记住了。", mem.get("key_facts", [])
            )
            print(f"[extract] {label}: name = {name} | facts = {facts}")
        except Exception as e:
            print(f"[extract] {label} EXCEPTION:", type(e).__name__, e)
            import traceback

            traceback.print_exc()

    # 3. 测写入
    try:
        mem["key_facts"].append("__diag_test__")
        save_memory(mem)
        print("[save_memory] ok, 已写入测试标记")
        mem2 = load_memory()
        print("[reload] 读到:", mem2.get("key_facts")[-1:])
        mem2["key_facts"] = [f for f in mem2["key_facts"] if f != "__diag_test__"]
        save_memory(mem2)
        print("[cleanup] 测试标记已清除")
    except Exception as e:
        print("[save_memory] EXCEPTION:", type(e).__name__, e)


if __name__ == "__main__":
    asyncio.run(main())
