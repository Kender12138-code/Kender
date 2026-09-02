r"""
农产品电商智能建站 Agent —— ReActAgent 进阶版。

与 farm_shop_app.py 的区别：
- 这里复用 Kender 的 ReActAgent，LLM 自主决定调用 build_farm_shop / update_farm_shop
- 工具调用轨迹会显示在"推理轨迹"面板，面试可直接展示"思考 → 行动 → 观察"
- 不改动 Kender 任何原有文件

运行方式（必须在项目根目录）：
    cd D:\kender_projects\kender_extracted\kender
    python farm_react_app.py
"""

import os
import asyncio

import gradio as gr
from dotenv import load_dotenv
from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit, ToolResponse
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg

load_dotenv()

from src.farm_shop import (
    extract_shop_data_sync,
    update_shop_data_sync,
    render_html,
    render_html_preview,
    SHOP_CART_SCRIPT,
    generate_reply,
    DEFAULT_SHOP_DATA,
)
from src.agent import get_reply_with_trace
from src.memory import load_memory
from src.tools import get_current_date


HEADER_HTML = """
<div style="padding: 16px 20px; border-bottom: 1px solid #e5e7eb; background: #fff;">
  <div style="font-size: 20px; font-weight: 700; color: #2e7d32;">🌾 农家小铺 AI 建站（ReAct 版）</div>
  <div style="font-size: 13px; color: #666; margin-top: 4px;">LLM 自主决定建店 / 改店，轨迹可见</div>
</div>
"""

# 单用户 demo 用全局状态保存当前店铺；多会话场景可改为按 session_id 隔离
_current_shop = DEFAULT_SHOP_DATA.copy()
_PREVIEW_FILE = "data/shop_react_preview.html"


def _save_preview(html: str):
    os.makedirs("data", exist_ok=True)
    with open(_PREVIEW_FILE, "w", encoding="utf-8") as f:
        f.write(html)


def _shop_summary(shop_data: dict) -> str:
    products = shop_data.get("products", [])
    if not products:
        return "当前店铺暂无产品"
    items = "、".join(f"{p.get('name')} ¥{p.get('price')}/{p.get('unit')}" for p in products)
    return f"店铺「{shop_data.get('shop_name', '未命名')}」当前展示：{items}"


def build_farm_shop(user_request: str) -> ToolResponse:
    """【Agent 工具】当农民想要新建店铺或首次描述需求时调用。

    Args:
        user_request: 农民的完整原始需求描述。

    Returns:
        ToolResponse: 建店结果摘要。
    """
    global _current_shop
    _current_shop = extract_shop_data_sync(user_request)
    html = render_html(_current_shop)
    _save_preview(html)
    return ToolResponse(content=[{"type": "text", "text": _shop_summary(_current_shop)}])


def update_farm_shop(user_request: str) -> ToolResponse:
    """【Agent 工具】当农民要求调整已有店铺时调用（改价、加产品、换风格等）。

    Args:
        user_request: 农民的修改要求。

    Returns:
        ToolResponse: 更新结果摘要。
    """
    global _current_shop
    _current_shop = update_shop_data_sync(_current_shop, user_request)
    html = render_html(_current_shop)
    _save_preview(html)
    return ToolResponse(content=[{"type": "text", "text": _shop_summary(_current_shop)}])


def create_farm_react_agent(memory):
    """创建面向农产品电商的 ReActAgent，注册建店/改店工具。"""
    from src.memory import build_memory_prompt

    prompt = build_memory_prompt(memory)
    toolkit = Toolkit()
    toolkit.register_tool_function(build_farm_shop)
    toolkit.register_tool_function(update_farm_shop)

    model = DashScopeChatModel(
        model_name="qwen-plus",
        api_key=os.getenv("DASHSCOPE_API_KEY"),
    )

    agent = ReActAgent(
        name="FarmShopAgent",
        sys_prompt=f"""你是一个农产品电商智能建站助手，名字叫农家小铺 AI。
{prompt}

当前真实日期：{get_current_date()}。

你的任务：通过对话帮农民生成和调整在线店铺页面。农民不懂技术，只会用自然语言描述，比如"我家有50斤西红柿，3块钱一斤，想在网上卖"。

你拥有两个工具：
1. build_farm_shop：当用户想要【新建店铺】或【第一次描述要卖什么】时调用。参数 user_request 必须是用户的完整原始需求，不要遗漏。
2. update_farm_shop：当用户要求【修改已有店铺】时调用，例如：
   - "把西红柿改成2块5"
   - "再加一箱土鸡蛋，60元"
   - "换个清新点的风格"
   - "店名改成李叔菜园"

工具调用规则：
- 先调用工具获取结果，再用简洁自然的语言告诉用户页面已生成/更新。
- 如果用户的话既不像建店也不像改店（只是闲聊），直接回答即可，不要调用工具。
- 不要编造用户没有提供的价格、库存等信息。
- 调用工具时，user_request 参数必须包含用户的完整原始表达。

回答要简洁、口语化，像面对农民朋友一样。""",
        model=model,
        toolkit=toolkit,
        formatter=OpenAIChatFormatter(),
    )
    return agent, model


