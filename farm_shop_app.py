r"""
农产品电商智能建站 Agent —— 基于 Kender 的新入口。

运行方式（必须在项目根目录执行，否则相对路径会错）：
    cd D:\kender_projects\kender_extracted\kender
    python farm_shop_app.py

核心交互：
- 左侧：农民用自然语言聊天，告诉 AI 要卖什么、怎么卖、多少钱
- 右侧：AI 实时生成/调整店铺页面（产品展示、购物车、模拟微信支付）
- 多轮对话可持续修改：换风格、改价格、加产品、改店名……

设计原则：
- 不改动 Kender 原有文件，新增 src/farm_shop.py + farm_shop_app.py
- 复用 Kender 的 DashScope API Key 配置（.env）
- 本地 demo，微信支付为模拟二维码，真实收款需接入商户号
"""

import os
import asyncio

import gradio as gr
from dotenv import load_dotenv

load_dotenv()

from src.farm_shop import (
    extract_shop_data,
    update_shop_data,
    render_html,
    render_html_preview,
    SHOP_CART_SCRIPT,
    generate_reply,
)


_PREVIEW_FILE = "data/shop_preview.html"


def _save_preview(html: str):
    os.makedirs("data", exist_ok=True)
    with open(_PREVIEW_FILE, "w", encoding="utf-8") as f:
        f.write(html)


HEADER_HTML = """
<div style="padding: 16px 20px; border-bottom: 1px solid #e5e7eb; background: #fff;">
  <div style="font-size: 20px; font-weight: 700; color: #2e7d32;">🌾 农家小铺 AI 建站</div>
  <div style="font-size: 13px; color: #666; margin-top: 4px;">说说话，店铺页面就出来</div>
</div>
"""


def _check_env():
    """启动前检查 API Key，避免跑到一半报错。"""
    if not os.getenv("DASHSCOPE_API_KEY"):
        raise RuntimeError(
            "缺少 DASHSCOPE_API_KEY。请把 .env.example 复制为 .env 并填入你的 DashScope API Key。"
        )


async def respond(message, history, shop_data, thinking_md):
    """处理每一轮农民输入，返回聊天更新 + 右侧页面更新。"""
    if not message or not message.strip():
        yield "", history, history, shop_data, "", thinking_md
        return

    user_msg = message.strip()
    is_new = not shop_data or not shop_data.get("products")

    # 1) 先展示"正在理解"
    yield (
        "",
        history + [{"role": "user", "content": user_msg}, {"role": "assistant", "content": "⏳ 我在听，正在帮你整理店铺……"}],
        history,
        shop_data,
        "",
        "🤖 正在解析农民需求 → 提取店铺信息 → 渲染页面",
    )
    await asyncio.sleep(0.2)

    # 2) 提取或更新店铺数据
    try:
        if is_new:
            shop_data = await extract_shop_data(user_msg)
            thinking = f"📝 从对话中提取到店铺：{shop_data.get('shop_name', '未命名')}，产品数：{len(shop_data.get('products', []))}"
        else:
            shop_data = await update_shop_data(shop_data, user_msg)
            thinking = f'🔄 根据"{user_msg[:20]}..."更新了店铺数据'
    except Exception as e:
        reply = f"⚠️ 处理出错了：{e}。请检查网络或 API Key。"
        yield "", history + [{"role": "user", "content": user_msg}, {"role": "assistant", "content": reply}], history, shop_data, "", thinking_md
        return

    # 3) 渲染页面 + 生成回复（右侧预览用内联样式，完整交互版保存到文件）
    html = render_html_preview(shop_data)
    full_html = render_html(shop_data)
    _save_preview(full_html)
    reply = generate_reply(shop_data, is_new)

    final_history = history + [
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": reply},
    ]

    # 4) 逐字显示回复（和 Kender 一致的打字机效果）
    base = history + [{"role": "user", "content": user_msg}]
    step = 3
    for i in range(step, len(reply) + step, step):
        shown = reply[:i]
        current = base + [{"role": "assistant", "content": shown}]
        yield "", current, current, shop_data, html, thinking
        await asyncio.sleep(0.018)

    # 最终完整输出
    yield "", final_history, final_history, shop_data, html, thinking


FARM_CSS = """
.gradio-container { max-width: 1400px !important; margin: 0 auto; }
.farm-left { border-right: 1px solid #e5e7eb; padding-right: 12px; }
.farm-right { padding-left: 12px; }
.preview-box { border: 1px solid #e5e7eb; border-radius: 12px; min-height: 620px; }
"""


def create_farm_ui():
    """创建左右分栏的 Gradio 界面。"""
    with gr.Blocks(title="农家小铺 AI 建站") as demo:
        gr.HTML(HEADER_HTML)

        with gr.Row(equal_height=True):
            # ========== 左侧：聊天 ==========
            with gr.Column(scale=1, elem_classes="farm-left"):
                chatbot = gr.Chatbot(
                    label="",
                    height=520,
                    value=[{"role": "assistant", "content": "你好！我是农家小铺 AI 助手。告诉我你要卖什么，比如：\"我家有50斤西红柿，3块钱一斤，想在网上卖\"。"}],
                )
                with gr.Row():
                    msg_input = gr.Textbox(
                        label="",
                        placeholder="输入你的需求，按 Enter 发送…",
                        lines=2,
                        scale=9,
                        container=False,
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)

                with gr.Accordion("🔍 AI 处理过程", open=False):
                    thinking_md = gr.Markdown("*发送消息后，这里会显示 AI 如何从需求生成页面*")

            # ========== 右侧：实时页面预览 ==========
            with gr.Column(scale=1, elem_classes="farm-right"):
                gr.Markdown("### 🏪 实时店铺预览")
                preview = gr.HTML(
                    value=render_html_preview({"shop_name": "农家小店", "slogan": "农家自产 · 绿色新鲜 · 产地直发", "style": "朴实", "products": []}),
                    elem_classes="preview-box",
                )
                gr.HTML(
                    '<div style="text-align:center;margin-top:10px;">'
                    '<a href="/gradio_api/file=data/shop_preview.html" target="_blank" '
                    'style="color:#2e7d32;font-size:14px;text-decoration:none;padding:8px 14px;border:1px solid #2e7d32;border-radius:8px;display:inline-block;">'
                    '🔍 在新窗口打开完整交互版（含购物车/支付）'
                    '</a></div>'
                )

        # 状态：当前店铺数据 + 聊天历史
        shop_data_state = gr.State({})
        chat_history_state = gr.State([])

        # 发送按钮 & 回车
        inputs = [msg_input, chat_history_state, shop_data_state, thinking_md]
        outputs = [msg_input, chatbot, chat_history_state, shop_data_state, preview, thinking_md]

        send_btn.click(respond, inputs, outputs)
        msg_input.submit(respond, inputs, outputs)

    return demo


if __name__ == "__main__":
    _check_env()
    server_name = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7861"))  # 避免和 Kender 默认 7860 冲突
    # 预览走内联样式 HTML + head 注入购物车脚本，同时允许 /file= 访问完整版页面
    create_farm_ui().launch(
        server_name=server_name,
        server_port=server_port,
        share=False,
        css=FARM_CSS,
        head="<script type=\"text/javascript\">\n" + SHOP_CART_SCRIPT + "\n</script>",
        allowed_paths=[os.path.abspath("data")],
    )
