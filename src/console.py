"""控制台编码兜底（Windows 专用问题的通用修复）。

## 问题

Windows 的 stdout 默认编码是 GBK（cp936）。AgentScope 的 ReActAgent 会把
模型的思考过程、工具调用和返回 print 到 stdout（这是框架行为，关不掉），
而大模型输出 emoji 极其常见（🌦️ ✨ 😊）。

一旦 print 撞上 GBK 编不出来的字符，就抛 `UnicodeEncodeError: 'gbk' codec
can't encode character ...`。这个异常发生在 `agent.reply()` 内部，会被
`_run_once` 的 try/except 捕获，于是用户看到的是：

    ⚠️ 抱歉，调用模型时出错了：... 'gbk' codec can't encode ...

而实际上模型答得好好的，只是控制台打不出来。这是本项目在 Windows 上最隐蔽
的一个坑：同一句话在 Linux/服务器上没问题，在自己电脑上必崩。

## 修复

进程启动时把 stdout/stderr 重设成 UTF-8。`TextIOWrapper.reconfigure` 是
Python 3.7+ 的 API，只改编码、不重建流，不会影响已经写出去的内容。

在 `src/__init__.py` 里调用，保证凡是 `import src.*` 的入口（main.py、
app.py、server.py、start_local_demo.py）都自动生效，不用每个入口各改一遍。
"""
from __future__ import annotations

import sys


def force_utf8() -> bool:
    """把 stdout / stderr 切到 UTF-8。返回是否至少成功改造了一个流。"""
    ok = False
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
            ok = True
        except Exception:  # noqa: BLE001
            # 已经被重定向成非 TextIOWrapper（比如某些测试框架、GUI 包装）时跳过
            pass
    return ok
