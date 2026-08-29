import os

from src.ui import create_ui, KENDER_CSS, KENDER_HEAD, KENDER_THEME, resolve_auth

# HuggingFace Spaces / Docker 通用入口：
# - 监听 0.0.0.0 + 7860，使容器或 Spaces 能从外部访问
# - 端口与地址优先读环境变量，本地 Docker 与 HF Spaces 都能直接用
# - 公网部署时务必设置 KENDER_AUTH_USER / KENDER_AUTH_PASS，
#   否则任何人打开页面都能消耗你的 DASHSCOPE_API_KEY
if __name__ == "__main__":
    server_name = os.getenv("GRADIO_SERVER_NAME", "0.0.0.0")
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    create_ui().launch(
        auth=resolve_auth(),
        server_name=server_name,
        server_port=server_port,
        share=False,
        theme=KENDER_THEME,
        css=KENDER_CSS,
        head=KENDER_HEAD,
    )
