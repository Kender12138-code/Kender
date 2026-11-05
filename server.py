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
from collections import OrderedDict
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

# 会话表：session_id -> {agent, model, memory, lock}
# 为什么需要：原来所有请求共用一个 agent，两个用户会往同一份 memory 里写，
# 而且一个人问长问题时另一个人只能干等（全局锁）。
# 现在按 session 隔离：各自的 agent、各自的记忆、各自的锁，互不阻塞。
SESSIONS: "OrderedDict[str, dict]" = OrderedDict()
MAX_SESSIONS = int(os.getenv("KENDER_MAX_SESSIONS", "8"))

# 兼容旧代码/测试的引用（默认会话的内部对象在 lifespan 里赋值）
memory = None
agent = None
model = None


def _blank_memory() -> dict:
    return {"user_name": None, "key_facts": [], "chat_history": []}


async def _build_session(session_id: str) -> dict:
    """新建一个会话：独立 agent + 独立记忆 + 独立锁。

    只有 default 会话读盘上的长期记忆；其它会话从空白开始，
    避免 A 用户的偏好泄漏给 B 用户。
    """
    mem = load_memory() if session_id == "default" else _blank_memory()
    ag, md = create_agent(mem)
    await attach_mcp_tools(ag.toolkit)  # MCP 子进程会被复用，不会重复启动
    return {"agent": ag, "model": md, "memory": mem, "lock": asyncio.Lock()}


async def get_session(session_id: str = "default") -> dict:
    sid = (session_id or "default").strip() or "default"
    session = SESSIONS.get(sid)
    if session is not None:
        SESSIONS.move_to_end(sid)  # LRU：常用会话不会被淘汰
        return session

    session = await _build_session(sid)
    SESSIONS[sid] = session
    while len(SESSIONS) > MAX_SESSIONS:
        SESSIONS.popitem(last=False)
    return session


async def run_chat_turn(message: str, session_id: str = "default"):
    """跑一轮对话（会话内串行、会话间并行）。

    抽成独立函数是为了可测试：不用起 HTTP 服务就能验证
    "同会话串行、不同会话互不阻塞"。
    """
    session = await get_session(session_id)
    async with session["lock"]:
        return await get_reply_with_review(
            session["agent"], session["model"], message, session["memory"]
        )

# 可选鉴权：设了 KENDER_API_TOKEN 才校验请求头 X-Kender-Token。
# 为什么要有：/chat 会真实消耗 DASHSCOPE_API_KEY，服务一旦监听 0.0.0.0
# （或被端口转发到公网），任何扫到 8003 的人都能烧你的额度。
# 不设 = 免密，保持本地演示 `python start_local_demo.py` 的用法不变。
API_TOKEN = os.getenv("KENDER_API_TOKEN")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动时预热默认会话；关闭时收尾。"""
    global memory, agent, model
    default = await get_session("default")
    memory, agent, model = default["memory"], default["agent"], default["model"]
    print(f"[server] Kender 服务已就绪（默认会话已预热，最多 {MAX_SESSIONS} 个会话）")
    yield
    # 回收 attach_mcp_tools 拉起来的 MCP Server 子进程，别让 8100 留残兵
    shutdown_mcp_server()
    print("[server] 服务关闭")


app = FastAPI(title="Kender API", lifespan=lifespan)


class ChatBody(BaseModel):
    message: str
    session_id: str = "default"  # 不同会话各自独立记忆；不传就是 default


@app.post("/chat")
async def chat(body: ChatBody, x_kender_token: str | None = Header(default=None)):
    """发消息给 Kender，返回回复 + ReAct 轨迹 + Critic 审核结论。"""
    if API_TOKEN and x_kender_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="缺少或错误的 X-Kender-Token")
    reply, trace, verdict, rounds = await run_chat_turn(body.message, body.session_id)
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
