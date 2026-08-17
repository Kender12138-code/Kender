import asyncio
import gradio as gr
from .memory import load_memory
from .agent import create_agent, get_reply
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
  🔧 Kender · 由 <b>AgentScope</b> + <b>Gradio</b> 构建 · 对话内容仅保存在本地
</div>
"""

# ===================== 自定义样式与主题 =====================
# 注意：Gradio 6 要求 theme / css 在 launch() 中传入，而非 Blocks() 构造器。
KENDER_CSS = """
/* 注：不引入外部 Google Fonts，避免网络抽风导致页面长时间"加载中"。
   系统字体栈已覆盖 Windows/macOS/Linux 的中文与西文显示。 */
.gradio-container {
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', sans-serif !important;
  background: linear-gradient(135deg, #eef2ff 0%, #f8fafc 45%, #ecfeff 100%) !important;
  max-width: 1180px !important;
  margin: 0 auto !important;
  padding-top: 14px !important;
}

/* 品牌头部 */
.kender-header {
  background: linear-gradient(120deg, #6366f1 0%, #06b6d4 100%);
  border-radius: 18px;
  padding: 22px 28px;
  color: #fff;
  box-shadow: 0 14px 34px rgba(99, 102, 241, 0.28);
  margin-bottom: 18px;
}
.kender-logo { font-size: 28px; font-weight: 800; letter-spacing: 0.5px; }
.kender-tagline { margin-top: 6px; font-size: 13.5px; opacity: 0.92; }

/* 页脚 */
.kender-footer {
  text-align: center;
  font-size: 12px;
  color: #64748b;
  margin-top: 16px;
  padding-bottom: 8px;
}

/* 侧边栏卡片 */
.kender-sidebar {
  background: #fff !important;
  border-radius: 18px !important;
  padding: 18px 16px !important;
  box-shadow: 0 6px 24px rgba(15, 23, 42, 0.06) !important;
  border: 1px solid rgba(99, 102, 241, 0.08) !important;
}

/* 聊天气泡容器 */
.kender-chat {
  border-radius: 18px !important;
  border: 1px solid rgba(99, 102, 241, 0.12) !important;
  box-shadow: 0 6px 24px rgba(15, 23, 42, 0.06) !important;
  background: #fff !important;
}
.kender-chat .message-wrap.user > .message {
  background: linear-gradient(120deg, #6366f1, #818cf8) !important;
  color: #fff !important;
}
.kender-chat .message-wrap.bot > .message {
  background: #f1f5f9 !important;
  color: #0f172a !important;
}

/* 发送按钮 */
.kender-send {
  background: linear-gradient(120deg, #6366f1, #06b6d4) !important;
  color: #fff !important;
  font-weight: 700 !important;
  border: none !important;
  border-radius: 14px !important;
  box-shadow: 0 6px 18px rgba(99, 102, 241, 0.35) !important;
}
.kender-send:hover { filter: brightness(1.06); }

/* 输入框 */
.kender-input textarea {
  border-radius: 14px !important;
  border: 1px solid rgba(99, 102, 241, 0.25) !important;
  font-size: 15px !important;
}
.kender-input textarea:focus {
  border-color: #6366f1 !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15) !important;
}

/* 文件框 */
.kender-file { border-radius: 14px !important; }

/* 示例区 */
.kender-examples .examples {
  border-radius: 12px !important;
  border: 1px dashed rgba(99, 102, 241, 0.35) !important;
  background: #faf5ff !important;
}
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
                    "- 自主决定何时联网搜索\n"
                    "- 能读取你上传的文档\n"
                    "- 跨会话记住关于你的事实"
                )

            # ================= 主聊天区 =================
            with gr.Column(scale=4):
                chatbot = gr.Chatbot(
                    label="",
                    height=540,
                    elem_classes="kender-chat",
                    value=[],
                )
                # 清空按钮需等 chatbot 定义后再绑定（避免 NameError）
                clear_btn.add([chatbot, chat_history])

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
                        "🚀 发送",
                        variant="primary",
                        scale=2,
                        elem_id="kender-send-btn",
                        elem_classes="kender-send",
                    )

                gr.Markdown("### 💡 试试这些")
                gr.Examples(
                    examples=[
                        "帮我查一下今天上海的天气",
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
            # 空消息不处理
            if not msg or not msg.strip():
                yield "", history, history
                return

            user_msg = msg.strip()
            agent_input = build_user_message(user_msg, search)

            # 1) 先展示「正在思考」占位，提升交互反馈（仅更新显示，不写入历史）
            thinking = list(history) + [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": "⏳ Kender 正在思考…"},
            ]
            yield "", thinking, history

            # 2) 取完整回复（保留 ReAct 工具调用 + 长期记忆持久化）。
            #    AgentScope 的 ReAct 封装聚合返回，未暴露 token 级流式接口，
            #    因此这里直接 await 完整回复，再于前端做增量渲染。
            try:
                full_reply = await get_reply(agent, model, agent_input, memory)
            except Exception as e:
                err_history = list(history) + [
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": f"⚠️ 错误：{e}"},
                ]
                yield "", err_history, err_history
                return

            # 3) 打字机式增量显示（前端 incremental rendering）。
            #    模型侧暂未做 token 级 streaming，改为拿到完整回复后逐字 reveal，
            #    体感上接近流式输出。真 token streaming 见 README 的 Future Work。
            base = list(history) + [{"role": "user", "content": user_msg}]
            step = 3
            shown = ""
            for i in range(step, len(full_reply) + step, step):
                shown = full_reply[:i]
                current = base + [{"role": "assistant", "content": shown}]
                yield "", current, current
                await asyncio.sleep(0.018)
            # 确保最终完整呈现
            final = base + [{"role": "assistant", "content": full_reply}]
            yield "", final, final

        send_btn.click(
            respond,
            [msg_input, chat_history, enable_search],
            [msg_input, chatbot, chat_history],
        )
        msg_input.submit(
            respond,
            [msg_input, chat_history, enable_search],
            [msg_input, chatbot, chat_history],
        )

    return demo
