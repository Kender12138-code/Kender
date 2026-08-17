from datetime import datetime
from pathlib import Path
from ddgs import DDGS
from agentscope.tool import ToolResponse


def search_web(query: str, max_results: int = 3) -> ToolResponse:
    """使用联网搜索引擎检索用户问题相关的最新信息。

    当用户询问实时资讯、新闻、天气、股价、最新事件，或明确表示
    "今天/最新/热搜/新闻" 等需要外部数据的内容时，应该调用本工具。
    返回检索到的标题、摘要与来源链接，供你综合后回答用户。

    Args:
        query: 用户想要搜索的关键词或问题。
        max_results: 返回的结果条数，默认 3 条。

    Returns:
        ToolResponse: 包装后的搜索结果文本（AgentScope 要求工具函数必须返回
        ToolResponse 对象或生成器）。content 使用字典列表，与 AgentScope
        内部对 TextBlock 的序列化格式保持一致。
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                text = "没有找到相关信息。"
            else:
                output = []
                for i, r in enumerate(results, 1):
                    output.append(f"{i}. {r.get('title', '无标题')}")
                    output.append(f"   {r.get('body', '无摘要')[:200]}...")
                    output.append(f"   来源：{r.get('href', '')}")
                    output.append("")
                text = "\n".join(output)
    except Exception as e:
        text = f"搜索出错：{e}"

    return ToolResponse(content=[{"type": "text", "text": text}])


def read_document(file_path: str) -> str:
    """读取本地文档（.txt / .docx / .pdf）的文本内容，最多返回前 5000 字符。

    本函数由 Web 界面在用户上传文件时调用，把文档内容注入到对话中，
    不注册为 Agent 工具（模型无法感知本地文件路径）。

    Args:
        file_path: 待读取文件的本地路径。

    Returns:
        文档文本内容；若格式不支持或读取失败，返回相应的提示信息。
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    try:
        if ext == ".txt":
            with open(path, "r", encoding="utf-8") as f:
                return f.read()[:5000]
        elif ext == ".docx":
            from docx import Document

            doc = Document(path)
            return "\n".join([p.text for p in doc.paragraphs])[:5000]
        elif ext == ".pdf":
            from PyPDF2 import PdfReader

            reader = PdfReader(path)
            text = "".join([page.extract_text() or "" for page in reader.pages[:20]])
            return text[:5000]
        else:
            return f"暂不支持 {ext} 格式"
    except Exception as e:
        return f"读取失败：{e}"


def get_current_date() -> str:
    """返回当前日期与星期，帮助模型感知"今天"的时间信息。"""
    now = datetime.now()
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    return f"今天是{now.year}年{now.month}月{now.day}日，星期{weekdays[now.weekday()]}。"


def retrieve_document(query: str, k: int = 4) -> ToolResponse:
    """从用户已上传的本地文档中检索与问题最相关的片段（真正的 RAG 检索）。

    当用户的问题涉及之前上传过的文档内容（例如"根据我上传的文档…"、
    "我的简历里写了什么"、"总结一下我上传的文档"、"文档里提到的 XX 是什么"）时，
    应该调用本工具从向量库中检索最相关的片段，再结合片段回答。如果用户尚未上传
    任何文档，本工具会提示其先上传 TXT / DOCX / PDF 文件。

    注意：本工具基于 FAISS 向量检索（分块 + DashScope Embedding），与联网搜索
    search_web 是两套独立能力，请按问题性质选择调用。

    Args:
        query: 要检索的问题或关键词。
        k: 返回的文档片段数量，默认 4 条。

    Returns:
        ToolResponse: 检索到的文档片段（或提示用户先上传文档）。content 使用
        字典列表，与 AgentScope 内部对 TextBlock 的序列化格式保持一致。
    """
    from .rag import retrieve, index_exists

    if not index_exists():
        text = "你还没有上传任何文档，无法检索。请先在界面左侧上传 TXT / DOCX / PDF 文档。"
        return ToolResponse(content=[{"type": "text", "text": text}])

    chunks = retrieve(query, k=k)
    if not chunks:
        text = "在已上传的文档中没有检索到相关内容。"
    else:
        output = [f"【文档片段 {i + 1}】\n{c}\n" for i, c in enumerate(chunks)]
        text = "\n".join(output)

    return ToolResponse(content=[{"type": "text", "text": text}])
