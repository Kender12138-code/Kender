import asyncio
import os

import gradio as gr

from .memory import load_memory
from .agent import attach_mcp_tools, create_agent, get_reply_with_review
from .tools import read_document

# 注意：read_document 不注册为 Agent 工具，而是由 UI 在用户上传文件时预处理，
# 把文档内容直接注入到本轮消息里。这是因为模型无法感知本地文件路径，
# 文件读取更适合放在应用层完成。

# ===================== 品牌头部 =====================
HEADER_HTML = """
<div class="kender-header">
  <div class="kender-logo">🔧 Kender</div>
  <div class="kender-tagline">你的专属 AI 助手 · 联网搜索 · 文档解析 · 长期记忆</div>
</div>
"""

FOOTER_HTML = """
<div class="kender-footer">
  Kender · 基于 AgentScope + Gradio 构建 · 对话内容仅保存在本地
</div>
"""

# ===================== 自定义样式与主题（豆包方向：极简、干净、扁平） =====================
# 注意：Gradio 6 要求 theme / css 在 launch() 中传入，而非 Blocks() 构造器。
KENDER_CSS = """
/* 豆包风格核心：纯白底、少阴影、轻圆角、纯色按钮 */
.gradio-container {
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', sans-serif !important;
  background: #ffffff !important;
  max-width: 1200px !important;
  margin: 0 auto !important;
  padding-top: 12px !important;
}

/* 品牌头部：极简白底 + 细灰线，更像豆包顶部导航 */
.kender-header {
  background: #ffffff;
  border-bottom: 1px solid #e5e7eb;
  border-radius: 0;
  padding: 16px 24px;
  color: #111827;
  margin-bottom: 12px;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.kender-logo { font-size: 20px; font-weight: 700; letter-spacing: -0.2px; color: #4f46e5; }
.kender-tagline { font-size: 13px; color: #6b7280; }

/* 页脚 */
.kender-footer {
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
  margin-top: 24px;
  padding-bottom: 16px;
}

/* 侧边栏：浅灰分隔，无阴影 */
.kender-sidebar {
  background: #f9fafb !important;
  border-radius: 0 !important;
  padding: 16px 14px !important;
  border-right: 1px solid #e5e7eb !important;
  box-shadow: none !important;
}

/* 主内容区 */
.kender-main { padding: 0 8px !important; }

/* 聊天气泡容器 */
.kender-chat {
  border-radius: 20px !important;
  border: 1px solid #e5e7eb !important;
  box-shadow: none !important;
  background: #ffffff !important;
}
.kender-chat .message-wrap { padding: 10px 16px !important; }
.kender-chat .message-wrap.user > .message {
  background: #4f46e5 !important;
  color: #ffffff !important;
  border-radius: 18px 18px 4px 18px !important;
  box-shadow: none !important;
}
.kender-chat .message-wrap.bot > .message {
  background: #f3f4f6 !important;
  color: #111827 !important;
  border-radius: 18px 18px 18px 4px !important;
  box-shadow: none !important;
}

/* 发送按钮：纯色、更柔和 */
.kender-send {
  background: #4f46e5 !important;
  color: #fff !important;
  font-weight: 600 !important;
  border: none !important;
  border-radius: 12px !important;
  box-shadow: none !important;
  transition: background 0.15s ease, transform 0.05s ease;
}
.kender-send:hover { background: #4338ca !important; }
.kender-send:active { transform: scale(0.98); }

/* 输入框：浅灰底、大圆角 */
.kender-input textarea {
  border-radius: 18px !important;
  border: 1px solid #e5e7eb !important;
  background: #f9fafb !important;
  font-size: 15px !important;
  padding: 12px 16px !important;
}
.kender-input textarea:focus {
  border-color: #4f46e5 !important;
  background: #ffffff !important;
  box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.1) !important;
}

/* 文件框 */
.kender-file {
  border-radius: 14px !important;
  border: 1px dashed #d1d5db !important;
  background: #f9fafb !important;
}

/* 推理轨迹面板：更克制 */
.kender-trace { border-color: #e5e7eb !important; }
"""


# Gradio 6 主题：靛蓝主色 + 青色辅色
KENDER_THEME = gr.themes.Default(
    primary_hue=gr.themes.colors.indigo,
    secondary_hue=gr.themes.colors.cyan,
    neutral_hue=gr.themes.colors.slate,
)


