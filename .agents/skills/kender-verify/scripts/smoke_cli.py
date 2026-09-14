"""Kender CLI 冒烟检查（离线，不调用模型）。

用法（任意工作目录）：
    python .agents/skills/kender-verify/scripts/smoke_cli.py

退出码 0 = 全部通过。检查项：
  1. 喂 "exit" 能干净退出，且退出时回收了 MCP Server 子进程
  2. 运行结束后 8100 端口已释放
  3. stdin 直接关闭（模拟 Ctrl+Z / Ctrl+D）不吐 EOFError
  4. 那次运行结束后 8100 同样已释放
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

# scripts/ -> kender-verify/ -> skills/ -> .agents/ -> 仓库根
REPO_ROOT = Path(__file__).resolve().parents[4]
MCP_PORT = int(os.getenv("KENDER_MCP_PORT", "8100"))
TIMEOUT = 240


def _force_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def run_cli(use_eof: bool) -> str:
    """跑一次 `python main.py`：喂 'exit\\n'，或直接关掉 stdin（EOF）。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    extra = {"stdin": subprocess.DEVNULL} if use_eof else {"input": "exit\n"}
    try:
        proc = subprocess.run(
            [sys.executable, "main.py"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            **extra,
        )
    except subprocess.TimeoutExpired:
        return "<<TIMEOUT>>"
    return (proc.stdout or "") + (proc.stderr or "")


def check_output(name: str, output: str, must: tuple[str, ...]) -> bool:
    missing = [m for m in must if m not in output]
    leaked = [m for m in ("Traceback", "EOFError") if m in output]
    ok = not missing and not leaked
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if missing:
        print(f"       缺少: {missing}")
    if leaked:
        print(f"       不应出现: {leaked}")
    return ok


def check_port_free(name: str) -> bool:
    busy = port_open(MCP_PORT)
    print(f"[{'FAIL' if busy else 'PASS'}] {name}")
    return not busy


def main() -> int:
    _force_utf8_stdout()
    print(f"仓库根目录: {REPO_ROOT}")
    print(f"Python: {sys.executable}")
    if port_open(MCP_PORT):
        print(f"[WARN] 开跑前 {MCP_PORT} 已被占用，可能是别的进程在用，会干扰下面的断言")

    results = []

    out = run_cli(use_eof=False)
    results.append(
        check_output(
            "exit 干净退出 + 回收 MCP 子进程",
            out,
            ("Kender CLI 已启动", "已停止 MCP Server 子进程"),
        )
    )
    results.append(check_port_free(f"退出后 {MCP_PORT} 端口已释放"))

    out = run_cli(use_eof=True)
    results.append(check_output("stdin 关闭(EOF) 不吐 traceback", out, ("再见",)))
    results.append(check_port_free(f"EOF 退出后 {MCP_PORT} 端口已释放"))

    passed = sum(results)
    print(f"\n{'全部通过' if all(results) else '有失败项'}：{passed}/{len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