FARM_CSS = """
.gradio-container { max-width: 1400px !important; margin: 0 auto; }
.farm-left { border-right: 1px solid #e5e7eb; padding-right: 12px; }
.farm-right { padding-left: 12px; }
.preview-box { border: 1px solid #e5e7eb; border-radius: 12px; min-height: 620px; }
"""


async def respond(message, history, session, trace_md):
    """处理每一轮输入，返回聊天更新 + 右侧预览 + ReAct 轨迹。"""
    if not message or not message.strip():
        yield "", history, history, session, "", render_html_preview(_current_shop)
        return

    user_msg = message.strip()

    # 会话兜底
    if not session:
        memory = {"user_name": None, "key_facts": [], "chat_history": []}
        agent, model = create_farm_react_agent(memory)
        session = {"agent": agent, "model": model, "memory": memory}

    agent, model = session["agent"], session["model"]
    memory = session["memory"]

    # 工具调用前的当前页面（预生成一次，避免打字机循环里反复重建 HTML）
    preview_current = render_html_preview(_current_shop)

    # 先展示思考占位
    yield (
        "",
        history + [{"role": "user", "content": user_msg}, {"role": "assistant", "content": "⏳ Agent 正在思考…"}],
        history,
        session,
        "正在运行 ReAct 循环…",
        preview_current,
    )

    # 调用 Kender 的 get_reply_with_trace，persist=False 避免污染用户长期记忆
    try:
        reply_text, trace = await get_reply_with_trace(agent, model, user_msg, memory, persist=False)
    except Exception as e:
        err_history = history + [{"role": "user", "content": user_msg}, {"role": "assistant", "content": f"⚠️ 出错了：{e}"}]
        yield "", err_history, err_history, session, f"错误：{e}", preview_current
        return

    # 工具执行后若店铺被更新，重新生成预览页面
    preview_updated = render_html_preview(_current_shop)

    # 打字机效果
    base = history + [{"role": "user", "content": user_msg}]
    step = 3
    for i in range(step, len(reply_text) + step, step):
        shown = reply_text[:i]
        current = base + [{"role": "assistant", "content": shown}]
        yield "", current, current, session, trace, preview_updated
        await asyncio.sleep(0.018)

    final = base + [{"role": "assistant", "content": reply_text}]
    yield "", final, final, session, trace, preview_updated


def create_ui():
    """创建左右分栏的 Gradio 界面。"""
    with gr.Blocks(title="农家小铺 AI 建站 · ReAct 版") as demo:
        gr.HTML(HEADER_HTML)

        with gr.Row(equal_height=True):
            with gr.Column(scale=1, elem_classes="farm-left"):
                chatbot = gr.Chatbot(
                    label="",
                    height=480,
                    value=[{"role": "assistant", "content": "你好！我是农家小铺 AI。告诉我你要卖什么，比如\"我家有50斤西红柿，3块钱一斤，想在网上卖\"。"}],
                )
                with gr.Row():
                    msg_input = gr.Textbox(
                        label="",
                        placeholder="输入需求，按 Enter 发送…",
                        lines=2,
                        scale=9,
                        container=False,
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)

                with gr.Accordion("🔍 ReAct 推理轨迹（思考 → 行动 → 观察）", open=True):
                    trace_md = gr.Markdown("*发送消息后，这里会显示 Agent 的完整推理过程*")

            with gr.Column(scale=1, elem_classes="farm-right"):
                gr.Markdown("### 🏪 实时店铺预览")
                preview = gr.HTML(
                    value=render_html_preview(_current_shop),
                    elem_classes="preview-box",
                )
                gr.HTML(
                    '<div style="text-align:center;margin-top:10px;">'
                    '<a href="/gradio_api/file=data/shop_react_preview.html" target="_blank" '
                    'style="color:#2e7d32;font-size:14px;text-decoration:none;padding:8px 14px;border:1px solid #2e7d32;border-radius:8px;display:inline-block;">'
                    '🔍 在新窗口打开完整交互版（含购物车/支付）'
                    '</a></div>'
                )

        session_state = gr.State(None)
        chat_history_state = gr.State([])

        inputs = [msg_input, chat_history_state, session_state, trace_md]
        outputs = [msg_input, chatbot, chat_history_state, session_state, trace_md, preview]

        send_btn.click(respond, inputs, outputs)
        msg_input.submit(respond, inputs, outputs)

    return demo


if __name__ == "__main__":
    if not os.getenv("DASHSCOPE_API_KEY"):
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，请检查 .env 文件")

    server_name = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7862"))
    # 预览走内联样式 HTML + head 注入购物车脚本，同时允许 /file= 访问完整版页面
    create_ui().launch(
        server_name=server_name,
        server_port=server_port,
        share=False,
        css=FARM_CSS,
        head="<script type=\"text/javascript\">\n" + SHOP_CART_SCRIPT + "\n</script>",
        allowed_paths=[os.path.abspath("data")],
    )
