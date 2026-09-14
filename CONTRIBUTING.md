# 贡献指南

感谢关注 **Kender**！这是一个用于个人学习 / 求职作品集的 Agent 项目，欢迎提出建议与 Issue。

## 🛠️ 本地开发

```bash
pip install -r requirements.txt
cp .env.example .env      # 填入你的 DASHSCOPE_API_KEY
python main.py --web      # 启动 Web 界面（默认 http://127.0.0.1:7860）
```

## ✅ 代码规范

- 遵循 PEP 8；
- 新增功能请同步更新 `tests/` 下的冒烟测试；
- 提交前请运行 `pytest` 确保通过（仓库根的 `pytest.ini` 已把收集范围限制在 `tests/`，裸跑 `pytest` 即可）；
- 涉及前端样式 / 快捷键修改时，请注意 Gradio 6 的 Shadow DOM 限制（详见 `src/ui.py` 代码注释）。

## 🔍 改完代码怎么验证

```bash
python -m compileall -q src server.py app.py main.py mcp_server   # 语法
python -m pytest tests -q                                        # 单元测试
python .agents/skills/kender-verify/scripts/smoke_cli.py          # CLI 冒烟 + 端口残留检查
```

仓库里带了一个仓库级 Codex 技能 [`.agents/skills/kender-verify/`](.agents/skills/kender-verify/SKILL.md)，把上面这套验证流程固定下来了：在 Codex 里说一句"改完验证一下"，或者输入 `$kender-verify`，就会按它执行。

## 🐳 Docker

```bash
docker build -t kender .
docker run --env-file .env -p 7860:7860 kender
```

## 📮 提交 Issue / PR

- Bug 请附**复现步骤**与报错信息；
- 功能建议请说明**使用场景**；
- 本项目目前由作者个人维护，回复可能不及时，请见谅。
