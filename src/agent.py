import json
import os
from datetime import datetime
from dotenv import load_dotenv
from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg
from .memory import load_memory, save_memory, build_memory_prompt
from .tools import search_web, get_current_date, retrieve_document

load_dotenv()


def create_agent(memory):
    prompt = build_memory_prompt(memory)
    # 真正把工具注册进 Agent：框架会读取函数的类型注解 + docstring 自动生成工具 schema，
    # 模型在推理时自主决定是否调用 search_web。
    toolkit = Toolkit()
    toolkit.register_tool_function(search_web)
    toolkit.register_tool_function(retrieve_document)

    model = DashScopeChatModel(
        model_name="qwen-plus",
        api_key=os.getenv("DASHSCOPE_API_KEY"),
    )
    agent = ReActAgent(
        name="Kender",
        sys_prompt=f"""你是一个温暖、贴心的生活助手，名字叫Kender。
{prompt}

当前真实日期：{get_current_date()}。这是系统直接提供的真实时间，不要质疑这个日期的合理性，不要称其为未来、设定或笔误。
你拥有联网搜索的能力（search_web 工具）。当用户询问最新资讯、实时信息、新闻、天气、股价等需要外部数据的问题时，请主动调用该工具获取最新结果后再回答。
回答要简洁、自然，不要主动列举你能做什么。""",
        model=model,
        toolkit=toolkit,
        formatter=OpenAIChatFormatter(),
    )
    return agent, model


def _extract_text(reply):
    """从 AgentScope 的回复里提取纯文本。

    不同版本 / 是否触发工具调用时，reply.content 可能是字符串、dict，
    也可能是结构化的 content blocks 列表。这里统一转成字符串，
    避免把对象结构持久化进记忆文件（原代码的 bug）。
    """

    def _to_text(obj):
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            return str(obj.get("text") or obj.get("content") or str(obj))
        return str(obj)

    # 1. 优先尝试 AgentScope Msg 的 text 属性
    if hasattr(reply, "text"):
        candidate = reply.text
        if isinstance(candidate, str) and candidate.strip():
            return candidate
        if isinstance(candidate, (list, tuple)):
            return "".join(_to_text(item) for item in candidate)

    # 2. 尝试新版 content_blocks
    if hasattr(reply, "get_content_blocks"):
        try:
            blocks = reply.get_content_blocks("text")
            if blocks:
                return "".join(_to_text(block) for block in blocks)
        except Exception:
            pass

    # 3. 回退到 content
    content = getattr(reply, "content", str(reply))
    if isinstance(content, (list, tuple)):
        return "".join(_to_text(item) for item in content)
    return _to_text(content)


async def _extract_user_info(model, user_message, reply_text, existing_facts):
    """用一次 LLM 调用，从本轮对话中结构化抽取用户信息。

    返回 (name, new_facts)：
      - name: 用户名字（str）或 None（仅当用户明确表达过名字时）
      - new_facts: 新增的事实/偏好列表（不含已存在项）

    用 LLM 结构化抽取替代脆弱的正则匹配，是"持续学习"能力的核心。
    """
    if not user_message or not reply_text:
        return None, []

    existing = "\n".join(f"- {f}" for f in existing_facts[-10:])
    prompt = f"""请从以下一轮对话中，抽取关于用户的信息，只返回一个 JSON 对象字符串：
{{
  "name": 用户的名字（仅当用户明确说"我叫XX"/"我的名字是XX"时填写，否则为 null），
  "facts": 关于用户的重要事实或偏好数组（每条不超过30字，仅抽取用户直接表达的，不要推测、不要编造）
}}
如果本轮没有新信息，返回 {{"name": null, "facts": []}}。
已有事实（不要重复）：
{existing if existing else "无"}

用户：{user_message}
助手：{reply_text}

输出必须是合法 JSON 对象，不要加任何解释、不要 markdown 代码块。"""

    try:
        res = await model(messages=[{"role": "user", "content": prompt}])
        text = _extract_text(res).strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:-1]).strip()
            if text.startswith("json"):
                text = text[4:].strip()
        data = json.loads(text)
        if not isinstance(data, dict):
            return None, []
        name = data.get("name")
        facts = data.get("facts", [])
        new_facts = []
        seen = set(existing_facts)
        if isinstance(facts, list):
            for item in facts:
                if isinstance(item, str) and item.strip() and item.strip() not in seen:
                    new_facts.append(item.strip())
                    seen.add(item.strip())
        if isinstance(name, str) and 1 < len(name) <= 20:
            return name, new_facts
        return None, new_facts
    except Exception:
        return None, []


async def get_reply(agent, model, user_message, memory):
    full_message = f"{get_current_date()}\n\n用户的问题：{user_message}"
    msg = Msg(name="user", role="user", content=full_message)
    msg.id = f"msg_{int(datetime.now().timestamp())}"
    try:
        reply = await agent.reply(msg)
    except Exception as e:
        # 模型调用 / 工具执行失败时不让 UI 崩溃，返回友好提示
        return f"⚠️ 抱歉，调用模型时出错了：{e}。请检查网络或 DASHSCOPE_API_KEY 后重试。"
    reply_text = _extract_text(reply)

    # 用一次 LLM 调用结构化抽取用户信息（名字 + 事实），替代脆弱正则
    user_name, new_facts = await _extract_user_info(
        model, user_message, reply_text, memory.get("key_facts", [])
    )
    if user_name:
        memory["user_name"] = user_name
    if new_facts:
        memory.setdefault("key_facts", []).extend(new_facts)
        memory["key_facts"] = memory["key_facts"][-15:]

    # 注：多轮连贯性由 AgentScope 内部记忆（同一 agent 实例跨轮累积）保证；
    # 此处 chat_history 是长期记忆的持久化备份，存完整内容以备将来回灌。
    memory["chat_history"].append({"role": "user", "content": user_message})
    memory["chat_history"].append({"role": "assistant", "content": reply_text})
    if len(memory["chat_history"]) > 100:
        memory["chat_history"] = memory["chat_history"][-100:]
    save_memory(memory)
    return reply_text
