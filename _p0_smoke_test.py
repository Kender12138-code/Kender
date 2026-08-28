"""P0 三项改动的冒烟测试：填槽追问 / 结构化校验 / ReAct 轨迹。

运行（必须在 kender 目录下）：
    python _p0_smoke_test.py
"""

import asyncio

from src.memory import load_memory
from src.agent import attach_mcp_tools, create_agent, get_reply_with_trace


async def main():
    memory = load_memory()
    agent, model = create_agent(memory)
    # 接入 MCP Server（提醒能力由它提供）；失败会自动降级为进程内工具
    await attach_mcp_tools(agent.toolkit)

    questions = [
        "明天下午三点提醒我交实习周报",  # 参数齐全 → 应直接调用 set_reminder
        "帮我设个提醒",                # 缺 title + remind_time → 应追问
        "今天天气怎么样",               # 缺 city → 应追问城市
        "上海",                        # 补全参数 → 应调用 get_weather
    ]

    for q in questions:
        print("=" * 60)
        print("【用户】", q)
        reply, trace = await get_reply_with_trace(agent, model, q, memory)
        print("【回复】", reply)
        print("【轨迹】")
        print(trace[:900] if trace else "(空)")
        print()

    print("=" * 60)
    print("记忆文件当前状态：user_name =", memory.get("user_name"))


if __name__ == "__main__":
    asyncio.run(main())
