import asyncio
import json
import os
import re
import sys
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv
from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg
from .memory import load_memory, save_memory, build_memory_prompt
from .tools import (
    search_web,
    get_weather,
    get_current_date,
    retrieve_document,
    set_reminder,
)

load_dotenv()


# ===================== MCP 接入（协议层）=====================
# 与工具函数的区别，面试务必讲清：
#   register_tool_function  -> 进程内函数，Function Call 的"实现层"
#   register_mcp_client     -> 连接独立 MCP Server，"协议层"
# MCP Server 是独立进程（可以是别的语言写的），Kender 通过 JSON-RPC over stdio 调用它。

MCP_SERVER_SCRIPT = "mcp_server/reminder_server.py"
MCP_HTTP_PORT = int(os.getenv("KENDER_MCP_PORT", "8100"))
MCP_HTTP_URL = f"http://127.0.0.1:{MCP_HTTP_PORT}/mcp"

_mcp_proc = None


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    """判断端口是否已经在监听（用来确认 MCP Server 是否启动完成）。"""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _start_mcp_server() -> bool:
    """后台启动 MCP Server（HTTP 传输），等端口就绪后返回 True。"""
    global _mcp_proc

    if _port_open(MCP_HTTP_PORT):
        return True  # 已经在跑，直接复用

    try:
        import subprocess

        # 关键：不要把子进程的 stdout 接成 PIPE 又不读。
        # MCP Server 内部也是 uvicorn，会持续往 stdout 打日志；
        # 管道缓冲区被写满后子进程会卡死，导致后续所有工具调用超时。
        # 这里改为写日志文件，既能排错又不会堵。
        try:
            from .paths import data_path, ensure_data_dir

            ensure_data_dir()
            logf = open(data_path("mcp_server.log"), "a", encoding="utf-8")
        except Exception:
            logf = subprocess.DEVNULL

        _mcp_proc = subprocess.Popen(
            [sys.executable, MCP_SERVER_SCRIPT, "--http", str(MCP_HTTP_PORT)],
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
        # 轮询等待端口就绪，最多等 20 秒
        for _ in range(40):
            if _port_open(MCP_HTTP_PORT):
                print(f"[mcp] MCP Server 已启动：{MCP_HTTP_URL}")
                return True
            if _mcp_proc.poll() is not None:
                print("[mcp] MCP Server 进程意外退出")
                return False
            time.sleep(0.5)
        print("[mcp] 等待 MCP Server 启动超时")
        return False
    except Exception as e:
        print(f"[mcp] 启动 MCP Server 失败：{e}")
        return False


def shutdown_mcp_server() -> bool:
    """回收本进程启动的 MCP Server 子进程（进程退出前调用）。

    为什么需要：_start_mcp_server 起的子进程不会随父进程一起消失，
    父进程退出后它继续占着 8100，下次演示就会撞上"端口被占用"。

    只结束"自己拉起来的"那个进程：如果 8100 上是别人先起的服务
    （_start_mcp_server 的复用分支），_mcp_proc 是 None，这里什么都不做。

    Returns:
        True 表示确实停掉了一个子进程，False 表示没有需要停的。
    """
    global _mcp_proc

    if _mcp_proc is None:
        return False

    import subprocess

    proc, _mcp_proc = _mcp_proc, None
    if proc.poll() is not None:
        return False

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    print(f"[mcp] 已停止 MCP Server 子进程（pid={proc.pid}）")
    return True


async def attach_mcp_tools(toolkit, enabled: bool = True):
    """连接 MCP Server 并把它的工具注册进 toolkit。

    设计原则：MCP 是"增强"，不是"依赖"。
    连接失败时打印日志并降级 —— Kender 保留进程内的 set_reminder 等工具照常工作，
    绝不能因为 MCP 挂了就让整个 Agent 不可用。

    Args:
        toolkit: AgentScope 的 Toolkit 实例。
        enabled: 是否启用 MCP（可用环境变量 KENDER_ENABLE_MCP=0 关闭）。

    Returns:
        成功注册的 MCP 工具名列表（失败则为空列表）。
    """
    if not enabled or os.getenv("KENDER_ENABLE_MCP", "1") == "0":
        print("[mcp] 已禁用，使用进程内工具")
        return []

    if not os.path.exists(MCP_SERVER_SCRIPT):
        print(f"[mcp] 未找到 MCP Server 脚本 {MCP_SERVER_SCRIPT}，跳过接入")
        return []

    try:
        import sys

        from agentscope.mcp import HttpStatelessClient

        # 用 HTTP 而非 stdio：Web 服务里连接和调用分属不同的 asyncio task，
        # stdio 客户端的 anyio cancel scope 不允许跨 task 退出，必然报错。
        if not _start_mcp_server():
            raise RuntimeError("MCP Server 未能启动")

        client = HttpStatelessClient(
            name="kender-reminder",
            transport="streamable_http",
            url=MCP_HTTP_URL,
        )
        # 无状态 HTTP 客户端没有 connect 方法（也不需要）；
        # 这里用 hasattr 兜一层，将来换回有状态传输时不用改代码
        if hasattr(client, "connect"):
            await client.connect()
        await toolkit.register_mcp_client(client)
        names = [t.name for t in await client.list_tools()]
        print(f"[mcp] 已接入 MCP Server（{MCP_HTTP_URL}），工具：{names}")
        return names
    except Exception as e:
        # 降级：把进程内的提醒工具补注册回来，保证提醒能力不消失
        print(f"[mcp] 接入失败，降级为进程内工具：{e}")
        try:
            toolkit.register_tool_function(set_reminder)
            print("[mcp] 已降级注册本地 set_reminder")
        except Exception as e2:
            print(f"[mcp] 降级注册也失败了：{e2}")
        return []


def create_agent(memory):
    prompt = build_memory_prompt(memory)
    # 真正把工具注册进 Agent：框架会读取函数的类型注解 + docstring 自动生成工具 schema，
    # 模型在推理时自主决定是否调用 search_web。
    toolkit = Toolkit()
    toolkit.register_tool_function(search_web)
    toolkit.register_tool_function(get_weather)
    toolkit.register_tool_function(retrieve_document)
    # 自然语言查本地业务库：属于可选能力，没装 openai 或没配 DB 就自动跳过，
    # 不影响其它工具与既有功能。
    try:
        from src.db_tool import query_database

        toolkit.register_tool_function(query_database)
    except Exception as exc:  # noqa: BLE001
        print(f"[toolkit] 数据库问答工具未启用：{exc}")
    # 技能机制：把 skills/ 与 data/skills/ 下的技能注册进 toolkit，并把
    # 「列技能 / 读技能 / 存技能」三个工具交给模型。注册之后 AgentScope 会自动
    # 把技能清单拼进系统提示词（细节见 src/skills.py 的模块注释）。
    try:
        from src.skills import list_skills, make_skill_tools, read_skill, register_skills

        skill_names = register_skills(toolkit)
        toolkit.register_tool_function(list_skills)
        toolkit.register_tool_function(read_skill)
        for skill_tool in make_skill_tools(toolkit):
            toolkit.register_tool_function(skill_tool)
        print(f"[skills] 已启用 {len(skill_names)} 个技能：{skill_names}")
    except Exception as exc:  # noqa: BLE001
        print(f"[toolkit] 技能机制未启用：{exc}")
    # 提醒能力默认由 MCP Server 提供（见 attach_mcp_tools）；
    # MCP 接入失败时，才把进程内的 set_reminder 作为降级方案补注册回来。

    model = DashScopeChatModel(
        model_name="qwen-plus",
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        # 温度默认 0.3：默认采样温度下，同一个问题多次运行会时而调工具、
        # 时而凭记忆作答（eval 里 MT03/H02 都复现过）。工具调用类任务要的是
        # 稳定，不是文采。想更自然可以设 KENDER_TEMPERATURE=0.7。
        generate_kwargs={"temperature": float(os.getenv("KENDER_TEMPERATURE", "0.3"))},
    )
    # 有文档索引时主动告诉模型一声：否则它看到"这个项目/团队"这类指代，
    # 会直接反问用户"是哪个项目"，而不会想到去检索已上传的文档。
    doc_hint = ""
    try:
        from src.rag import index_exists

        if index_exists():
            doc_hint = (
                "\n【文档状态】用户已经上传过文档，向量索引已就绪。"
                "遇到「这个项目 / 这个团队 / 这个方案 / 我的文档」这类指代，"
                "或者你缺少回答所需的信息时，先调用 retrieve_document 检索，再作答。"
            )
    except Exception:  # noqa: BLE001
        pass

    agent = ReActAgent(
        name="Kender",
        sys_prompt=f"""你是一个温暖、贴心的生活助手，名字叫Kender。
{prompt}

当前真实日期：{get_current_date()}。这是系统直接提供的真实时间，不要质疑这个日期的合理性，不要称其为未来、设定或笔误。
你拥有以下工具：
1. search_web：联网搜索最新资讯、新闻、股价等。
2. get_weather：查询指定城市实时天气。当用户询问天气时，必须优先调用本工具，city 参数使用用户提到的城市名（如"上海"）。
3. retrieve_document：从用户已上传的文档中检索内容。
4. 提醒工具：可以创建提醒事项、查看已有提醒（由 MCP Server 提供）。
   创建提醒时「提醒内容」与「提醒时间」都是必填的，缺一不可。
5. 技能工具：list_skills 列出已有技能，read_skill 读某个技能的完整步骤，save_skill 存新技能，delete_skill 删掉自己写的技能，set_skill_enabled 停用或重新启用技能。

工具调用规则：
- 先调用工具获取结果，再用简洁、自然的语言回答。如果工具调用失败或返回空，请如实说明，不要编造。
- 【实时信息必须取证】凡是会随时间变化的信息（天气、气温、股价、指数、汇率、新闻、比分、航班），
  必须先调用对应工具；没有工具返回结果时，只能说"暂时查不到"，禁止给出具体数值，
  也禁止使用工具的返回格式（如"城市: 图标 温度"）自行拼接一条数据。
- 【只转述不脑补】工具返回了什么就说什么。可以把工具返回的英文天气描述翻成中文，
  但不能添加工具没给的细节——工具只给了温度，就不要说"晴/小雨/多云"。
  同理，检索没给出具体片名/商品名/书名时，不要"举例"编几个出来。
- 【不得外推】用户问的是未来（明天、下周、未来几天）而工具只能返回当前值时，
  必须说明"拿不到该时段的数据"，禁止把当前值当成预报，也禁止给出"明天同样是 X"
  这类推断。同理，问历史数据时也不能用当前值代替。
- 【被质疑要核实】用户质疑你之前说过的实时数据（"你刚才说是吗""真的吗""确认一下"），
  必须调用工具重新核实后再回答，不能只凭常识或记忆下结论。
- 【先用已知信息】用户已经说过的**偏好或个人信息**（见上方记忆，例如口味、常住城市、职业）
  足够回答时，直接基于它回答，不要再调用工具。工具是给"你不知道的信息"用的，不是每轮都要调。
  例：用户说过"我喜欢喝美式"，下一句问"推荐一杯咖啡"，直接基于偏好推荐即可，不必联网。
  注意：这条只适用于偏好类信息，实时数据（天气/股价/新闻）仍然必须先取证。
- 【多任务不遗漏】用户一句话里提了多个请求（例如"先查北京天气，再查上海天气"），
  必须逐项完成、分别取证，再合并成一条回答；不允许只做其中一件就下结论。
- 【追问后必须执行】如果上一轮你向用户追问了缺少的参数，而用户这一轮把答案给了，
  必须立刻用补全后的参数调用工具，禁止再问一遍同样的问题。
  例：用户说"帮我查下天气" → 你追问"哪个城市？" → 用户回"上海" →
  你必须立刻调用 get_weather(city="上海")，而不是再问一次城市。
- 【填槽规则】调用任何工具前，先检查必需参数是否齐全。如果用户没有提供某个必需参数（例如没说查哪个城市、没说提醒什么内容或什么时间），
  禁止猜测、禁止使用默认值、禁止跳过该参数，必须先向用户追问补全，等用户回答后再调用工具。
- 【指代先查文档】用户用"这个项目""这个方案""我的文档""上面提到的"这类指代提问，
  而你不确定具体内容时，先调用 retrieve_document 检索，再根据结果回答；
  不要一上来就说"没有相关信息"或反问用户。检索不到再说明。
- 【技能规则】系统提示词末尾会列出你已经拥有的技能。当用户的任务命中某个技能的描述时，必须先调 read_skill 读出它的完整步骤，再照着执行，不要凭印象做。
- 【学技能规则】只有用户明确说"记住这套做法""以后都按这个来"时，才调用 save_skill；调用前先用一句话跟用户确认。技能名用小写连字符，description 要写清"什么时候该用"。删技能、停用技能同理：只有用户明确要求时才调 delete_skill / set_skill_enabled，动手前确认一次。

回答要简洁、自然，不要主动列举你能做什么。{doc_hint}""",
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


# 记忆抽取最多尝试次数：首次 + 一次带纠错提示的重试
MAX_EXTRACT_ATTEMPTS = 2


class UserInfo(BaseModel):
    """记忆抽取的结构化输出模型。

    用 Pydantic 而不是手写 dict 取值，好处是：字段名缺失给默认值、
    类型不对直接报 ValidationError，由上层决定重试还是降级。
    """

    name: Optional[str] = None
    facts: List[str] = []


def _extract_chunk_text(chunk) -> str:
    """从流式返回的单个 chunk 中取出文本内容。

    注意 ChatResponse 是 dict 的子类，content 字段是 content blocks 列表，
    例如 [{'type': 'text', 'text': '...'}]。
    """
    content = chunk["content"] if isinstance(chunk, dict) else None
    if isinstance(content, list):
        return "".join(
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return "" if content is None else str(content)


async def _call_model_text(model, prompt: str) -> str:
    """调用一次模型，返回完整的纯文本结果。

    ⚠️ 本项目踩过的坑：DashScopeChatModel 默认以流式（AsyncGenerator）返回，
    必须迭代消费；每个 chunk 携带的是「截止目前的累积内容」，
    因此取最后一个 chunk 的文本就是完整结果。

    早期实现直接把返回值当响应对象用（res.text / res.content），
    实际拿到的是异步生成器的字符串表示，JSON 解析必然失败，
    而异常又被 except 静默吞掉 —— 这正是长期记忆抽取长期失效的根因。
    """
    res = await model(messages=[{"role": "user", "content": prompt}])
    if isinstance(res, AsyncGenerator):
        text = ""
        async for chunk in res:
            text = _extract_chunk_text(chunk)
        return text
    return _extract_text(res)


def _parse_user_info(text: str) -> UserInfo:
    """把 LLM 返回的文本解析并校验成 UserInfo。

    解析失败时抛异常，交给调用方统一处理（重试 / 降级）。
    """
    cleaned = text.strip()
    # 模型经常自作主张包一层 markdown 代码块，先剥掉
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:-1]).strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError(f"期望 JSON 对象，实际得到 {type(data).__name__}")
    return UserInfo.model_validate(data)


async def _extract_user_info(model, user_message, reply_text, existing_facts):
    """用一次 LLM 调用，从本轮对话中结构化抽取用户信息。

    返回 (name, new_facts)：
      - name: 用户名字（str）或 None（仅当用户明确表达过名字时）
      - new_facts: 新增的事实/偏好列表（不含已存在项）

    用 LLM 结构化抽取替代脆弱的正则匹配，是"持续学习"能力的核心。
    """
    if not user_message or not reply_text:
        return None, []

    # 先做一个可靠的规则兜底：用户说"我叫杨恺"就直接命中，
    # 避免 LLM 提取不稳定导致记忆丢失。
    name_match = re.search(
        r"(?:我叫|我的名字是)\s*([\u4e00-\u9fa5]{2,20}(?:[·•][\u4e00-\u9fa5]+)?)",
        user_message,
    )
    # 过滤反问句，例如"我叫什么""我叫啥""你猜我叫什么"
    invalid_names = {"什么", "啥", "谁", "多少", "几", "吗", "呢", "吧", "嘛"}
    rule_name = None
    if name_match:
        name = name_match.group(1).strip()
        if 1 < len(name) <= 20 and name not in invalid_names:
            # ⚠️ 修复（2026-09-09）：原来这里直接 `return name, []`，
            # 导致只要用户说出名字，本轮的事实/偏好就整轮被丢弃——
            # 表现为"记不住东西"。正确做法是只把名字记为兜底值，
            # 事实抽取照常往下走。
            rule_name = name

    existing = "\n".join(f"- {f}" for f in existing_facts[-10:])

    # 结构化输出校验：LLM 返回不稳定（可能带 markdown 代码块、可能缺字段、可能类型不对），
    # 这里用 Pydantic 做严格校验；失败则带纠错提示重试一次；两次都失败就放弃本轮抽取，
    # 宁可少记一条，也不要把脏数据写进长期记忆。
    info = None
    for attempt in range(MAX_EXTRACT_ATTEMPTS):
        retry_hint = ""
        if attempt > 0:
            retry_hint = (
                "\n\n【重要】你上一次的输出无法解析为合法 JSON。"
                "这次请严格只输出 JSON 对象本身，不要任何解释文字、不要 markdown 代码块。"
            )
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

输出必须是合法 JSON 对象，不要加任何解释、不要 markdown 代码块。{retry_hint}"""

        try:
            text = await _call_model_text(model, prompt)
            info = _parse_user_info(text)
            break
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            print(f"[memory-extract] 第 {attempt + 1} 次解析失败：{e}")
            info = None

    if info is None:
        # 两次都失败：降级为空结果，不污染记忆。
        # 但正则兜底命中的名字仍然要保住，不能一起丢掉。
        print("[memory-extract] 抽取失败，本轮不写入新事实")
        return rule_name, []

    new_facts = []
    seen = set(existing_facts)
    for item in info.facts:
        if isinstance(item, str) and item.strip() and item.strip() not in seen:
            new_facts.append(item.strip())
            seen.add(item.strip())

    # 名字优先用 LLM 抽的，抽不到再退回正则兜底值
    name = (info.name or rule_name or "").strip()
    if 1 < len(name) <= 20:
        return name, new_facts
    return None, new_facts


def _stringify_tool_output(output) -> str:
    """把工具返回值统一转成字符串（可能是 str，也可能是 content blocks 列表）。"""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts = []
        for item in output:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(output)


def _format_trace(messages):
    """把 ReAct 的中间消息格式化成人能看懂的推理轨迹。

    AgentScope 会把 ReAct 的每一步都写进 agent.memory：
      - assistant 消息：thinking 块（思考）+ tool_use 块（行动）
      - system 消息：tool_result 块（观察）
    这里把它们抽出来，对应成"思考 → 行动 → 观察"三段式。

    Returns:
        (轨迹文本, 工具调用次数)
        工具调用次数用于判断本轮是否真的用了工具（决定要不要走 Critic 审核）。
    """
    lines = []
    step = 0
    tool_calls = 0
    for m in messages:
        if getattr(m, "role", None) == "user":
            continue
        blocks = getattr(m, "content", None)
        if not isinstance(blocks, list):
            continue
        for b in blocks:
            if not isinstance(b, dict):
                continue
            btype = b.get("type")
            if btype == "thinking":
                think = (b.get("thinking") or "").strip()
                if think:
                    step += 1
                    lines.append(f"**思考 {step}**\n{think}")
            elif btype == "tool_use":
                tool_calls += 1
                args = json.dumps(b.get("input") or {}, ensure_ascii=False)
                lines.append(f"**行动** 调用 `{b.get('name')}`\n入参：`{args}`")
            elif btype == "tool_result":
                out = _stringify_tool_output(b.get("output")).strip()
                if len(out) > 300:
                    out = out[:300] + "…（已截断）"
                lines.append(f"**观察**\n{out}")
    text = (
        "\n\n".join(lines)
        if lines
        else "（本轮没有调用工具，模型直接生成了回复）"
    )
    return text, tool_calls


async def _capture_trace(agent, msg):
    """从 agent.memory 中取出本轮对话产生的 ReAct 轨迹。

    Returns:
        (轨迹文本, 工具调用次数)
    """
    try:
        mem = await agent.memory.get_memory()
        # 优先按本轮用户消息的 id 定位起点；找不到就退回"取最后若干条"
        start = 0
        for i, m in enumerate(mem):
            if getattr(m, "id", None) == msg.id:
                start = i
                break
        return _format_trace(mem[start:])
    except Exception as e:
        return f"（轨迹提取失败：{e}）", 0


# 单轮最大处理时间（秒）。模型或工具卡住时不能无限等，
# 否则 Web 端一个请求就能把 worker 占死。可用环境变量调大。
TURN_TIMEOUT = float(os.getenv("KENDER_TURN_TIMEOUT", "120"))


async def _run_once(agent, model, message):
    """跑一轮 ReAct，返回 (回复文本, 轨迹文本, 工具调用次数)。

    只负责"跑"，不写长期记忆 —— 这样 Critic 打回重写时，
    中间被否决的版本不会污染记忆文件。

    加了 asyncio.wait_for：模型/工具卡住时抛 TimeoutError，
    转成一句可读的提示返回，而不是让整个请求无限挂起。
    """
    full_message = f"{get_current_date()}\n\n用户的问题：{message}"
    msg = Msg(name="user", role="user", content=full_message)
    # ⚠️ 必须用 uuid，不能用秒级时间戳：两轮对话如果在同一秒内完成
    # （模型答得快时很常见），id 会撞车，AgentScope 把第二条用户消息当重复消息，
    # 模型看到的上下文还停在自己上一句问话上，于是原样再问一遍。
    # eval 的 MT03 稳定复现过：耗时 1.3s 的失败、6s 的通过。
    msg.id = f"msg_{uuid.uuid4().hex[:12]}"
    try:
        reply = await asyncio.wait_for(agent.reply(msg), timeout=TURN_TIMEOUT)
    except asyncio.TimeoutError:
        return (
            f"⚠️ 这一轮处理超时了（超过 {TURN_TIMEOUT:.0f} 秒）。"
            "可能是网络或工具响应慢，请稍后重试，或把问题拆小一点。",
            "",
            0,
        )
    except Exception as e:
        return (
            f"⚠️ 抱歉，调用模型时出错了：{e}。请检查网络或 DASHSCOPE_API_KEY 后重试。",
            "",
            0,
        )

    reply_text = _extract_text(reply)
    trace, tool_calls = await _capture_trace(agent, msg)
    return reply_text, trace, tool_calls


async def _persist_turn(model, memory, user_message, reply_text, persist: bool = True):
    """抽取用户信息并写入长期记忆（一轮对话结束时调用一次）。

    persist=False 时直接跳过：访客会话的对话不落盘、也不做事实抽取
    （省一次模型调用），实现多用户之间的记忆隔离。
    """
    if not persist:
        return
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


async def get_reply_with_trace(agent, model, user_message, memory, persist: bool = True):
    """返回 (回复文本, ReAct 推理轨迹)。

    与 get_reply 逻辑完全一致，只是额外把 ReAct 中间过程抽出来，
    用于界面展示（让"Agent 把连续输出离散化"这件事变得可见）。
    """
    reply_text, trace, _ = await _run_once(agent, model, user_message)
    await _persist_turn(model, memory, user_message, reply_text, persist=persist)
    return reply_text, trace


# ===================== 检查点 Critic：评审式多 Agent 协作 =====================
# 视频里的原话："用 AI 查 AI"。这也是最小可用的多 Agent 系统：
#   一个 Agent 负责生成（Generator），另一个负责审核（Critic）。
# 单靠 prompt 约束不住模型，就再加一道"后置检查点"来兜底。

CRITIC_PROMPT_TEMPLATE = """你是一个严格的质量审核员，负责判断 AI 助手的回答是否合格。

【判为不合格的情况】
1. 答非所问：没有直接回应用户的问题，顾左右而言他
2. 编造：调用了工具，但回答里的信息并非来自工具返回的结果
3. 自相矛盾，或明显的事实错误

【判为合格的情况】
- 助手正在向用户追问必要信息（例如问城市、问时间）——这是合理的填槽行为，必须判合格
- 正常的闲聊、解释、总结，以及如实说明"没查到"

只输出一个 JSON 对象，不要任何解释文字、不要 markdown 代码块：
{{"passed": true 或 false, "reason": "一句话说明原因，20 字以内"}}

用户的问题：{user_message}
{tool_context}
助手的回答：{reply_text}

请输出审核结果 JSON："""


class CriticVerdict(BaseModel):
    """Critic 的审核结论（Pydantic 强制结构化，防止模型絮絮叨叨白白多烧 token）。"""

    passed: bool = True
    reason: str = ""


def _parse_verdict(text: str) -> CriticVerdict:
    """解析 Critic 的 JSON 输出，失败抛异常由调用方兜底。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:-1]).strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError(f"期望 JSON 对象，实际得到 {type(data).__name__}")
    return CriticVerdict.model_validate(data)