# 前端注入 JS：交换输入框快捷键（Enter 发送 / Shift+Enter 换行）
# 原因：Gradio 多行 Textbox 默认「Shift+Enter 提交、Enter 换行」，与提示文字相反。
# 通过 document 捕获阶段拦截 keydown，修正为「Enter 发送、Shift+Enter 换行」。
# 注：Gradio 的 gr.HTML 会过滤内联 <script>；demo.load(js=...) 会被前端包成 AsyncFunction，
#     在不同 Gradio 版本/环境下容易报语法错。这里改用 launch(head=...) 直接注入 <script> 标签。
KENDER_JS = """
(function () {
  function getScope() {
    var app = document.querySelector('gradio-app');
    return (app && app.shadowRoot) ? app.shadowRoot : document;
  }
  // 穿透 Shadow DOM 收集所有匹配元素（Gradio 6 组件常渲染进 shadow root）
  function deepQueryAll(root, selector) {
    var out = [];
    if (!root || !root.querySelectorAll) return out;
    var list = root.querySelectorAll(selector);
    for (var i = 0; i < list.length; i++) out.push(list[i]);
    var all = root.querySelectorAll('*');
    for (var j = 0; j < all.length; j++) {
      if (all[j].shadowRoot) {
        out = out.concat(deepQueryAll(all[j].shadowRoot, selector));
      }
    }
    return out;
  }
  function findSendBtn() {
    var scope = getScope();
    // 1) 优先按 id 直接找（light DOM 场景）
    var box = scope.getElementById('kender-send-btn');
    if (box) {
      var b = box.querySelector('button');
      if (b) return b;
      if (box.tagName === 'BUTTON') return box;
    }
    // 2) 穿透 shadow DOM：按 id 找容器再取内部 button（Lit 把真实 button 渲染进宿主的 shadowRoot）
    var boxes = deepQueryAll(scope, '[id="kender-send-btn"]');
    for (var i = 0; i < boxes.length; i++) {
      var inner = boxes[i].shadowRoot ? boxes[i].shadowRoot.querySelector('button') : null;
      if (inner) return inner;
      var bb = boxes[i].querySelector('button');
      if (bb) return bb;
      if (boxes[i].tagName === 'BUTTON') return boxes[i];
    }
    // 3) 兜底：按按钮文字「发送」匹配
    var btns = deepQueryAll(scope, 'button');
    for (var k = 0; k < btns.length; k++) {
      if (btns[k].textContent && btns[k].textContent.indexOf('发送') !== -1) {
        return btns[k];
      }
    }
    return null;
  }
  function insertNewline(ta) {
    var s = ta.selectionStart || 0, e = ta.selectionEnd || 0;
    var v = ta.value || '';
    ta.value = v.slice(0, s) + '\\n' + v.slice(e);
    ta.selectionStart = ta.selectionEnd = s + 1;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  }
  function triggerSend() {
    var btn = findSendBtn();
    if (!btn) return false;
    btn.focus();
    // 触发真实点击：原生 click 会派发事件并命中 Gradio 的监听器
    btn.click();
    return true;
  }
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Enter' || ev.isComposing) return;
    if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
    // 仅拦截来自本输入框 textarea 的按键
    var ta = ev.target;
    if (!ta || ta.tagName !== 'TEXTAREA') return;
    var scope = getScope();
    var box = scope.getElementById('kender-msg-input');
    if (box && !box.contains(ta)) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    if (ev.shiftKey) {
      insertNewline(ta);
    } else {
      triggerSend();
    }
  }, true);
})();
"""

# 通过 launch(head=...) 注入的完整 <script> 标签。
# 放在 <head> 中直接执行，不走 Gradio 的 AsyncFunction 包装。
KENDER_HEAD = f"""<script type="text/javascript">
{KENDER_JS}
</script>"""


