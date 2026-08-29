import asyncio
import os
import sys
from src.ui import create_ui, KENDER_CSS, KENDER_HEAD, KENDER_THEME, resolve_auth


async def run_cli():
    """命令行对话模式。

    整个会话跑在同一个事件循环里 —— MCP 客户端连接后也在这个循环中被调用，
    所以这里用一次 asyncio.run 包住整个会话，而不是每轮对话各 run 一次。
    """
    from src.memory import load_memory
    from src.agent import attach_mcp_tools, create_agent, get_reply

    memory = load_memory()
    agent, model = create_agent(memory)
    await attach_mcp_tools(agent.toolkit)

    print("Kender CLI 已启动，输入 exit 退出")
    while True:
        user_input = input("你: ").strip()
        if user_input.lower() == "exit":
            break
        reply = await get_reply(agent, model, user_input, memory)
        print(f"Kender: {reply}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--web":
        server_name = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
        # 设了 KENDER_AUTH_USER / KENDER_AUTH_PASS 才启用口令，本地不设即免密
        create_ui().launch(
            auth=resolve_auth(),
            share=False,
            server_name=server_name,
            server_port=7860,
            theme=KENDER_THEME,
            css=KENDER_CSS,
            head=KENDER_HEAD,
        )
    else:
        asyncio.run(run_cli())