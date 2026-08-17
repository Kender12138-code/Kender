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
- 提交前请运行 `pytest` 确保通过；
- 涉及前端样式 / 快捷键修改时，请注意 Gradio 6 的 Shadow DOM 限制（详见 `src/ui.py` 代码注释）。

## 🐳 Docker

```bash
docker build -t kender .
docker run --env-file .env -p 7860:7860 kender
```

## 📮 提交 Issue / PR

- Bug 请附**复现步骤**与报错信息；
- 功能建议请说明**使用场景**；
- 本项目目前由作者个人维护，回复可能不及时，请见谅。
