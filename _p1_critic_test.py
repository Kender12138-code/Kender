"""P1-2 检查点 Critic（评审式多 Agent）的冒烟测试。

分两部分：
  A. 单元级：直接喂给 Critic 三种场景，验证它的判断力
  B. 端到端：走完整的「生成 → 审核 → 打回重写」流程

运行（必须在 kender 目录下）：
    python _p1_critic_test.py
"""

import asyncio

from src.memory import load_memory
from src.agent import create_agent, critique_reply, get_reply_with_review


OBS = (
    "**行动** 调用 `get_weather`\n"
    "入参：`{\"city\": \"上海\"}`\n\n"
    "**观察**\n"
    "上海: ☀️ +27°C"
)

CASES = [
    (
        "应判不合格：回答与工具结果矛盾",
        "今天上海天气怎么样",
        "上海今天大雨，气温只有 12 度，出门一定记得带伞。",
        OBS,
    ),
    (
        "应判合格：回答与工具结果一致",
        "今天上海天气怎么样",
        "上海今天晴，27°C，挺适合出门的。",
        OBS,
    ),
    (
        "应判合格：正在向用户追问（填槽行为）",
        "帮我设个提醒",
        "请问提醒的内容是什么？希望什么时候提醒你？",
        "",
    ),
]


async def unit_tests(model):
    print("#" * 60)
    print("# A. Critic 单元级测试")
    print("#" * 60)
    for title, user_msg, reply, trace in CASES:
        verdict = await critique_reply(model, user_msg, reply, trace)
        flag = "通过" if verdict.passed else "不合格"
        print(f"\n场景：{title}")
        print(f"  用户：{user_msg}")
        print(f"  回答：{reply}")
        print(f"  Critic 判定：{flag} | 原因：{verdict.reason}")


async def e2e_tests(agent, model, memory):
    print()
    print("#" * 60)
    print("# B. 端到端：生成 → 审核 → 打回重写")
    print("#" * 60)
    for q in ["今天上海天气怎么样", "帮我设个提醒"]:
        print(f"\n用户：{q}")
        reply, trace, verdict, rounds = await get_reply_with_review(
            agent, model, q, memory
        )
        print(f"  最终回复：{reply[:120]}")
        print(f"  审核结论：passed={verdict.passed} | {verdict.reason} | 共 {rounds} 轮")


async def main():
    memory = load_memory()
    agent, model = create_agent(memory)
    await unit_tests(model)
    await e2e_tests(agent, model, memory)


if __name__ == "__main__":
    asyncio.run(main())