def resolve_auth():
    """解析 Gradio 访问口令（公网部署前必须配）。

    为什么需要：
        页面一旦暴露在公网，任何人打开都能驱动你的 Agent，
        消耗的是你自己的 DASHSCOPE_API_KEY。加口令是最基本的防护。

    用法：
        设置环境变量 KENDER_AUTH_USER / KENDER_AUTH_PASS 后生效；
        两个都没设置时返回 None（本地开发免密，不影响日常使用）。

    Returns:
        (用户名, 口令) 元组，或 None。
    """
    user = os.getenv("KENDER_AUTH_USER")
    password = os.getenv("KENDER_AUTH_PASS")
    if user and password:
        return (user, password)
    return None


def create_ui():
    memory = load_memory()
    agent, model = create_agent(memory)

    with gr.Blocks(
        title="Kender · 你的专属 AI 助手",
    ) as demo:
        # 注：theme=KENDER_THEME 与 css=KENDER_CSS 在 launch() 中传入（Gradio 6 要求）
        gr.HTML(HEADER_HTML)

        # 跨组件状态：chat_history 是消息源，chatbot 仅负责展示
        chat_history = gr.State([])

        with gr.Row(equal_height=False):
            # ================= 侧边栏 =================
            with gr.Column(scale=1, min_width=250, elem_classes="kender-sidebar"):
                gr.Markdown("### ⚙️ 设置")
                enable_search = gr.Checkbox(
                    label="🌐 优先联网搜索",
                    value=False,
                    info="开启后 Kender 会优先检索最新网络信息",
                )
                clear_btn = gr.ClearButton(
                    value="🧹 清空对话",
                )

                gr.Markdown("---")
                gr.Markdown("### 🤖 关于 Kender")
                gr.Markdown(
                    "Kender 是一个基于 **ReAct** 推理的 AI 助手：\n"
                    "- 自主决定何时调用哪个工具\n"
                    "- 参数缺失时会主动追问补全（填槽）\n"
                    "- 能读取你上传的文档并做向量检索\n"
                    "- 跨会话记住关于你的事实\n"
                    "- **多 Agent 协作**：生成回答后由 Critic 审核Agent 把关，"
                    "不合格会打回重写\n\n"
                    "对话下方的面板可以展开，看到每一轮的"
                    "「思考 → 行动 → 观察」和审核结论。"
                )

                mcp_status = gr.Markdown("🔌 工具接入：初始化中…")

            # ================= 主聊天区 =================
            with gr.Column(scale=4, elem_classes="kender-main"):
                chatbot = gr.Chatbot(
                    label="",
                    height=620,
                    elem_classes="kender-chat",
                    value=[],
                )
                # 清空按钮需等 chatbot 定义后再绑定（避免 NameError）
                clear_btn.add([chatbot, chat_history])

                # ReAct 推理轨迹：把"思考 → 行动 → 观察"展示出来，
                # 让 Agent 的离散化决策过程可见（面试时可直接指着讲）
                with gr.Accordion("🔍 推理轨迹与质量审核（思考 → 行动 → 观察）", open=False, elem_classes="kender-trace"):
                    trace_md = gr.Markdown(
                        "*发一条消息，这里会显示 Kender 这一轮的推理过程，"
                        "以及 Critic 审核Agent 给出的结论*"
                    )

                file_status = gr.Markdown("")

                with gr.Row(equal_height=True):
                    file_input = gr.File(
                        label="📎 上传文档",
                        file_types=[".txt", ".docx", ".pdf"],
                        scale=3,
                        elem_classes="kender-file",
                    )
                    msg_input = gr.Textbox(
                        label="",
                        placeholder="给 Kender 发消息…（Enter 发送，Shift+Enter 换行）",
                        lines=2,
                        scale=9,
                        elem_id="kender-msg-input",
                        elem_classes="kender-input",
                        container=False,
                    )
                    send_btn = gr.Button(
                        "发送",
                        variant="primary",
                        scale=2,
                        elem_id="kender-send-btn",
                        elem_classes="kender-send",
                    )

                gr.Markdown("### 💡 试试这些")
                gr.Examples(
                    examples=[
                        "帮我查一下今天上海的天气",
                        "今天天气怎么样",
                        "帮我设个提醒",
                        "用通俗的话解释一下什么是 RAG",
                        "帮我总结一下我上传的文档",
                        "你记得我之前跟你说过什么吗？",
                    ],
                    inputs=msg_input,
                )

        gr.HTML(FOOTER_HTML)

        # ================= 交互逻辑 =================
        def build_user_message(message, enable_search):
            # 是否优先联网交由 Agent 自主决策（search_web 工具）；
            # 这里仅在用户勾选时给一句偏好提示，最终是否调用仍是模型决定。
            # 注意：文档不再全文注入，而是由 RAG 工具 retrieve_document 按问题检索片段。
            if enable_search:
                message = f"{message}\n\n[偏好提示] 用户希望优先使用联网搜索获取最新信息。"
            return message

        async def handle_file(f):
            if f is None:
                return ""
            from .rag import build_index
            try:
                content = read_document(f.name)
                # 构建向量库涉及 Embedding 的阻塞 HTTP 调用，丢到线程池避免卡住 UI 事件循环
                n = await asyncio.to_thread(build_index, content)
                name = f.name.replace("\\", "/").split("/")[-1]
                return f"✅ 已构建向量库：**{name}**（{n} 个片段已索引）。现在可以让 Kender 检索文档内容了。"
            except Exception as e:
                return f"⚠️ 构建向量库失败：{e}"

        file_input.change(handle_file, [file_input], [file_status])

        async def respond(msg, history, search):
            # 空消息不处理（gr.update() 表示轨迹面板保持原样，不刷新）
            if not msg or not msg.strip():
                yield "", history, history, gr.update()
                return

            user_msg = msg.strip()
            agent_input = build_user_message(user_msg, search)

            # 1) 先展示「正在思考」占位，提升交互反馈（仅更新显示，不写入历史）
            thinking = list(history) + [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": "⏳ Kender 正在思考…"},
            ]
            yield "", thinking, history, "⏳ 正在推理，稍后这里会显示完整轨迹…"

            # 2) 取完整回复 + ReAct 轨迹（保留工具调用 + 长期记忆持久化）。
            #    AgentScope 的 ReAct 封装聚合返回，未暴露 token 级流式接口，
            #    因此这里直接 await 完整回复，再于前端做增量渲染。
            try:
                # 生成 → Critic 审核 → 不合格打回重写（评审式多 Agent 协作）
                full_reply, trace, verdict, rounds = await get_reply_with_review(
                    agent, model, agent_input, memory
                )
            except Exception as e:
                err_history = list(history) + [
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": f"⚠️ 错误：{e}"},
                ]
                yield "", err_history, err_history, f"⚠️ 出错：{e}"
                return

            # 3) 打字机式增量显示（前端 incremental rendering）。
            #    模型侧暂未做 token 级 streaming，改为拿到完整回复后逐字 reveal，
            #    体感上接近流式输出。真 token streaming 见 README 的 Future Work。
            base = list(history) + [{"role": "user", "content": user_msg}]
            step = 3
            for i in range(step, len(full_reply) + step, step):
                shown = full_reply[:i]
                current = base + [{"role": "assistant", "content": shown}]
                yield "", current, current, gr.update()
                await asyncio.sleep(0.018)
            # 确保最终完整呈现，并在轨迹面板展示审核结论 + ReAct 过程
            if verdict.passed:
                review_line = f"**审核通过**（第 {rounds} 轮）· {verdict.reason}"
            else:
                review_line = f"**审核仍未通过**（已重试 {rounds} 轮）· {verdict.reason}"
            final = base + [{"role": "assistant", "content": full_reply}]
            yield "", final, final, f"{review_line}\n\n{trace}"

        send_btn.click(
            respond,
            [msg_input, chat_history, enable_search],
            [msg_input, chatbot, chat_history, trace_md],
        )
        msg_input.submit(
            respond,
            [msg_input, chat_history, enable_search],
            [msg_input, chatbot, chat_history, trace_md],
        )

        # 页面加载完成后再接 MCP。
        # 必须用 demo.load 的异步钩子，而不是在 create_ui() 里直接接：
        # MCP 的 stdio 客户端会绑定到当前事件循环，而 respond() 也跑在这个循环里，
        # 两者必须是同一个；放在同步的 create_ui() 里会导致跨循环调用失败。
        async def init_tools():
            names = await attach_mcp_tools(agent.toolkit)
            if names:
                return f"🔌 已接入 MCP Server（协议层）：`{', '.join(names)}`"
            return "🔌 使用进程内工具（MCP 未接入或已降级）"

        demo.load(init_tools, outputs=[mcp_status])

    return demo
