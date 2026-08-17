import asyncio
import os
import sys
from src.ui import create_ui, KENDER_CSS, KENDER_HEAD, KENDER_THEME

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--web":
        server_name = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
        create_ui().launch(
            share=False,
            server_name=server_name,
            server_port=7860,
            theme=KENDER_THEME,
            css=KENDER_CSS,
            head=KENDER_HEAD,
        )
    else:
        from src.memory import load_memory, save_memory
        from src.agent import create_agent, get_reply
        memory = load_memory()
        agent, model = create_agent(memory)
        print("Kender CLI 已启动，输入 exit 退出")
        while True:
            user_input = input("你: ").strip()
            if user_input.lower() == "exit":
                break
            reply = asyncio.run(get_reply(agent, model, user_input, memory))
            print(f"Kender: {reply}")
        save_memory(memory)