# Kender — 你的专属 AI 生活助手

![License](https://img.shields.io/badge/license-MIT-green.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Gradio](https://img.shields.io/badge/Gradio-6.x-ff69b4.svg)
![AgentScope](https://img.shields.io/badge/AgentScope-1.x-orange.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-服务化-009688.svg)
![MCP](https://img.shields.io/badge/MCP-工具协议-8b5cf6.svg)

基于 [AgentScope](https://github.com/modelscope/agentscope) 框架与通义千问大模型构建的**可对话、可联网、能记住你的** AI 生活助手。

它不只是一个聊天机器人，而是一个具备完整 Agent 工程链路的系统：**ReAct 自主工具调用 → 参数填槽 → 结构化输出校验 → 多 Agent 质量审核 → 跨会话长期记忆**，工具层同时支持**进程内 Function Call** 与**独立进程的 MCP Server** 两种接入方式。

> 适用场景：日常问答、联网查最新资讯、解析本地文档、管理提醒事项，并且能随着和你对话次数的增多而越来越"懂你"。

**🚀 在线体验（腾讯云 CloudBase Run 部署）**：<http://kender-304815-11-1477243187.sh.run.cloudbase.com>
> 访问需要口令（`KENDER_AUTH_USER` / `KENDER_AUTH_PASS`），如需演示请联系作者。

---

## ✨ 核心功能

### 基础能力

| 功能 | 说明 |
| --- | --- |
| 💬 多轮对话 | 基于 ReAct Agent，上下文连贯，支持 Web / CLI / HTTP API 三种入口 |
| 🧠 跨会话记忆 | 主人模式下自动记住你的名字、学校、目标等事实，持久化到本地 JSON，下次启动仍记得 |
| 🔒 多会话隔离 | 每位访客的浏览器会话独立一套 Agent 与记忆，互不串上下文；访客对话默认不落盘 |
| 🔧 工具调用（联网搜索） | 由模型**自主决定**何时调用 `search_web`，而非关键词硬匹配 |
| 🌤️ 天气查询 | `get_weather` 实时天气，缺城市时会主动追问而非瞎猜 |
| 📄 文档解析（真 RAG） | 上传 TXT / DOCX / PDF 后自动分块建向量库，模型自主检索相关片段 |
| 🌱 持续认知（key_facts） | 每轮对话后抽取你表达的事实/偏好，回灌到 system prompt，越聊越个性化 |
| 🌊 流式输出 | 回复以打字机式逐字呈现（前端 incremental rendering） |

### 工程化能力（P0 / P1 阶段新增）

| 功能 | 说明 |
| --- | --- |
| 🎯 **参数填槽（Slot Filling）** | 工具必填参数缺失时，模型**必须先追问**而不是猜默认值。去掉参数默认值 + sys_prompt 双重约束 |
| 🛡️ **Pydantic 结构化校验** | 记忆抽取、质量审核的输出都用 Pydantic 模型强制约束，解析失败自动重试 / 降级 |
| 🔍 **ReAct 轨迹可视化** | Web 界面折叠面板展示每一步「思考 → 行动 → 观察」，工具调用过程不再是黑盒 |
| ⚖️ **Critic 质量审核（多 Agent 协作）** | 生成 → 审核 → 不合格打回重写（最多 2 轮）。审核时把工具返回内容一并喂给 Critic 用于识别编造 |
| 🔌 **MCP 工具接入** | 提醒能力由**独立进程的 MCP Server** 提供，走 streamable-http 协议；接入失败自动降级为进程内工具 |
| ✍️ **Query 改写** | RAG 检索前把问题改写成多条同义语句分别检索后合并去重，提升召回率；小语料自动跳过以省 token |
| 🚀 **FastAPI 服务化** | 独立 HTTP 服务，暴露 `/chat` 与 `/health`，自带 Swagger 文档；初始化放进 lifespan 保证与 MCP 同处一个事件循环 |
| 🐳 容器化部署 | 内置 Dockerfile，可一键打包为镜像部署 |

---

## 💡 示例对话

### 联网搜索

**👤 用户**：帮我查一下今天 A 股大盘行情。
**🤖 Kender**：（自主调用 `search_web`）根据最新检索，今日 A 股三大指数……

### 长期记忆

**👤 用户**：记一下，我正在准备 Agent 开发岗的面试。
**🤖 Kender**：好的，我已经记住啦。后续聊到相关话题时我会结合这个背景。

### 参数填槽（缺参数时追问，不瞎猜）

**👤 用户**：今天天气怎么样？
**🤖 Kender**：你想查哪个城市的天气呢？
**👤 用户**：上海。
**🤖 Kender**：（调用 `get_weather(city="上海")`）上海今天……

### MCP 工具（提醒事项）

**👤 用户**：提醒我明天上午 9 点交实习周报。
**🤖 Kender**：（通过 MCP Server 调用 `add_reminder`）提醒已创建成功。当前共有 1 条提醒：明天上午 9 点 —— 交实习周报。

### 真 RAG 检索

**👤 用户**：我上传的简历里，项目经历写了什么？
**🤖 Kender**：（自主调用 `retrieve_document`，必要时先做 query 改写）根据你的简历，项目经历部分写了……

---

## 🏗️ 架构

```text
┌──────────────────────────────────────────────────────────┐
│                        接入层                             │
│   Gradio Web (7860)  │  CLI  │  FastAPI HTTP (8002)       │
└──────────────┬───────────────────────────────────────────┘
               │ 用户消息
               ▼
┌──────────────────────────────────────────────────────────┐
│                    Agent 层（ReAct）                       │
│   system prompt（含 key_facts 回灌 + 填槽规则）             │
│        ↓ 模型决策                                          │
│   是否调用工具？── 是 ──▶ Toolkit 执行                      │
│        │                                                   │
│        └─ 否（闲聊 / 追问用户）──▶ 直接返回                  │
└──────────────┬───────────────────────────────────────────┘
               │ 生成回答
               ▼
┌──────────────────────────────────────────────────────────┐
│              Critic 层（评审式多 Agent 协作）               │
│   Critic 拿到「用户问题 + 工具返回 + 回答」三方对照          │
│        ├─ PASS ──▶ 返回用户                                │
│        └─ FAIL ──▶ 把批评意见回灌给 Generator 重写（≤2 轮）  │
└──────────────────────────────────────────────────────────┘

   工具层                          记忆层
   ┌────────────────────┐        ┌────────────────────┐
   │ 进程内 Function Call │        │ 短期：ReActAgent    │
   │  · search_web       │        │       内部消息累积   │
   │  · get_weather      │        │ 长期：user_name +   │
   │  · retrieve_document│        │   key_facts → JSON  │
   ├────────────────────┤        └────────────────────┘
   │ MCP Server (8100)   │
   │  · add_reminder     │  ← 独立进程，streamable-http
   │  · list_reminders   │     失败自动降级为进程内工具
   └────────────────────┘
```

**核心数据流**：用户消息 → Agent 拼装（记忆 + 系统提示）→ 模型推理 → 必要时调用工具 → Critic 审核 → 生成回复 → 后台抽取 key_facts 写回记忆。

**端口占用**：Web `7860` ｜ FastAPI `8002` ｜ MCP Server `8100`（可用 `KENDER_MCP_PORT` 覆盖）

---

## 📂 项目结构

```text
kender/
├── main.py                    # 入口：--web 启动 Web UI，否则启动 CLI
│                              #   默认绑 127.0.0.1（本地用），读 GRADIO_SERVER_NAME 环境变量
├── app.py                     # 公网部署入口：默认绑 0.0.0.0:7860（Docker / HuggingFace Spaces 用）
├── server.py                  # FastAPI 服务化：POST /chat、GET /health
├── requirements.txt           # 依赖清单
├── Dockerfile                 # 容器化构建
├── .dockerignore
├── .env.example               # 环境变量模板（复制为 .env 并填入 key）
├── .gitignore
├── LICENSE                    # MIT 开源协议
├── src/
│   ├── agent.py               # ReActAgent 构建 + 工具注册 + Critic 审核 + MCP 接入 + 记忆抽取
│   ├── tools.py               # 工具函数：search_web / get_weather / retrieve_document
│   │                          #            + query 改写 + 降级用 set_reminder
│   ├── memory.py              # 记忆的加载 / 保存 / 提示词拼装
│   ├── rag.py                 # 文档分块 + DashScope Embedding + FAISS 索引与检索
│   ├── ui.py                  # Gradio Web 界面（含 ReAct 轨迹面板）
│   └── __init__.py
├── mcp_server/
│   └── reminder_server.py     # 独立进程 MCP Server：add_reminder / list_reminders
├── data/                      # 运行时自动生成，已被 .gitignore 忽略
│   ├── kender_memory.json     #   长期记忆
│   ├── reminders.json         #   提醒事项
│   ├── faiss_index/           #   RAG 向量库
│   └── mcp_server.log         #   MCP Server 日志
└── tests/
    ├── test_memory.py         # 记忆读写测试
    └── test_smoke.py          # 冒烟测试（工具返回类型等，无需联网）
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

#### 4. 启动（三种入口任选）

```bash
# ① Gradio Web 界面（推荐，带 ReAct 轨迹面板）
python main.py --web          # 默认 http://127.0.0.1:7860

# ② 命令行交互
python main.py

# ③ FastAPI HTTP 服务
python -m uvicorn server:app --port 8002
#    打开 http://127.0.0.1:8002/docs 看 Swagger 文档
```

> 📌 **Web 界面对外开放时**：`main.py` 默认绑定 `127.0.0.1`（只能本机访问）。
> 需要局域网/公网访问时使用 `app.py`（默认 `0.0.0.0`），或给 `main.py` 设置环境变量 `GRADIO_SERVER_NAME=0.0.0.0`。
> Dockerfile 中已默认设置该变量，容器部署无需额外配置。
>
> ⚠️ **公网部署前务必开启访问口令**，否则任何人打开页面都能驱动你的 Agent，消耗的是你自己的 `DASHSCOPE_API_KEY`。
> 项目已内置开关（`src/ui.py` 的 `resolve_auth()`），只需设置两个环境变量：
> ```bash
> # Windows (PowerShell)
> $env:KENDER_AUTH_USER = "kender"
> $env:KENDER_AUTH_PASS = "你的口令"
>
> # Mac / Linux (bash/zsh)
> export KENDER_AUTH_USER=kender
> export KENDER_AUTH_PASS=你的口令
> ```
> 两个变量都设置才启用口令；都不设置则免密，本地开发不受影响。
>
> 💡 **演示专用口令（可选）**：另设 `KENDER_DEMO_USER` / `KENDER_DEMO_PASS` 可启用第二组账号，
> 专门发给面试官或朋友演示用（弱口令即可），与自己的主口令互不影响，随时可在云控制台单独改掉：
> ```bash
> $env:KENDER_DEMO_USER = "demo"
> $env:KENDER_DEMO_PASS = "demo2026"
> ```

### 方式二：Docker 运行

```bash
# 构建镜像
docker build -t kender .

# 运行（需先准备好 .env）
docker run --env-file .env -p 7860:7860 kender
```

---

## 🧰 技术栈

| 层次 | 选型 |
| --- | --- |
| Agent 框架 | [AgentScope](https://github.com/modelscope/agentscope)（ReActAgent + Toolkit） |
| 大模型 | DashScope 通义千问 `qwen-plus` |
| 工具协议 | [MCP](https://modelcontextprotocol.io/)（streamable-http，独立进程） |
| 服务化 | FastAPI + Uvicorn |
| 结构化校验 | Pydantic v2 |
| Web UI | Gradio 6 |
| 联网搜索 | DuckDuckGo（`ddgs`） |
| 文档解析 | python-docx / PyPDF2 |
| 向量检索 | FAISS + DashScope `text-embedding-v3` |

---

## 📌 设计说明

### 1. 记忆架构（短期 + 长期 + 多会话隔离）

- **短期记忆**：由 AgentScope 的 ReActAgent 内部维护（同一 agent 实例跨轮累积消息），保证单会话内多轮连贯。
- **长期记忆**：本项目额外持久化 `user_name` 与 `key_facts` 到本地 JSON，重启后仍记得你——这是"跨会话记忆"的核心，也是简历上最该讲清楚的设计点。
- **抽取链路**：每轮对话后用一次 LLM 调用抽取，输出经 Pydantic `UserInfo` 模型校验；解析失败最多重试 2 次，仍失败则降级跳过，**绝不因为记忆抽取失败就让对话崩掉**。
- **多会话隔离**：公网部署后多个访客会共用同一个服务，直接共享全局 Agent 会导致**对话上下文互相串、记忆文件互相污染**。因此 Web 端把 Agent 运行时（agent/model/memory）放进 Gradio 的 `gr.State`——它天然按浏览器会话隔离；长期记忆的读写由侧边栏「主人模式」开关控制：默认访客会话空白记忆、纯内存、关页面即丢弃（还省掉了访客轮次的事实抽取调用）；勾选主人模式才会以本地记忆文件为底稿创建 Agent 并把新事实写回。因为记忆内容嵌在 `sys_prompt` 里，切换开关或清空对话时直接**重建 Agent**，而不是只改字典。

> ⚠️ 这不是模型层面的真正"学习"，而是通过**显式记忆机制**模拟的持续认知能力，面试中表述需实事求是。

### 2. 工具调用（真 ReAct，非关键词匹配）

`search_web`、`get_weather`、`retrieve_document` 通过 `toolkit.register_tool_function()` 注册为 Agent 工具。框架会读取函数的**类型注解 + docstring** 自动生成工具 schema；模型在推理时**自主决定**是否调用、调用哪个，而非依赖硬编码的关键词匹配。

### 3. 参数填槽（Slot Filling）

**问题**：工具参数给了默认值，模型在用户没说清楚时就会"自作主张"填一个，比如用户问"今天天气怎么样"，模型直接查了北京。

**解法**（双管齐下，缺一不可）：

1. **代码层**：去掉工具函数的参数默认值（`get_weather(city: str)`，不给 `city="北京"`）——没有默认值，模型就没法偷懒。
2. **Prompt 层**：在 system prompt 里写死填槽规则——"禁止猜测、禁止使用默认值、禁止跳过该参数，必须先向用户追问补全"。

```python
# src/agent.py 中的 sys_prompt 片段
【填槽规则】调用任何工具前，先检查必需参数是否齐全。
如果用户没有提供某个必需参数（例如没说查哪个城市、
没说提醒什么内容或什么时间），禁止猜测、禁止使用默认值、
禁止跳过该参数，必须先向用户追问补全，等用户回答后再调用工具。
```

> 💡 面试点：这个能力同时被 Critic 保护——Critic 的 prompt 里明确写了"助手正在追问必要信息属于合格行为"，否则 Critic 会把正常的追问误判为"答非所问"。

### 4. 文档解析 = 真 RAG（分块 + Embedding + FAISS 检索）

`read_document` **不**注册为 Agent 工具——模型无法感知本地文件路径。因此由 Web 界面在用户上传文件时，调用 `src/rag.py` 把文档**分块（500 字 / 80 字 overlap，中文友好按行聚合）→ DashScope `text-embedding-v3` 向量化 → 写入 FAISS 本地索引**（持久化到 `data/faiss_index`）。

回答阶段，`retrieve_document` 注册为 Agent 工具，模型**自主决定**何时从已上传文档中检索相关片段（与 `search_web` 联网搜索是两套独立能力，按问题性质择一调用）。

> 📌 这是**真正的 RAG**：有分块、有向量库、有「问题 → top-k 片段」的检索环节，而不是把全文塞进 prompt 的上下文注入。同仓库保留 `kender_rag_demo`（LangChain 版）与 `langgraph_rag_demo`（LangGraph 版）作为横向对比参考。

### 5. Query 改写（检索增强）

单一问法容易漏召回。检索前先用模型把问题改写成 3 条**表述不同但语义相同**的语句，分别检索后合并去重（按片段前 80 字符判重）。

**成本权衡**：语料规模小于 8 个片段时跳过改写——小语料下原始问题通常已经能命中，改写只会白白多花一次 LLM 调用。

```python
# src/tools.py
total = chunk_count()
if total >= REWRITE_MIN_CHUNKS:      # REWRITE_MIN_CHUNKS = 8
    queries = [query] + [q for q in await expand_query(query) if q != query]
else:
    queries = [query]
```

改写失败（JSON 解析异常等）自动降级为 `[原问题]`——**优化不能拖垮主链路**。

### 6. Critic 质量审核（评审式多 Agent 协作）

单靠 prompt 约束不住模型，就再加一道**后置检查点**：一个 Agent 生成（Generator），另一个审核（Critic）。

```text
第 1 次生成 → Critic 审核
    ├─ PASS → 返回用户
    └─ FAIL → 把批评意见回灌给 Generator 重写（最多 2 轮）
```

**三个关键设计**：

1. **Critic 必须看到工具返回内容**。只看最终回答，Critic 无从判断"有没有编造"；把 ReAct 轨迹（Observation）一并喂给它，才能识破数据捏造。
2. **输出用 Pydantic 强制结构化**（`CriticVerdict: {passed: bool, reason: str}`）。不让模型絮絮叨叨，省 token 也省解析麻烦。
3. **两个省 token / 保稳定的优化**：
   - 本轮没调用工具时直接跳过审核（闲聊和追问没有审核价值）
   - 审核本身出异常时**默认放行**——检查点是"兜底"不是"拦路虎"

> 📌 诚实说明：Critic 与 Generator 复用同一个 `DashScopeChatModel` 实例（都是 `qwen-plus`），只是 prompt 角色不同。它是**评审式的双 Agent 分工**，不是两个独立部署的模型服务。

### 7. MCP 工具接入（协议层）

提醒能力默认由**独立进程的 MCP Server**（`mcp_server/reminder_server.py`）提供，主程序通过 MCP 协议调用，而不是直接 import。

**为什么绕这一层？这正是 MCP 的意义**：

| | 能被调用的范围 |
| --- | --- |
| 进程内函数（Function Call） | 只能被本进程、本语言的程序调用 |
| MCP Server（协议层） | 任何支持 MCP 的客户端都能调用，可换语言实现、可独立部署、可给别人复用 |

> 💡 **面试关键区分**：Function Call 是**实现层**（模型自主决策 + 结构化调用），MCP 是**协议层**（定义工具怎么被发现和接入）。二者不是一回事，混为一谈会被扣分。

**两个传输方式的选择**：

- `stdio`（默认）：CLI 单任务场景可用
- `streamable-http`（`--http 8100`）：**Web 服务必须用**

为什么 Web 不能用 stdio？因为 stdio 客户端会在调用方所在的 asyncio task 里创建 anyio cancel scope；Web 服务里「建立连接」在启动阶段（lifespan）、「调用工具」在请求处理阶段，两者是不同 task，anyio 会直接抛：

```
RuntimeError: Attempted to exit cancel scope in a different task
              than it was entered in
```

**降级设计**：MCP 是"增强"不是"依赖"。连接失败时自动把进程内的 `set_reminder` 补注册回来，提醒能力不消失，整个 Agent 不受影响。可用 `KENDER_ENABLE_MCP=0` 主动关闭。

### 8. ReAct 轨迹可视化

Web 界面底部有折叠面板「🔍 推理轨迹与质量审核（思考 → 行动 → 观察）」，展示每一轮：

- 模型调用了哪些工具、传了什么参数
- 工具返回了什么（Observation）
- Critic 的审核结论（PASS/FAIL + 原因 + 第几轮通过）

**为什么值得做**：工具调用过程本来是黑盒，模型"想了什么、查了什么、为什么这么答"全看不见。可视化之后，调试效率大幅提升，演示时也能直观证明"这是真 ReAct，不是关键词匹配"。

### 9. FastAPI 服务化

`server.py` 把 Kender 从"终端对话"变成"HTTP 对话"：

| 接口 | 说明 |
| --- | --- |
| `POST /chat` | 发一句话，返回 `{reply, trace, review:{passed, reason, rounds}}` |
| `GET /health` | 健康检查，方便运维探活 |

启动：`python -m uvicorn server:app --port 8002`，Swagger 文档在 `/docs`。

**关键设计：初始化放进 `lifespan`**。原来 memory / agent 写在模块顶层，接入 MCP 后不行了——MCP 客户端会绑定到一个具体的事件循环上，而模块顶层还没有循环；老版本在每个请求里 `asyncio.run()` 新建循环，会导致「A 循环里连接、B 循环里调用」必然报错。放进 lifespan 后，初始化和请求都跑在 uvicorn 的同一个循环里。

### 10. 流式输出（前端 incremental rendering）

Web 界面在拿到模型完整回复后，将文本**逐字（每帧约 3 字）增量渲染**到对话气泡，配合「正在思考」占位，体感上接近实时流式输出。

> 📌 说明：AgentScope 的 `ReActAgent.reply()` 为聚合返回（内部虽有 `async for` 流式 chunk，但不向外暴露），因此这里采用**前端增量 reveal** 而非模型 token 级 streaming。若需真 token 级流式，需改写 Agent 调用层以支持流式 ReAct 循环（见后续计划）。

---

## ⚠️ 已知限制与边界

诚实列出当前版本的取舍，这也是面试中该主动说清的部分：

| 项目 | 现状 |
| --- | --- |
| 流式输出 | 前端 reveal，**不是**模型 token 级 streaming |
| Critic 独立性 | 与 Generator 复用同一模型实例，靠 prompt 切换角色，不是独立部署的第二个模型服务 |
| MCP Server | 本地子进程 + 本机 HTTP，**不是**远程服务；主进程退出后需自行管理 |
| 多 Agent 协作层级 | 当前是**评审式**（Generator + Critic），尚未做到上下级式（Planner + 多 Worker 分工） |
| 长期记忆 | 全量 key_facts 回灌 system prompt，未做向量检索式的记忆召回，规模变大后需优化 |
| RAG 检索 | 纯向量检索，未做混合检索（BM25 + 向量）与重排序（rerank） |
| CLI 模式 | 不带 Critic 审核（调用 `get_reply`），只有 Web 与 API 走 `get_reply_with_review` |
| 并发 | 单实例，未做请求队列；但 Web 界面已实现**多会话隔离**（每个浏览器会话独立 Agent 与记忆，访客不落盘），仅 FastAPI 接口仍共享全局 Agent |

---

## 🔧 后续计划

- [x] Docker 容器化部署
- [x] 长期记忆（key_facts / user_name）持久化
- [x] 流式输出（前端 incremental rendering）
- [x] 真 RAG（分块 + DashScope Embedding + FAISS 检索）
- [x] 参数填槽（Slot Filling）
- [x] Pydantic 结构化输出校验
- [x] ReAct 轨迹可视化
- [x] Critic 质量审核（评审式多 Agent 协作）
- [x] MCP 工具接入（独立进程 + streamable-http + 降级）
- [x] Query 改写（规模阈值控制成本）
- [x] FastAPI 服务化（lifespan 初始化 + /chat + /health）
- [ ] 真 token 级 streaming（需改写 AgentScope 调用层以支持流式 ReAct 循环）
- [ ] 上下级式多 Agent 协作（Planner + 多 Worker 分工，AgentScope `MsgHub` / `sequential_pipeline`）
- [ ] RAG 混合检索（BM25 + 向量）与重排序（rerank）
- [ ] 长期记忆的向量化召回（当前全量回灌，规模变大后需优化）
- [ ] 更完整的单元测试覆盖 agent / tools

---

## 📑 配套文档

- [`DEPLOYMENT.md`](DEPLOYMENT.md) — 部署/演示方案，让面试官点开即用。
- [`CODE_WALKTHROUGH.md`](CODE_WALKTHROUGH.md) — 逐模块代码讲解稿与高频面试追问预设，帮助把项目讲清楚。
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — 开发约定。

---

## 🌾 农产品电商智能建站 Agent（新增）

基于 Kender 的 Agent 能力做的一个**垂直场景 demo**：农民用自然语言描述"卖什么、怎么卖、多少钱"，AI 自动生成一个类似淘宝店铺的销售页面，支持多轮对话持续调整。

### 适合在面试里讲的点

- **真 ReAct 工具调用**：LLM 自主决定调用 `build_farm_shop` 建店还是 `update_farm_shop` 改店，轨迹面板可见"思考 → 行动 → 观察"。
- **零回归接入**：新增 `src/farm_shop.py` + `farm_shop_app.py` + `farm_react_app.py`，**没有改动 Kender 原有文件**。
- **左右分栏交互**：左侧聊天，右侧实时生成店铺页面，体验直观。

### 运行方式

```bash
cd D:\kender_projects\kender_extracted\kender

# 推荐：ReActAgent 版（带推理轨迹，面试展示效果更好）
python farm_react_app.py
# 浏览器打开 http://127.0.0.1:7862

# 或者：简单直接版
python farm_shop_app.py
# 浏览器打开 http://127.0.0.1:7861
```

### 示例对话

```text
用户：我家有50斤西红柿，3块钱一斤，还有30斤黄瓜，2块钱一斤，店名叫李叔菜园
AI  → 调用 build_farm_shop
AI  → 李叔菜园建好啦，展示西红柿和黄瓜

用户：再加20个土鸡蛋，2块钱一个，换个清新风格
AI  → 调用 update_farm_shop
AI  → 已加上土鸡蛋，风格换成清新
```

### 文件说明

| 文件 | 作用 |
| --- | --- |
| `src/farm_shop.py` | 核心逻辑：从自然语言提取/更新店铺信息、渲染 HTML 页面 |
| `farm_shop_app.py` | 简单直接版入口：左侧聊天 + 右侧预览 |
| `farm_react_app.py` | **ReActAgent 版入口**：复用 Kender 的 ReActAgent，LLM 自主调用工具 |
| `data/shop_react_preview_demo.html` | 示例生成的店铺页面，可直接用浏览器打开 |

### 已知限制

- **右侧预览**：为避免 Gradio 6 `gr.HTML` 对 `position:fixed` 的渲染 bug（fixed 元素会吞掉文档流主体），预览面板里的店铺页采用内联样式、文档流定位；点击商品卡片的「加入购物车」、底部的「购物车」在预览区内可直接交互。
- **完整交互版**：底部提供「在新窗口打开完整交互版」链接，会打开一个独立 HTML 页面，里面购物车/结算/模拟微信支付二维码是 `position:fixed` 悬浮交互，体验最接近真实淘宝店铺。
- 微信支付为模拟二维码，真实收款需接入微信支付商户号。
- 当前为单用户 demo，`_current_shop` 是全局状态；多人并发使用需按 session 隔离或落库。
