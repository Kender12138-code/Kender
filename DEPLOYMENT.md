# Kender 部署与演示方案

目标：让面试官**点开就能用**，或**看一段录屏就懂**。三种方案按"成本/效果"排序，任选其一即可，推荐方案一。

| 方案 | 效果 | 成本 | 适合 |
| --- | --- | --- | --- |
| ① HuggingFace Spaces | 公网链接，面试官点开即用 | 免费，10 分钟 | **首选**，简历直接贴链接 |
| ② 本地录屏转 GIF | README 里嵌动图 | 免费，需本机录 | 不想暴露 API Key / 无网络环境 |
| ③ Docker 部署 | 自己服务器上跑 | 需一台云服务器 | 有服务器、想完全自控 |

> 无论哪种方案，都需要一个可用的 `DASHSCOPE_API_KEY`（通义千问）。

---

## 方案一：HuggingFace Spaces 免费公网部署（推荐）

HuggingFace Spaces 原生支持 Gradio，本项目已准备好 `app.py` 入口，部署几乎零配置。

### 前置条件
1. 注册 [HuggingFace](https://huggingface.co) 账号（免费）。
2. 准备好你的 `DASHSCOPE_API_KEY`。

### 步骤

**1. 新建 Space**
- 进入 [huggingface.co/spaces](https://huggingface.co/spaces) → 点 **Create new Space**。
- 填写名字（如 `kender`）。
- **SDK 选 `Gradio`**，**硬件选 `Free`**（或 `CPU basic`，免费）。
- 可见性选 `Public`（否则面试官打不开）。
- 点 Create。

**2. 上传以下文件**（直接拖拽，保持目录结构）

```text
kender/                  ← 仓库根目录
├── app.py               # 已提供，Spaces 会自动运行它
├── main.py
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── src/
│   ├── __init__.py
│   ├── agent.py
│   ├── tools.py
│   ├── memory.py
│   └── ui.py
└── data/               # 空目录也可，运行时自动生成记忆文件
```

> 注意：`.env` **不要上传**（含密钥）。仓库里只有 `.env.example` 即可。

**3. 配置 API Key（关键）**
- 在 Space 页面 → **Settings** → **Repository secrets** → **New secret**。
- Name 填 `DASHSCOPE_API_KEY`，Value 填你的真实 Key。
- 保存。代码里 `os.getenv("DASHSCOPE_API_KEY")` 会自动读到它（无需 .env 文件）。

**4. 等待构建**
- Spaces 会自动 `pip install -r requirements.txt` 并运行 `app.py`。
- 顶部状态从 `Building` 变 `Running` 后，点开链接即可对话。
- 把该链接放进简历和 GitHub README。

### 注意事项
- **记忆不持久**：Spaces 容器是无状态的，`data/kender_memory.json` 重启会清空，属正常现象，演示无影响。
- **免费额度会休眠**：Free 硬件长时间无人访问会 sleep，面试官首次打开可能要等十几秒唤醒，属正常。
- 若构建失败，看 Space 的 **Logs** 标签排查（多半是依赖版本或 Key 没配）。

---

## 方案二：本地录屏转 GIF 嵌入 README

不想暴露 Key、或网络受限时，录一段本地运行的 GIF 放进 README，效果同样直观。

### 录制内容脚本（建议 60 秒内，5 个镜头）
1. 打开 `http://127.0.0.1:7860`，看到 Kender 界面。
2. 输入「你是谁？」→ 展示基础对话。
3. 勾选「优先联网搜索」，问「今天有什么科技新闻？」→ 展示 `search_web` 工具调用。
4. 上传一个 `.txt` 文档，问「这份文档讲了什么？」→ 展示文档解析。
5. 输入「我叫杨恺，在 70 迈实习」→ 再问「我刚才说我叫什么？」→ 展示记忆/key_facts。

### 录制工具（任选）
- **ScreenToGif**（Windows，免费，边录边剪，直接导出 gif）— 最推荐。
- **OBS Studio**（免费，录屏后需转格式）。
- **Xbox Game Bar**（Win+G 自带，仅录屏，转 gif 需额外工具）。

### 嵌入 README
把导出的 `demo.gif` 放进项目根目录，在 README 顶部加一行：

```markdown
![Kender 演示](demo.gif)
```

---

## 方案三：Docker 部署（本地或云服务器）

项目已内置 `Dockerfile`（基于 `python:3.11-slim`，已设 `GRADIO_SERVER_NAME=0.0.0.0` + 暴露 7860）。

### 本地跑
```bash
cd kender_extracted/kender      # 进入项目根目录
docker build -t kender .
docker run --env-file .env -p 7860:7860 kender
# 浏览器打开 http://localhost:7860
```

### 部署到云服务器
1. 买一台轻量云服务器（阿里云/腾讯云，约 ¥50/月起步，选有公网 IP 的）。
2. 装好 Docker，把项目传上去，`docker build` + `docker run -d -p 7860:7860 --env-file .env kender`。
3. 服务器安全组**放行 7860 端口**。
4. 浏览器访问 `http://<服务器公网IP>:7860`。

> 进阶：用 Nginx 反代 + 域名 + HTTPS，体验更专业，但新人可先跳过。

---

## 推荐组合

**简历项目最稳的组合：方案一（HF Spaces 公网链接）+ 方案二（README 内嵌 GIF）。**
- HF Spaces 给面试官"点开即用"的体验；
- README 的 GIF 保证即使 Spaces 休眠，也能一眼看懂能力。

两个都不需要你额外花钱，先把这两个做了，Kender 就从"只能看代码"变成"能直接体验"，面试说服力翻倍。