async def critique_reply(model, user_message, reply_text, trace="") -> CriticVerdict:
    """用第二个模型（Critic）审核第一个模型（Generator）的回答。

    关键点：把工具实际返回的内容（轨迹）也一并喂给 Critic。
    只看最终回答的话，Critic 无从判断"有没有编造"；
    有了 Observation 做对照，它才能识破答非所问和数据捏造。

    审核异常时默认放行 —— 检查点是"兜底"而不是"拦路虎"，
    不能因为审核本身出错就让整个对话失败。
    """
    tool_context = (
        f"本轮工具实际返回的信息（用于核对回答有没有编造）：\n{trace}\n"
        if trace
        else ""
    )
    prompt = CRITIC_PROMPT_TEMPLATE.format(
        user_message=user_message, tool_context=tool_context, reply_text=reply_text
    )
    try:
        text = await _call_model_text(model, prompt)
        return _parse_verdict(text)
    except Exception as e:
        print(f"[critic] 审核异常，默认放行：{e}")
        return CriticVerdict(passed=True, reason="审核异常，默认放行")


async def _collect_tool_outputs(agent, limit_chars: int = 600) -> str:
    """把本轮工具实际返回的内容拼成一段文本。

    为什么需要：Critic 打回重写时，第二次生成往往不再调用工具（凭 ReAct 记忆重写）。
    模型这时看不到原始数据，只有两个选择——凭印象编，或者把工具输出原样复读。
    eval 里的 W05 就是这样退化成 "深圳: 🌦️ +28°C" 的。
    把 Observation 显式塞回重写提示词，重写才有依据。
    """
    try:
        mem = await agent.memory.get_memory()
    except Exception:  # noqa: BLE001
        return ""
    parts = []
    for m in mem:
        content = getattr(m, "content", None)
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                text = _stringify_tool_output(b.get("output")).strip()
                if text:
                    if len(text) > limit_chars:
                        text = text[:limit_chars] + "…（已截断）"
                    parts.append(text)
    return "\n---\n".join(parts[-3:])


