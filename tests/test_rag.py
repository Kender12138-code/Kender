"""RAG 模块的离线测试。

不联网：embedding 用假实现（按关键词计数生成向量），这样分块、建索引、
FAISS 检索、阈值判断这几步都能真实跑一遍，只是语义是假的。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.rag as rag  # noqa: E402


def _fake_embed(texts):
    """把文本映射成 3 维向量：苹果数、香蕉数、常数项。"""
    if isinstance(texts, str):
        texts = [texts]
    return [
        [float(t.count("苹果")), float(t.count("香蕉")), 0.1] for t in texts
    ]


@pytest.fixture()
def fake_embedding(monkeypatch):
    monkeypatch.setattr(rag, "embed", _fake_embed)


# ---------------- 分块 ----------------

def test_split_empty_returns_empty_list():
    assert rag.split_text("") == []
    assert rag.split_text("   \n  ") == []


def test_split_keeps_short_text_whole():
    text = "第一句话。第二句话。"
    assert rag.split_text(text, chunk_size=100) == [text]


def test_split_merges_short_paragraphs():
    text = "段落一\n段落二\n段落三"
    chunks = rag.split_text(text, chunk_size=100)
    assert len(chunks) == 1
    assert "段落一" in chunks[0] and "段落三" in chunks[0]


def test_split_long_text_into_multiple_chunks():
    text = "甲" * 1200
    chunks = rag.split_text(text, chunk_size=500, chunk_overlap=80)
    assert len(chunks) >= 3
    assert all(len(c) <= 500 for c in chunks)


def test_split_overlap_preserves_context():
    """带 overlap 时，相邻块要有重叠区域，否则跨块的句子会被切断。"""
    text = "".join(str(i % 10) for i in range(1000))
    chunks = rag.split_text(text, chunk_size=300, chunk_overlap=100)
    assert len(chunks) >= 2
    assert chunks[0][-100:] == chunks[1][:100]


def test_split_does_not_lose_too_much_text():
    text = "。".join(f"第{i}句" for i in range(200))
    chunks = rag.split_text(text, chunk_size=200, chunk_overlap=0)
    assert sum(len(c) for c in chunks) >= len(text) * 0.9


# ---------------- 建索引与检索 ----------------

def test_build_index_creates_files(tmp_path, fake_embedding):
    n = rag.build_index("苹果很好吃\n香蕉也不错", index_dir=str(tmp_path))
    assert n == 1
    assert (tmp_path / "index.faiss").is_file()
    assert (tmp_path / "chunks.json").is_file()
    saved = json.loads((tmp_path / "chunks.json").read_text(encoding="utf-8"))
    assert len(saved) == n


def test_build_index_rejects_empty_document(tmp_path, fake_embedding):
    with pytest.raises(ValueError):
        rag.build_index("   ", index_dir=str(tmp_path))


def test_retrieve_returns_none_without_index(tmp_path):
    assert rag.retrieve("苹果", index_dir=str(tmp_path)) is None


def test_retrieve_ranks_relevant_chunk_first(tmp_path, fake_embedding):
    doc = "这里一直在讲苹果。\n这里一直在讲香蕉。\n这里讲的是别的。"
    rag.build_index(doc, index_dir=str(tmp_path), chunk_size=100)
    hits = rag.retrieve("苹果", k=2, index_dir=str(tmp_path))
    assert hits, "应当能召回内容"
    assert "苹果" in hits[0]


def test_retrieve_k_larger_than_chunks(tmp_path, fake_embedding):
    """k 超过实际块数时不能报错，也不能返回 None 占位。"""
    rag.build_index("只有一段话", index_dir=str(tmp_path))
    hits = rag.retrieve("任意", k=10, index_dir=str(tmp_path))
    assert len(hits) == 1
    assert all(isinstance(h, str) for h in hits)


def test_index_exists_requires_both_files(tmp_path):
    assert rag.index_exists(str(tmp_path)) is False
    (tmp_path / "index.faiss").write_bytes(b"")
    assert rag.index_exists(str(tmp_path)) is False  # 只有一个是无效的
    (tmp_path / "chunks.json").write_text("[]", encoding="utf-8")
    assert rag.index_exists(str(tmp_path)) is True


def test_chunk_count_reads_chunks_json(tmp_path):
    (tmp_path / "index.faiss").write_bytes(b"")
    (tmp_path / "chunks.json").write_text(json.dumps(["a", "b", "c"]), encoding="utf-8")
    assert rag.chunk_count(str(tmp_path)) == 3


def test_chunk_count_returns_zero_on_broken_json(tmp_path):
    (tmp_path / "index.faiss").write_bytes(b"")
    (tmp_path / "chunks.json").write_text("{坏掉的 json", encoding="utf-8")
    assert rag.chunk_count(str(tmp_path)) == 0
