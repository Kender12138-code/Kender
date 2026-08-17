"""Kender 冒烟测试。

目标：在不依赖真实 API Key / 联网的前提下，验证核心模块可被导入、
记忆读写正常、工具函数返回类型正确。

运行（需已安装依赖）：
    pip install -r requirements.txt
    pytest

说明：本测试用 unittest.mock 替换联网依赖（ddgs.DDGS），不发起真实网络请求。
"""
import os
import sys

import pytest

# 让测试能 import 项目根目录的 src 包
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.memory import load_memory, build_memory_prompt  # noqa: E402
from src.tools import get_current_date, search_web  # noqa: E402
from src.rag import split_text  # noqa: E402
from agentscope.tool import ToolResponse  # noqa: E402


def test_load_memory_returns_dict():
    mem = load_memory()
    assert isinstance(mem, dict)
    assert "key_facts" in mem
    assert "chat_history" in mem


def test_build_memory_prompt_no_error():
    prompt = build_memory_prompt(load_memory())
    assert isinstance(prompt, str)


def test_get_current_date_format():
    d = get_current_date()
    assert "今天" in d
    assert "年" in d and "月" in d


def test_search_web_returns_tool_response():
    from unittest.mock import patch

    fake = [{"title": "示例标题", "body": "示例摘要内容", "href": "https://example.com"}]
    with patch("src.tools.DDGS") as MockDDGS:
        inst = MockDDGS.return_value.__enter__.return_value
        inst.text.return_value = fake
        res = search_web("测试查询")
    assert isinstance(res, ToolResponse)
    assert res.content and res.content[0]["text"]
    assert "示例标题" in res.content[0]["text"]


def test_search_web_handles_empty():
    from unittest.mock import patch

    with patch("src.tools.DDGS") as MockDDGS:
        inst = MockDDGS.return_value.__enter__.return_value
        inst.text.return_value = []
        res = search_web("无结果查询")
    assert isinstance(res, ToolResponse)
    assert "没有找到" in res.content[0]["text"]


def test_split_text_basic():
    # 分块是纯本地逻辑，不依赖网络 / API Key，适合冒烟测试
    text = "。".join(f"第{i}句示例内容" for i in range(30))
    chunks = split_text(text, chunk_size=200, chunk_overlap=40)
    assert isinstance(chunks, list) and len(chunks) >= 1
    # 分块不应丢失过多原文（允许少量切分碎片损耗）
    assert sum(len(c) for c in chunks) >= len(text) * 0.8