def _looks_like_echo(reply: str, tool_text: str) -> bool:
    """判断回答是不是把工具原始输出原样复读了一遍。

    工业上这叫"没有完成转述"：工具给的是结构化数据，用户要的是人话。
    直接复读既没用，也说明模型没理解数据。
    """
    if not reply.strip():
        return True
    if not tool_text:
        return False
    norm = lambda s: re.sub(r"\s+", "", s)  # noqa: E731
    r, t = norm(reply), norm(tool_text)
    return len(r) <= 40 and r in t


# 实时数据的强特征词：只有这些词 + 数字同时出现，才认为模型在做"具体断言"
_REALTIME_MARKERS = ("℃", "°C", "气温", "温度", "股价", "指数", "汇率")
_DIGIT_RE = re.compile(r"\d")


def _looks_like_realtime_claim(reply: str) -> bool:
    """回答里是否出现了"实时数据型"的具体断言。

    用来抓一类最危险的编造：用户问天气/股价，模型既不调工具，又直接给出
    具体数值——甚至照抄工具返回的格式（`上海: 🌦️ 18°C`）。
    这种回答表面最像真的，实际是凭空捏的，比明显的胡话危害更大。

    只做粗筛：要求"数字 + 强特征词"同时出现，避免把闲聊误判成断言。
    """
    if not reply:
        return False
    return bool(_DIGIT_RE.search(reply)) and any(m in reply for m in _REALTIME_MARKERS)


