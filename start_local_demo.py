# -*- coding: utf-8 -*-
"""本地一键启动 Kender 演示（Gradio 界面 + FastAPI 接口）。

用法（在项目根目录）：
    python start_local_demo.py

会做三件事：
1. 起 FastAPI 服务 -> http://127.0.0.1:<可用端口>/docs
2. 起 Gradio 界面 -> http://127.0.0.1:<可用端口>
3. 两个进程都活着时打印地址，Ctrl+C 一起退出

端口如果被别的程序占着，会自动往后顺延找空闲端口，不会直接报错退出。
（历史坑：8003 / 7860 被上一次没关干净的服务占用时，脚本会崩在 bind 上，
  所以这里先探测再启动，并把实际端口打印出来。）

面试演示前跑这个，避免临时敲命令出错。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request

API_PORT = 8003
UI_PORT = 7860
PORT_TRIES = 20


def find_free_port(preferred: int, tries: int = PORT_TRIES) -> int:
    """优先用 preferred；被占用就顺延，最多试 tries 个。"""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"从 {preferred} 开始的 {tries} 个端口都被占用了，请先关掉占用端口的程序"
    )


def alive(url: str, timeout: float = 1.5) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def wait(name: str, url: str, proc: subprocess.Popen, seconds: float = 40) -> bool:
    t0 = time.time()
    while time.time() - t0 < seconds:
        if alive(url):
            print(f"  [OK] {name} 已就绪")
            return True
        if proc.poll() is not None:
            print(f"  [X] {name} 启动失败（进程已退出，退出码 {proc.returncode}）")
            return False
        time.sleep(1)
    print(f"  [!] {name} 启动超时")
    return False


def main() -> None:
    try:
        api_port = find_free_port(API_PORT)
        ui_port = find_free_port(UI_PORT)
    except RuntimeError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    if api_port != API_PORT:
        print(f"[提示] {API_PORT} 被占用，接口改用 {api_port}")
    if ui_port != UI_PORT:
        print(f"[提示] {UI_PORT} 被占用，界面改用 {ui_port}")

    env = os.environ.copy()
    env["GRADIO_SERVER_NAME"] = "127.0.0.1"
    env["GRADIO_SERVER_PORT"] = str(ui_port)

    print("正在启动本地演示...")
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app",
             "--host", "127.0.0.1", "--port", str(api_port)],
            env=env,
        ),
        subprocess.Popen([sys.executable, "app.py"], env=env),
    ]

    ok = True
    try:
        ok &= wait("FastAPI 接口文档", f"http://127.0.0.1:{api_port}/docs", procs[0])
        ok &= wait("Gradio 界面", f"http://127.0.0.1:{ui_port}/", procs[1])

        if ok:
            print("\n演示地址：")
            print(f"  界面  http://127.0.0.1:{ui_port}")
            print(f"  接口  http://127.0.0.1:{api_port}/docs")
            print("\n按 Ctrl+C 结束演示")
            while True:
                time.sleep(1)
        else:
            print("\n有服务没起来，下面是已启动进程的输出，把报错发我看看：")
            for p in procs:
                if p.poll() is not None:
                    continue
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n正在关闭...")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
