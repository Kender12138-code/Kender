"""Kender FastAPI 服务化（Day 2 作业完成版 + P1 升级）

目标：把 Kender 从"终端对话"变成"HTTP 对话"。
三个接口：
    GET  /health  -> 健康检查
    POST /chat    -> 发一句话给 Kender，返回回复 + ReAct 轨迹 + 审核结论

启动命令（在 kender 目录下）：
    python -m uvicorn server:app --port 8002
自测：
    浏览器打开 http://127.0.0.1:8002/docs

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

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from src.agent import attach_mcp_tools, create_agent, get_reply_with_review
from src.memory import load_memory

# 全局单例（在 lifespan 中赋值）
memory = None
agent = None
model = None


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
    print("[server] 服务关闭")


app = FastAPI(title="Kender API", lifespan=lifespan)


class ChatBody(BaseModel):
    message: str        # 必填，用户说的话


@app.post("/chat")
async def chat(body: ChatBody):
    """发消息给 Kender，返回回复 + ReAct 轨迹 + Critic 审核结论。"""
    reply, trace, verdict, rounds = await get_reply_with_review(
        agent, model, body.message, memory
    )
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
