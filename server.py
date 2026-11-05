"""Kender FastAPI 服务化（Day 2 作业完成版 + P1 升级）

目标：把 Kender 从"终端对话"变成"HTTP 对话"。
三个接口：
    GET  /health  -> 健康检查
    POST /chat    -> 发一句话给 Kender，返回回复 + ReAct 轨迹 + 审核结论

启动命令（在 kender 目录下）：
    python -m uvicorn server:app --port 8003
自测：
    浏览器打开 http://127.0.0.1:8003/docs

【相比 Day 2 版本的两处重要改动】

1. 初始化移进了 lifespan
   原来 memory / agent 写在模块顶层。接入 MCP 之后不行了：
   MCP 的 stdio 客户端会绑定到一个具体的事件循环上，而模块顶层还没有循环；
   并且老版本在每个请求里用 asyncio.run() 新建循环 —— 那样 MCP 客户端
   在 A 循环里连接、却在 B 循环里被调用，必然报错。
   放进 lifespan 后，初始化和请求都跑在 uvicorn 的同一个循环里。

2. chat 改成 async def
   原来是同步 def + 内部 asyncio.run()。改成 async 后由 uvicorn 直接调度，
   与 MCP 客户端同处一个事件循环。
"""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from src.agent import (
    attach_mcp_tools,
    create_agent,
    get_reply_with_review,
    shutdown_mcp_server,
)
from src.memory import load_memory

# 全局单例（在 lifespan 中赋值）
memory = None
agent = None
model = None

# 串行锁：所有请求共用同一个 agent 实例，而 AgentScope 的 ReActAgent 会按轮次
# 往自己的 memory 里追加消息。两个请求并发进来时，A 的 tool_use 可能被插到
# B 的对话中间，导致回答串台、轨迹错乱。这里先保证正确性（串行执行），
# 真正的多会话隔离（每个 session 一套 agent）见 README 的后续计划。
_chat_lock = asyncio.Lock()


async def run_chat_turn(message: str):
    """跑一轮对话（串行执行）。

    抽成独立函数是为了可测试：不用起 HTTP 服务就能验证并发请求不会交错。
    """
    async with _chat_lock:
        return await get_reply_with_review(agent, model, message, memory)

# 可选鉴权：设了 KENDER_API_TOKEN 才校验请求头 X-Kender-Token。
# 为什么要有：/chat 会真实消耗 DASHSCOPE_API_KEY，服务一旦监听 0.0.0.0
# （或被端口转发到公网），任何扫到 8003 的人都能烧你的额度。
# 不设 = 免密，保持本地演示 `python start_local_demo.py` 的用法不变。
API_TOKEN = os.getenv("KENDER_API_TOKEN")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动时建 agent、接 MCP；关闭时收尾。"""
    global memory, agent, model
    memory = load_memory()
    agent, model = create_agent(memory)
    # MCP 接入失败会自动降级为进程内工具，不影响服务启动
    await attach_mcp_tools(agent.toolkit)
    print("[server] Kender 服务已就绪")
    yield
    # 回收 attach_mcp_tools 拉起来的 MCP Server 子进程，别让 8100 留残兵
    shutdown_mcp_server()
    print("[server] 服务关闭")


app = FastAPI(title="Kender API", lifespan=lifespan)


class ChatBody(BaseModel):
    message: str        # 必填，用户说的话


@app.post("/chat")
async def chat(body: ChatBody, x_kender_token: str | None = Header(default=None)):
    """发消息给 Kender，返回回复 + ReAct 轨迹 + Critic 审核结论。"""
    if API_TOKEN and x_kender_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="缺少或错误的 X-Kender-Token")
    reply, trace, verdict, rounds = await run_chat_turn(body.message)
    return {
        "reply": reply,
        "trace": trace,
        "review": {
            "passed": verdict.passed,
            "reason": verdict.reason,
            "rounds": rounds,
        },
    }


@app.get("/health")
async def health():
    """健康检查接口，方便运维探活（面试可以提这个）。"""
    return {"status": "ok"}