# 用户的"实时类问题"特征。必须是问题本身在问实时信息，才值得触发取证检查。
# 只看回答会把"举例说明"误判成编造（比如回答里写"比如上海 18°C"）。
_REALTIME_QUESTION_MARKERS = (
    "天气", "气温", "温度", "几度", "多少度",
    "股价", "股票", "指数", "汇率", "大盘",
    "新闻", "热搜", "比分", "航班",
)


def _is_realtime_question(text: str) -> bool:
    """用户这句话是否在问实时/易变信息。"""
    if not text:
        return False
    return any(k in text for k in _REALTIME_QUESTION_MARKERS)


async def _anchor_short_followup(agent, message: str) -> str:
    """用户只回一个短词（如"上海"）时，把上下文显式写进提示词。

    为什么需要：多轮填槽时，用户上一轮被追问"哪个城市？"，这轮只回"上海"。
    实测 qwen-plus 有约一半概率把"上海"当成新问题、又把同一个问题问一遍
    （eval 的 MT03 稳定复现）。单靠系统提示里的规则约束不住，
    于是把「上一轮在追问、这轮是答案」这个事实直接写进本轮输入。
    """
    msg = (message or "").strip()
    if not msg or len(msg) > 12 or any(p in msg for p in "。！？?!"):
        return message
    try:
        mem = await agent.memory.get_memory()
    except Exception:  # noqa: BLE001
        return message

    last_assistant = ""
    for m in reversed(mem):
        if getattr(m, "role", None) != "assistant":
            continue
        blocks = getattr(m, "content", None)
        if isinstance(blocks, list):
            last_assistant = "".join(
                str(b.get("text", ""))
                for b in blocks
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
        elif isinstance(blocks, str):
            last_assistant = blocks.strip()
        break

    if not last_assistant.endswith(("？", "?")):
        return message
    print(f"[anchor] 命中追问锚定：{msg!r}（上一轮问句：{last_assistant[:30]!r}）")
    return (
        f"（上一轮你在向用户追问必要参数，用户这轮的回答是：{msg}。"
        f"请据此补全参数并直接调用工具，不要再重复提问。）\n{msg}"
    )


async def get_reply_with_review(
    agent, model, user_message, memory, max_retries: int = 2, persist: bool = True
):
    """生成 → 审核 → 不合格打回重写（评审式多 Agent 协作）。

    流程：
        第 1 次生成 → Critic 审核
            ├ 合格  → 返回
            └ 不合格 → 把批评意见 + 工具原始结果回灌给 Generator 重写（最多 max_retries 次）

    优化：本轮没有调用工具时直接跳过审核。
    闲聊和"追问用户"没有审核价值，省下一整轮 token。

    persist=False 时不做长期记忆抽取/落盘（Web 访客会话的隔离开关）。

    Returns:
        (回复文本, 轨迹文本, 审核结论, 实际生成轮数)
    """
    message = await _anchor_short_followup(agent, user_message)
    rounds = 0
    # 打回重写时，后续轮次可能不再调工具（凭 ReAct 记忆直接重写），
    # 那样轨迹会变成"本轮没有调用工具"。这里保留最后一个真正用过工具的轨迹。
    last_trace_with_tools = ""
    last_tool_outputs = ""

    for attempt in range(max_retries + 1):
        rounds = attempt + 1
        reply_text, trace, tool_calls = await _run_once(agent, model, message)
        if tool_calls > 0:
            last_trace_with_tools = trace
            last_tool_outputs = await _collect_tool_outputs(agent)

        echoed = _looks_like_echo(reply_text, last_tool_outputs)

        # 【无工具却给出实时数据】——最隐蔽的一类编造。
        # 模型有时不调工具，直接照抄 get_weather 的返回格式编一条（如"上海: 🌦️ 18°C"）。
        # 这种情况原来会走进下面的"没调工具→跳过审核"分支，假数据直接放行。
        # 这里改成强制重写：明确要求先取证再回答。
        if (
            tool_calls == 0
            and _is_realtime_question(user_message)
            and _looks_like_realtime_claim(reply_text)
        ):
            if attempt < max_retries:
                message = (
                    f"{user_message}\n\n"
                    "[系统检查] 你刚才没有调用任何工具，却给出了具体数值。"
                    "这类实时信息必须调用工具获取，禁止凭记忆或推测作答，"
                    "也不允许照抄工具的返回格式自行拼接数据。"
                    "请重新回答：先调用对应工具，再基于工具返回的结果作答；"
                    "如果工具不可用，就如实说明查不到。"
                )
                print(f"[guard] 第 {rounds} 轮：无工具却含实时数据，强制重写")
                continue
            # 已经用完重试次数，仍然是无依据的数据 → 判定不合格，交上层处理
            return (
                reply_text,
                last_trace_with_tools or trace,
                CriticVerdict(passed=False, reason="未调用工具却给出具体实时数据，属编造"),
                rounds,
            )

        if tool_calls == 0 and not echoed:
            # 没调工具 = 闲聊或正在追问用户，没必要审核
            # ⚠️ 修复（2026-09-09）：原来这里直接 return，跳过了 _persist_turn，
            # 于是"我叫XX""我要去出差""我不吃香菜"这类不触发工具的陈述
            # 一条都进不了长期记忆 —— 而这恰恰是记忆最主要的来源。
            # 审核可以跳过，记忆不能跳过。
            await _persist_turn(
                model, memory, user_message, reply_text, persist=persist
            )
            return (
                reply_text,
                last_trace_with_tools or trace,
                CriticVerdict(passed=True, reason="本轮未调用工具，跳过审核"),
                rounds,
            )

        if echoed:
            # 复读原始数据同样算不合格，不必再花一次 Critic 调用
            verdict = CriticVerdict(
                passed=False, reason="回答只是复述了工具原始数据，没有转成自然语言"
            )
        else:
            verdict = await critique_reply(model, user_message, reply_text, trace)
        print(f"[critic] 第 {rounds} 轮：passed={verdict.passed} | {verdict.reason}")

        if verdict.passed or attempt == max_retries:
            # 记忆只在最终版本落盘一次，避免被否决的中间版本污染
            await _persist_turn(
                model, memory, user_message, reply_text, persist=persist
            )
            return reply_text, last_trace_with_tools or trace, verdict, rounds

        # 打回重写：批评意见 + 工具原始结果一起回灌。
        # 只给批评意见的话，模型看不到数据，只能编或者复读。
        message = f"{user_message}\n\n[上一版回答未通过审核] {verdict.reason}\n"
        if last_tool_outputs:
            message += f"\n【本轮工具实际返回的内容，只能依据它回答】\n{last_tool_outputs}\n"
        message += (
            "\n请重新回答用户的问题：用自然语言直接回答，"
            "不要复述原始数据，不要补充工具里没有的信息。"
        )

    # 理论上到不了这里（循环内必返回），留个兜底防止重构时出纰漏
    await _persist_turn(model, memory, user_message, reply_text, persist=persist)
    return reply_text, last_trace_with_tools or trace, CriticVerdict(passed=True, reason=""), rounds


async def get_reply(agent, model, user_message, memory):
    """保留原有签名与返回值（str），内部复用带轨迹的版本，保证老调用方零回归。"""
    reply_text, _ = await get_reply_with_trace(agent, model, user_message, memory)
    return reply_text
