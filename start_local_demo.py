# -*- coding: utf-8 -*-
"""本地一键启动 Kender 演示（Gradio 界面 + FastAPI 接口）。

用法（在项目根目录）：
    python start_local_demo.py

会做三件事：
1. 起 FastAPI 服务 -> http://127.0.0.1:8003/docs
2. 起 Gradio 界面 -> http://127.0.0.1:7860
3. 两个进程都活着时打印地址，Ctrl+C 一起退出

面试演示前跑这个，避免临时敲命令出错。
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request

API_PORT = 8003
UI_PORT = 7860


def alive(url: str, timeout: float = 1.5) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def wait(name: str, url: str, seconds: float = 40) -> bool:
    t0 = time.time()
    while time.time() - t0 < seconds:
        if alive(url):
            print(f"  {name} 已就绪：{url}")
            return True
        time.sleep(1)
    print(f"  {name} 启动超时（详见各自的输出）")
    return False


def main() -> None:
    procs = []
    env_ui = {"GRADIO_SERVER_NAME": "127.0.0.1", "GRADIO_SERVER_PORT": str(UI_PORT)}

    import os

    env = os.environ.copy()
    env.update(env_ui)

    print("正在启动本地演示...")
    procs.append(
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
             "--port", str(API_PORT)],
            env=env,
        )
    )
    procs.append(subprocess.Popen([sys.executable, "app.py"], env=env))

    try:
        wait("FastAPI 接口文档", f"http://127.0.0.1:{API_PORT}/docs")
        wait("Gradio 界面", f"http://127.0.0.1:{UI_PORT}/")
        print("\n演示地址：")
        print(f"  界面  http://127.0.0.1:{UI_PORT}")
        print(f"  接口  http://127.0.0.1:{API_PORT}/docs")
        print("\n按 Ctrl+C 结束演示")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在关闭...")
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
