"""Kender 的提醒能力 MCP Server（stdio 传输）。

这是一个**独立进程**：Kender 主程序不直接 import 它，
而是通过 MCP 协议（JSON-RPC over stdio）去调用它提供的工具。

为什么要这么绕？这正是 MCP 的意义所在：
    进程内函数（Function Call）  ->  只能被本进程、本语言的程序调用
    MCP Server（协议层）         ->  任何支持 MCP 的客户端都能调用，
                                     可以换语言实现、可以独立部署、可以给别人复用

面试关键区分：
    Function Call 是"实现层"（模型自主决策 + 结构化调用）
    MCP          是"协议层"（定义工具怎么被发现和接入）
    二者不是一回事，混为一谈会被扣分。

两种传输方式：
    stdio（默认）        python mcp_server/reminder_server.py
    streamable-http     python mcp_server/reminder_server.py --http 8100

【为什么 Web 场景必须用 HTTP 而不是 stdio】
stdio 客户端会在调用方所在的 asyncio task 里创建 anyio cancel scope；
Web 服务里「建立连接」发生在启动阶段（lifespan），「调用工具」发生在请求处理
阶段，两者是不同的 task，anyio 会直接抛：
    RuntimeError: Attempted to exit cancel scope in a different task
                  than it was entered in
HTTP 是无状态的，不存在这个问题。CLI 单任务场景下 stdio 仍然可用。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# data 目录相对项目根（与 memory.py 的约定一致）
REMINDER_FILE = Path("data/reminders.json")

mcp = FastMCP("kender-reminder")


def _load() -> list:
    if not REMINDER_FILE.exists():
        return []
    try:
        with open(REMINDER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(items: list) -> None:
    REMINDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REMINDER_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


@mcp.tool()
def add_reminder(title: str, remind_time: str) -> str:
    """创建一个提醒事项。

    当用户表达"提醒我…""帮我记一下…""别忘了…"这类意图时调用。
    title 和 remind_time 都是必填参数；用户没说清楚时必须先追问，不要猜测。

    Args:
        title: 提醒的具体内容，例如"交实习周报"、"取快递"。
        remind_time: 提醒时间，例如"今晚 20:00"、"明天上午 9 点"、"下周一"。

    Returns:
        创建结果，以及当前全部提醒列表。
    """
    items = _load()
    items.append(
        {
            "title": title,
            "time": remind_time,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": "mcp",
        }
    )
    _save(items)

    listing = "\n".join(
        f"{i + 1}. {it['time']} —— {it['title']}" for i, it in enumerate(items)
    )
    return f"提醒已创建成功（通过 MCP Server）。当前共有 {len(items)} 条提醒：\n{listing}"


@mcp.tool()
def list_reminders() -> str:
    """列出当前已创建的全部提醒事项。

    当用户询问"我有哪些提醒""我让你提醒我什么来着""提醒列表"时调用。

    Returns:
        全部提醒列表；如果还没有任何提醒，返回相应提示。
    """
    items = _load()
    if not items:
        return "目前还没有任何提醒事项。"
    listing = "\n".join(
        f"{i + 1}. {it['time']} —— {it['title']}" for i, it in enumerate(items)
    )
    return f"当前共有 {len(items)} 条提醒：\n{listing}"


if __name__ == "__main__":
    # --http <port> 走 streamable-http（Web 服务用）；不带参数走 stdio（CLI / 自测用）
    if len(sys.argv) >= 3 and sys.argv[1] == "--http":
        port = int(sys.argv[2])
        # FastMCP.run() 不接受 host/port 关键字参数，要通过 settings 设置
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = port
        print(f"[mcp-server] streamable-http 模式启动："
              f"http://{mcp.settings.host}:{port}/mcp", flush=True)
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
