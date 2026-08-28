# Kender — 你的专属 AI 生活助手

![License](https://img.shields.io/badge/license-MIT-green.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Gradio](https://img.shields.io/badge/Gradio-6.x-ff69b4.svg)
![AgentScope](https://img.shields.io/badge/AgentScope-1.x-orange.svg)

基于 [AgentScope](https://github.com/modelscope/agentscope) 框架与通义千问大模型构建的**可对话、可联网、能记住你的** AI 生活助手。它不仅是个聊天机器人，更是一个具备**工具调用（ReAct）能力**和**跨会话长期记忆**的 Agent。

> 适用场景：日常问答、联网查最新资讯、解析本地文档，并且能随着和你对话次数的增多而越来越"懂你"。

---

## ✨ 核心功能

| 功能 | 说明 |
| --- | --- |
| 💬 多轮对话 | 基于 ReAct Agent，上下文连贯，支持 Web / CLI 双界面 |
| 🧠 跨会话记忆 | 自动记住你的名字、学校、目标等事实，持久化到本地 JSON，下次启动仍记得 |
| 🔧 工具调用（联网搜索） | 注册为 Agent 工具，由模型**自主决定**何时调用 `search_web`，而非关键词匹配 |
| 📄 文档解析（真 RAG） | 上传 TXT / DOCX / PDF 后自动分块建向量库，模型自主检索相关片段 |
| 🌱 持续认知（key_facts） | 每轮对话后抽取你表达的事实/偏好，回灌到 system prompt，越聊越个性化 |
| 🐳 容器化部署 | 内置 Dockerfile，可一键打包为镜像部署 |
| 🌊 流式输出 | 回复以打字机式逐字呈现，体感接近实时流式（前端 incremental rendering） |

---

## 💡 示例对话

> 以下为功能示意（建议运行后替换为真实截图）。

**👤 用户**：帮我查一下今天 A 股大盘行情。
**🤖 Kender**：（自动调用 `search_web`）根据最新检索，今日 A 股三大指数……

**👤 用户**：记一下，我正在准备 Agent 开发岗的面试。
**🤖 Kender**：好的，我已经记住啦。后续聊到相关话题时我会结合这个背景。

**👤 用户**：那你能基于我刚上传的简历 PDF 帮我改下自我介绍吗？
**🤖 Kender**：（结合文档上下文注入）根据你的简历，你的自我介绍可以这样组织……

---

## 🏗️ 架构

```text
            ┌─────────────────────────────────────────┐
            │                  UI 层                    │
            │   Gradio Web (默认 7860)  /  CLI 交互     │
            └───────────────┬─────────────────────────┘
                            │ 用户消息
                            ▼
            ┌─────────────────────────────────────────┐
            │              Agent 层 (ReAct)             │
            │  system prompt (含 key_facts 回灌)         │
            │      ↓ 模型决策                           │
            │  是否调用工具？ ── 是 ──▶ Toolkit 执行     │
            └───────────────┬─────────────────────────┘
                            │            │
                            │            ▼
              ┌─────────────┴──┐   ┌──────────────────┐
              │  记忆系统       │   │   工具层          │
              │ key_facts 抽取 │   │ search_web        │
              │ 持久化 JSON    │   │ read_document     │
              └────────────────┘   │ get_current_date  │
                                   └──────────────────┘
```

**核心数据流**：用户消息 → Agent 拼装（记忆 + 系统提示）→ 模型推理 → 必要时调用工具 → 生成回复 → 后台抽取 key_facts 写回记忆。

---

## 📂 项目结构

```text
kender/
├── main.py              # 入口：--web 启动 Web UI，否则启动 CLI
├── requirements.txt     # 依赖清单
├── Dockerfile           # 容器化构建
├── .dockerignore
├── .env.example         # 环境变量模板（复制为 .env 并填入 key）
├── .gitignore
├── LICENSE            # MIT 开源协议
├── src/
│   ├── agent.py         # ReActAgent 构建 + 工具注册 + 回复逻辑 + key_facts 抽取
│   ├── tools.py         # 工具函数：search_web / read_document / get_current_date
│   ├── memory.py        # 记忆的加载 / 保存 / 提示词拼装
│   ├── ui.py            # Gradio Web 界面
│   └── __init__.py
├── data/
│   └── kender_memory.json  # 运行时自动生成，已被 .gitignore 忽略
└── tests/
    └── test_smoke.py    # 冒烟测试（记忆读写 / 工具返回类型，无需联网）
```

---

## 🚀 快速开始

### 方式一：本地运行

> 📍 **第一步永远是进入正确的目录！** 如果你用 VS Code 打开的是 `kender_projects` 总目录，
> 终端默认就停在那一层，直接跑下面的命令会报"找不到 requirements.txt / main.py"。
> 请先 `cd` 进本项目子目录（其余两个 demo 同理，只改目录名）：
> ```bash
> cd kender_extracted/kender      # ← 主项目：进入本项目根目录
> ```
> ✅ 验证：输入 `dir`（Windows）或 `ls`（Mac/Linux），能看到 `requirements.txt`、`main.py` 再继续。
> （如果本项目已经是单独打开 / 克隆的仓库根目录，可跳过 cd。）

#### 1. 准备 Python 虚拟环境

推荐使用虚拟环境，避免和系统 Python 的依赖打架。下面两种方式任选其一。

**方式 A：用 VS Code 推荐的 WorkBuddy managed venv（推荐，已预装好依赖）**

如果你已经在 WorkBuddy 的默认 venv 里跑通过本项目，直接让 VS Code 指向它：

1. 打开 VS Code，按 `Ctrl+Shift+P`；
2. 输入并选择 `Python: Select Interpreter`；
3. 选择路径：
   ```
   C:\Users\10215\.workbuddy\binaries\python\envs\default\Scripts\python.exe
   ```
   如果列表里没有，选 `Enter interpreter path...`，把上面路径贴进去；
4. 关掉当前终端，按 `` Ctrl+` `` 重新开一个，右下角状态栏应该显示类似 `Python 3.13.x ('default')`。

**方式 B：给 Kender 单独建一个 venv（想自动激活就用这个）**

如果你希望每次打开本项目 VS Code 都自动激活虚拟环境，可以在项目根目录建一个 `.venv`：

```bash
cd D:\kender_projects\kender_extracted\kender
"C:\Users\10215\.workbuddy\binaries\python\versions\3.13.12\python.exe" -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

然后重复"方式 A"的第 1-4 步，选择 `.venv\Scripts\python.exe` 作为解释器。这样每次开新终端 VS Code 会自动运行 `.venv\Scripts\Activate.ps1`。

> 💡 **为什么 VS Code 会自动激活虚拟环境？**
> VS Code 的 Python 扩展会记住"当前工作区/文件夹选中的 Python 解释器"。
> 当解释器路径指向一个虚拟环境里的 `python.exe` 时，每次新建终端，扩展就会自动执行对应目录下的 `Activate.ps1`（Windows）或 `activate`（Mac/Linux），所以你会看到终端提示符前面多了 `(.venv)`。
> 如果你想取消这个行为，按 `Ctrl+Shift+P` → `Python: Select Interpreter` → 选回系统 Python 即可。

#### 2. 安装 / 更新依赖

```bash
# 方式 A：已在 managed venv 中，直接装
pip install -r requirements.txt

# 方式 B：使用项目独立 .venv，先激活再装（VS Code 已自动激活则跳过）
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

#### 3. 配置环境变量

```bash
# Windows (PowerShell)
copy .env.example .env
notepad .env          # 填入你的 DASHSCOPE_API_KEY

# Mac / Linux (bash/zsh)
cp .env.example .env
nano .env             # 填入你的 DASHSCOPE_API_KEY
```

> ⚠️ `.env` 已被 `.gitignore` 忽略，**千万不要手动把它加进 git 提交**。提交前请用 `git status` 确认绿色列表里没有 `.env`。

#### 4. 启动

```bash
python main.py --web     # Web 界面（默认 http://127.0.0.1:7860）
python main.py           # 或命令行交互
```

### 方式二：Docker 运行

```bash
# 构建镜像
docker build -t kender .

# 运行（需先准备好 .env）
docker run --env-file .env -p 7860:7860 kender
```

---

## 🧰 技术栈

- **Agent 框架**：[AgentScope](https://github.com/modelscope/agentscope)（ReActAgent）
- **大模型**：DashScope 通义千问 `qwen-plus`
- **工具系统**：AgentScope Toolkit（`register_tool_function` 注册 `search_web`）
- **Web UI**：Gradio
- **联网搜索**：DuckDuckGo（`ddgs`）
- **文档解析**：python-docx / PyPDF2

---

## 📌 设计说明

**记忆架构（短期 + 长期）**

- **短期记忆**：由 AgentScope 的 ReActAgent 内部维护（同一 agent 实例跨轮累积消息），保证单会话内多轮连贯。
- **长期记忆**：本项目额外持久化 `user_name` 与 `key_facts` 到本地 JSON，重启后仍记得你——这是"跨会话记忆"的核心，也是简历上最该讲清楚的设计点。

**1. 工具调用（真 ReAct，非关键词匹配）**

`search_web` 通过 `toolkit.register_tool_function(search_web)` 注册为 Agent 工具。框架会读取函数的**类型注解 + docstring** 自动生成工具 schema；用户在对话中提到最新资讯、天气、新闻等需求时，Agent 会**自主决定**调用该工具，而非依赖硬编码匹配。

**2. 文档解析 = 真 RAG（分块 + Embedding + FAISS 检索）**

`read_document` 不注册为 Agent 工具——模型无法感知本地文件路径，因此由 Web 界面在用户上传文件时，调用 `src/rag.py` 把文档**分块 → DashScope `text-embedding-v3` 向量化 → 写入 FAISS 本地索引**（持久化到 `data/faiss_index`）。回答阶段，框架通过 `toolkit.register_tool_function(retrieve_document)` 把检索注册为 Agent 工具，模型**自主决定**何时从已上传文档中检索相关片段（与 `search_web` 联网搜索是两套独立能力，按问题性质择一调用）。

> 📌 这是**真正的 RAG**：有分块、有向量库、有「问题 → top-k 片段」的检索环节，而不是把全文塞进 prompt 的上下文注入。同仓库保留 `kender_rag_demo`（LangChain 版）与 `langgraph_rag_demo`（LangGraph 版）作为横向对比参考。

**3. 持续认知（key_facts）**

每轮对话后，系统用**一次 LLM 结构化调用**从对话中抽取两类信息：(1) 用户名字；(2) 事实/偏好（如学校、目标、喜好，每条 ≤30 字）。两者均**只抽取用户直接表达的内容、不推测不编造**，去重后写入 `memory["key_facts"]`。下次启动时，这些事实作为 system prompt 的一部分回灌，使 Agent 能基于历史给出更个性化的回复。

> ⚠️ 注意：这不是模型层面的真正"学习"，而是通过**显式记忆机制**模拟的持续认知能力，面试中表述需实事求是。

**4. 流式输出（前端 incremental rendering）**

Web 界面在拿到模型完整回复后，将文本**逐字（每帧约 3 字）增量渲染**到对话气泡，配合「正在思考」占位，体感上接近实时流式输出，明显改善交互等待感。

> 📌 说明：AgentScope 的 `ReActAgent.reply()` 为聚合返回（内部虽有 `async for` 流式 chunk，但不向外暴露），因此这里采用**前端增量 reveal** 而非模型 token 级 streaming。后端 ReAct 工具调用、长期记忆等能力保持不变，零回归风险。若需真 token 级流式，需改写 Agent 调用层以支持流式 ReAct 循环（见后续计划）。

---

## 🔧 后续计划

- [x] Docker 容器化部署
- [x] 多轮连贯由 AgentScope 内部记忆保证；本项目聚焦长期记忆（key_facts / user_name）持久化
- [x] 流式输出（前端 incremental rendering，打字机式逐字呈现）
- [x] 真 RAG（分块 + DashScope Embedding + FAISS 检索，retrieve_document 注册为 Agent 工具由模型自主调用）
- [ ] 真 token 级 streaming（需改写 AgentScope 调用层以支持流式 ReAct 循环）
- [ ] FastAPI 后端 + 前端分离部署
- [ ] 更完整的单元测试覆盖 agent / tools

## 📑 配套文档

- [`DEPLOYMENT.md`](DEPLOYMENT.md) — 三种部署/演示方案（HuggingFace Spaces 公网部署 / 本地录屏 GIF / Docker），让面试官点开即用。
- [`CODE_WALKTHROUGH.md`](CODE_WALKTHROUGH.md) — 逐模块代码讲解稿与高频面试追问预设，帮助把项目讲清楚。
