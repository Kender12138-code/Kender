"""RAG 端到端测试：索引目录可被环境变量重定向，retrieve_document 能读到内容。

这条链路以前没法测——`index_dir: str = DEFAULT_INDEX_DIR` 把默认值固化在
函数定义里，测试改不了目标目录，只能去动项目真实的 data/faiss_index。
改成运行时解析后，可以用临时目录完整跑一遍「建库 → 检索 → 工具返回」。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.rag as rag  # noqa: E402
from src.tools import retrieve_document  # noqa: E402


def _fake_embed(texts):
    if isinstance(texts, str):
        texts = [texts]
    return [[float(t.count("苹果")), float(t.count("香蕉")), 0.1] for t in texts]


def test_env_var_redirects_index_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KENDER_RAG_INDEX_DIR", str(tmp_path))
    monkeypatch.setattr(rag, "embed", _fake_embed)

    assert rag.index_exists() is False
    rag.build_index("苹果很好吃")
    assert rag.index_exists() is True
    assert rag.chunk_count() == 1
    assert (tmp_path / "index.faiss").is_file()

    hits = rag.retrieve("苹果")
    assert hits and "苹果" in hits[0]


def test_retrieve_document_reads_real_index(tmp_path, monkeypatch):
    """完整链路：建库 → retrieve_document → 返回片段文本。"""
    monkeypatch.setenv("KENDER_RAG_INDEX_DIR", str(tmp_path))
    monkeypatch.setattr(rag, "embed", _fake_embed)
    rag.build_index("公司的年度预算是 100 万元。\n苹果是水果。\n香蕉也是水果。", chunk_size=200)

    resp = asyncio.run(retrieve_document("预算是多少"))
    text = resp.content[0]["text"]
    assert "预算" in text
    assert "文档片段" in text


def test_retrieve_document_without_index_gives_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("KENDER_RAG_INDEX_DIR", str(tmp_path / "empty"))
    resp = asyncio.run(retrieve_document("我的文档里写了什么"))
    text = resp.content[0]["text"]
    assert "还没有上传" in text or "无法检索" in text
