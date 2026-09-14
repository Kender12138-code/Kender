---
name: kender-verify
description: 改完 Kender 代码后做离线验证：跑单测、CLI 冒烟（exit/EOF 退出、单轮错误兜底、MCP 子进程回收）、端口残留检查。改动 Python 代码后用；改 prompt 文案或文档不需要。
---

# Kender Verify

改完 Kender 的代码后，用它把"离线能抓住的回归"一次排掉。核心原则：**验证过程不调用真实模型**——不消耗 `DASHSCOPE_API_KEY`，也不依赖外网。

## 依次跑这四项

1. 语法检查（改过的文件都要在参数里）：

   ```bash
   python -m compileall -q src server.py app.py main.py mcp_server
   ```

2. 单元测试，期望 `12 passed`：

   ```bash
   python -m pytest tests -q -p no:cacheprovider
   ```

   不要用显式路径在仓库根收集测试：`preview_test*.py` 会在**收集阶段**就 `demo.launch()` 起 Gradio 服务器，pytest 会永久卡在 `collecting ...`。仓库根的 [pytest.ini](../../../pytest.ini) 已把收集范围限制在 `tests/`。

3. CLI 冒烟（本技能自带脚本）：

   ```bash
   python .agents/skills/kender-verify/scripts/smoke_cli.py
   ```

   它依次断言：喂 `exit` 能干净退出并打印"已停止 MCP Server 子进程"；stdin 直接关闭（模拟 Ctrl+Z / Ctrl+D）不吐 `EOFError`；两次运行结束后 8100 端口都已释放。

4. 只有当改动涉及 `server.py` 的鉴权时，才额外起一次真实服务：设 `KENDER_API_TOKEN=test123` 启 uvicorn，然后 `/health` 返回 200、**不带 token** 的 `POST /chat` 返回 401。

   **不要**测带正确 token 的 `/chat`——那条路径会真的调用模型、花你的钱。

## 判定

第 1–3 项全绿才算通过；冒烟脚本退出码非 0 即失败，会打印缺失项和不该出现的字符串。

## 已知假阳性（别当成 bug 去改代码）

- PowerShell 里 `curl.exe -d '{"message":"hi"}'` 会被吞掉引号，服务端返回 422——用 `Invoke-WebRequest -Body '{"message":"hi"}'` 重测。
- 本机 curl 直连 https 可能报 `schannel ... CRYPT_E_REVOCATION_OFFLINE`（证书吊销检查走不通），加 `--ssl-no-revoke`。
- PowerShell 管道喂中文给 python 会变成 `?`（管道按控制台编码发字节）：`'你好' | python -c "..."` 收到的是 `'?????'`。做真实的对话验证前先设 `$OutputEncoding = [System.Text.UTF8Encoding]::new($false)`，或把内容写进文件再重定向；用 Python 的 `subprocess.run(input=..., encoding="utf-8")` 不受影响。
- 冒烟脚本会往 `data/mcp_server.log` 追加日志；`data/` 已 gitignore，属正常。

## 收尾

确认没有残留的 python 进程，且 8100 / 7860 / 8003 都没有监听。演示前尤其要确认这一点——"端口被上一次没关干净的服务占着"是这个项目历史上最常见的翻车原因。
