"""P1-1 MCP 接入的独立验证（不改动 Kender 主程序）。

验证三件事：
  1. stdio 传输在 Windows 上能不能跑通（这是最大的未知项）
  2. MCP Server 的工具能不能被客户端发现（list_tools）
  3. 工具能不能被真正调用（call_tool）

运行（必须在 kender 目录下）：
    python _p1_mcp_test.py
"""

import asyncio
import sys

from agentscope.mcp import StdIOStatefulClient


async def main():
    client = StdIOStatefulClient(
        name="kender-reminder",
        command=sys.executable,          # 用当前 Python 启动 Server 子进程
        args=["mcp_server/reminder_server.py"],
        cwd=None,
    )

    print("正在连接 MCP Server（stdio）…")
    await client.connect()
    print("已连接\n")

    tools = await client.list_tools()
    print(f"发现 {len(tools)} 个 MCP 工具：")
    for t in tools:
        print(f"  - {t.name}: {t.description.strip().splitlines()[0] if t.description else ''}")

    print("\n调用 add_reminder：")
    fn = await client.get_callable_function("add_reminder")
    res = await fn(title="试试 MCP 调用", remind_time="明天上午 10 点")
    text = res.content[0]["text"] if isinstance(res.content, list) else str(res)
    print(f"  {text}")

    print("\n调用 list_reminders：")
    fn2 = await client.get_callable_function("list_reminders")
    res2 = await fn2()
    text2 = res2.content[0]["text"] if isinstance(res2.content, list) else str(res2)
    print(f"  {text2}")

    await client.close()
    print("\nMCP 链路验证完成")


if __name__ == "__main__":
    asyncio.run(main())
