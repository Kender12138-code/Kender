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
