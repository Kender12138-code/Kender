# -*- coding: utf-8 -*-
"""本地一键启动 Kender 演示（Gradio 界面 + FastAPI 接口）。

用法（在项目根目录）：
    python start_local_demo.py                  # 推荐：先清理残留进程，再启动
    python start_local_demo.py --keep-existing  # 不清理，直接把端口往后顺延

会做四件事：
1. 清理上一次没退干净的 Kender 演示进程（只认自己的进程，绝不碰别的程序）
2. 起 FastAPI 服务 -> http://127.0.0.1:<端口>/docs
3. 起 Gradio 界面 -> http://127.0.0.1:<端口>
4. 两个进程都活着时打印地址，Ctrl+C 一起退出（退出时按进程树结束，不留尾巴）

端口策略：默认端口被占着时，先判断是不是自己上一次的残留进程——
是自己人就地清理（端口回到默认值），是别的程序才往后顺延，并把实际端口打印出来。

（历史坑一：8003 / 7860 被上一次没关干净的服务占用时，脚本会直接崩在 bind 上。
  历史坑二：改成"自动顺延端口"后虽然不崩了，但端口老在漂移，而且每次启动都多出一份
  僵尸演示进程——根因是退出时只 terminate 了直接子进程，孙子进程（MCP server）和
  部分残留还活着。所以这里补上：启动前清理 + 退出时按进程树结束。）

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
MCP_PORT = int(os.getenv("KENDER_MCP_PORT", "8100"))
PORT_TRIES = 20

# 只清理命令行命中这些特征的进程，避免误杀别的程序
_OWN_MARKERS = ("start_local_demo.py", "reminder_server.py", "server:app")
# HTTP 侧的身份确认路径（返回内容里含 "kender" 才认定是自己人）
_HTTP_IDENTITY = {UI_PORT: "/config", API_PORT: "/openapi.json"}


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


def listening_pids(port: int) -> list[int]:
    """返回正在监听指定端口的进程 PID（探测不到就返回空列表，不阻断启动）。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            timeout=15,
            errors="ignore",
        ).stdout
    except Exception:  # noqa: BLE001
        return []
    pids: set[int] = set()
    for line in out.splitlines():
        parts = line.split()
        if (
            len(parts) >= 5
            and parts[0].upper() == "TCP"
            and parts[3].upper().startswith("LISTEN")
            and parts[1].rsplit(":", 1)[-1] == str(port)
        ):
            try:
                pids.add(int(parts[4]))
            except ValueError:
                pass
    return sorted(pids)


def command_lines(pids: list[int]) -> dict[int, str]:
    """取进程命令行，用来确认这是不是我们自己的演示进程。"""
    if not pids:
        return {}
    if os.name != "nt":
        result: dict[int, str] = {}
        for pid in pids:
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    result[pid] = f.read().replace(b"\x00", b" ").decode("utf-8", "ignore")
            except OSError:
                pass
        return result

    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in @("
        + ",".join(str(p) for p in pids)
        + ') } | ForEach-Object { "$($_.ProcessId)|$($_.CommandLine)" }'
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            errors="ignore",
        )
    except Exception:  # noqa: BLE001
        return {}
    result = {}
    for line in proc.stdout.splitlines():
        pid_s, _, cmd = line.partition("|")
        if pid_s.strip().isdigit():
            result[int(pid_s.strip())] = cmd.strip()
    return result


def looks_like_our_service(port: int) -> bool:
    """HTTP 探测：这个端口上跑的确实是我们自己的 Kender 演示吗？"""
    path = _HTTP_IDENTITY.get(port, "/")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as resp:
            return "kender" in resp.read(40000).decode("utf-8", "ignore").lower()
    except Exception:  # noqa: BLE001
        return False


def is_our_leftover(port: int, pid: int, cmds: dict[int, str]) -> bool:
    """双重确认：命令行特征命中，或 HTTP 自报家门是 Kender。"""
    cmd = cmds.get(pid, "").replace("\\", "/").lower()
    if cmd and "python" in cmd and any(m in cmd for m in _OWN_MARKERS):
        return True
    return looks_like_our_service(port)


def kill_tree(pid: int) -> bool:
    """结束进程及其子进程（Windows 上用 taskkill /T，否则孙进程会变成残留）。"""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=20,
                errors="ignore",
            )
        else:
            os.kill(pid, 15)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [!] 结束进程 {pid} 失败：{type(e).__name__}: {e}")
        return False


def cleanup_stale(ports: tuple[int, ...]) -> int:
    """启动前清掉上一次没退干净的自己人，让端口尽量回到默认值。返回清理数量。"""
    killed = 0
    for port in ports:
        pids = listening_pids(port)
        if not pids:
            continue
        cmds = command_lines(pids)
        for pid in pids:
            if is_our_leftover(port, pid, cmds):
                print(f"[清理] {port} 被上一次没关掉的 Kender 演示占用（PID {pid}），已结束它")
                if kill_tree(pid):
                    killed += 1
            else:
                print(f"[提示] {port} 被其它程序占用（PID {pid}），不动它，稍后顺延端口")
    if killed:
        time.sleep(1.5)  # 等系统回收端口
    return killed


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
    if "--keep-existing" not in sys.argv:
        cleanup_stale((API_PORT, UI_PORT, MCP_PORT))

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

    try:
        ok = True
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
            print("\n有服务没起来，把上面这段报错发我看看。")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n正在关闭...")
    finally:
        # 按进程树结束：只 terminate 直接子进程的话，孙进程（MCP server）
        # 会活下来继续占端口，下次启动就得顺延——这就是端口漂移的根因。
        for p in procs:
            if p.poll() is None:
                kill_tree(p.pid)
        print("已清理全部演示进程，端口已释放。")


if __name__ == "__main__":
    main()
