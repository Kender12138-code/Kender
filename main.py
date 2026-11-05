import argparse
import asyncio
import os


async def run_cli():
    """命令行对话模式。

    整个会话跑在同一个事件循环里 —— MCP 客户端连接后也在这个循环中被调用，
    所以这里用一次 asyncio.run 包住整个会话，而不是每轮对话各 run 一次。

    两处稳定性兜底（2026-09-14 补）：
      1. stdin 关闭（Ctrl+Z / Ctrl+D / 管道读完）抛 EOFError，Ctrl+C 抛
         KeyboardInterrupt —— 都要当成"正常退出"，不能吐 traceback。
      2. 单轮出错（网络抖动、模型报错）不能带走整个会话：
         get_reply 内部的记忆抽取路径不保证吞掉所有异常，这里再兜一层。
    """
    from src.agent import (
        attach_mcp_tools,
        create_agent,
        get_reply_with_review,
        shutdown_mcp_server,
    )
    from src.memory import load_memory

    memory = load_memory()
    agent, model = create_agent(memory)
    await attach_mcp_tools(agent.toolkit)

    print("Kender CLI 已启动，输入 exit 退出")
    try:
        while True:
            try:
                user_input = input("你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nKender: 再见（会话已结束）")
                break

            if not user_input:
                continue  # 空回车不浪费一次模型调用
            if user_input.lower() in ("exit", "quit"):
                break

            try:
                # 与网页端保持一致：走「生成 → Critic 审核 → 不合格重写」链路。
                # 早期 CLI 直接调 get_reply，既没有质量审核、也没有编造守卫，
                # 同一句话在 CLI 和网页上表现不一样，属于两个产品。
                reply, _trace, verdict, rounds = await get_reply_with_review(
                    agent, model, user_input, memory
                )
                if rounds > 1:
                    print(f"（已自动重写 {rounds - 1} 次：{verdict.reason}）")
            except Exception as e:  # noqa: BLE001
                print(
                    f"Kender: ⚠️ 这一轮出错了（{type(e).__name__}: {e}），"
                    "会话还在，可以再问一次。"
                )
                continue
            print(f"Kender: {reply}")
    finally:
        # 退出前回收自己起的 MCP Server 子进程，别让 8100 留残兵
        shutdown_mcp_server()


def run_web():
    """启动 Gradio 网页界面（默认 127.0.0.1:7860）。"""
    from src.agent import shutdown_mcp_server
    from src.ui import KENDER_CSS, KENDER_HEAD, KENDER_THEME, create_ui, resolve_auth

    server_name = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
    # 端口跟 app.py / start_local_demo.py 保持一致：环境变量优先，默认 7860
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    try:
        # 设了 KENDER_AUTH_USER / KENDER_AUTH_PASS 才启用口令，本地不设即免密
        create_ui().launch(
            auth=resolve_auth(),
            share=False,
            server_name=server_name,
            server_port=server_port,
            theme=KENDER_THEME,
            css=KENDER_CSS,
            head=KENDER_HEAD,
        )
    finally:
        # 网页会话里 MCP Server 是本进程拉起来的（见 src/ui.py），退出时同样要收
        shutdown_mcp_server()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Kender 入口：默认进命令行对话，--web 启动网页界面。",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="启动 Gradio 网页界面（默认 http://127.0.0.1:7860，可用 GRADIO_SERVER_NAME/PORT 覆盖）",
    )
    args = parser.parse_args(argv)

    if args.web:
        run_web()
    else:
        asyncio.run(run_cli())


if __name__ == "__main__":
    main()
