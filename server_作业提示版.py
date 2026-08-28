"""Kender FastAPI 服务化 — Day 2 作业（原始提示版，仅存档对照用，勿运行）

用途：和 server.py（完成版）对比着看，分析"提示 → 答案"的映射关系。
启动请用完成版：python -m uvicorn server:app --port 8002
"""

# ============ TODO 1：导入（2 分钟）============
# 需要 import 三样东西：
#   1. asyncio     （Python 自带，用来跑 async 函数）
#   2. FastAPI     （Day 1 学过：from fastapi import FastAPI）
#   3. BaseModel   （Day 1 学过：from pydantic import BaseModel）
import asyncio
# 你的代码写这里 👇（补两行 import）


# ============ TODO 2：导入 Kender 三件套（2 分钟）============
# 打开 main.py 看第 18-19 行，它从 src 导入了三个函数：
#   load_memory / create_agent / get_reply
# 照抄那两行的 from 语句（server.py 和 main.py 在同一个目录）
# 你的代码写这里 👇


# ============ TODO 3：全局初始化（1 分钟）============
# 看 main.py 第 20-21 行，抄下来。
# 注意：这段代码必须在"模块顶层"（不缩进、不在函数里），
# 因为 agent 要全局只创建一次——每个请求都新建 agent 的话，
# 多轮对话的连贯性就没了，还会反复加载记忆、浪费 API 调用。
# 你的代码写这里 👇


# ============ TODO 4：创建 app（30 秒）============
# Day 1 学过：app = FastAPI(title="...")，title 起个 "Kender API"
# 你的代码写这里 👇


# ============ TODO 5：请求体模型 ChatBody（3 分钟）============
# 参考 Day 1 的 EchoBody，定义：
#   message: str   （必填，用户说的话）
# 你的代码写这里 👇


# ============ TODO 6：POST /chat（10 分钟，核心！）============
# 目标：收到 {"message": "你好"}  ->  返回 {"reply": "Kender 的回复"}
#
# 三个关键点（不会就按这三步拼）：
#   1. 用 @app.post("/chat") 装饰器
#   2. 函数签名：def chat(body: ChatBody):   （跟 Day 1 的 echo 一模一样）
#   3. 函数体里只有一件事：
#        reply = asyncio.run(get_reply(agent, model, body.message, memory))
#        return {"reply": reply}
#
# 为什么用 asyncio.run？因为 get_reply 是 async 函数
# （main.py 第 27 行也是这么调用的），而你的 chat 函数是普通同步函数，
# 里面不能直接 await，所以用 asyncio.run 包一层。
# 你的代码写这里 👇


# ============ TODO 7：GET /health（3 分钟，加分项）============
# 最简单的接口：return {"status": "ok"}
# 面试时可以说"我写了健康检查接口，方便运维探活"
# 你的代码写这里 👇
