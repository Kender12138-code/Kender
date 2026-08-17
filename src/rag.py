"""
Kender 轻量 RAG 模块（自实现，不依赖 langchain / langgraph）。

真正的 RAG 流程：文档分块 → DashScope Embedding 向量化 → FAISS 检索 top-k。
- 分块：中文友好的递归切分（先按段落/句子聚合，超长再按字符滑动窗口）。
- 向量化：DashScope `text-embedding-v3`，走 OpenAI 兼容接口，复用现有 DASHSCOPE_API_KEY。
- 检索：FAISS IndexFlatL2（精确最近邻），索引持久化到本地 data/faiss_index。

设计取舍：自己实现而非调 langchain 黑盒，好处是依赖最小、逻辑透明、面试能讲清
「分块 / 向量化 / 检索」每一步；代价是不如 langchain 的 FAISS 封装省事，但代码量很小。
"""
import os
import json
from pathlib import Path

import faiss
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = "text-embedding-v3"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_INDEX_DIR = "data/faiss_index"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


def _get_client() -> OpenAI:
    """创建 DashScope OpenAI 兼容客户端（Embedding 与 Chat 共用 base_url）。"""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("请先设置 DASHSCOPE_API_KEY 环境变量（RAG 向量化需要 Embedding 接口）")
    return OpenAI(api_key=api_key, base_url=DASHSCOPE_BASE_URL)


def embed(texts):
    """批量向量化文本，返回 list[list[float]]（与输入顺序一致）。

    Args:
        texts: 待向量化的字符串列表（一或多个）。
    """
    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return []
    client = _get_client()
    # DashScope Embedding 单次输入有批量上限，按固定 batch 分批发请求，
    # 既避免触发接口限制，也保证输出顺序与输入一致。
    batch_size = 16
    out = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        out.extend(item.embedding for item in resp.data)
    return out


def split_text(text: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP):
    """中文友好的文档分块。

    策略：
      1. 先按换行切成「段」，把短段合并到接近 chunk_size（避免把一句话切碎得太碎）；
      2. 若单段仍超过 chunk_size，再按字符做带 overlap 的滑动窗口切分。
    返回非空文本块列表。
    """
    text = (text or "").strip()
    if not text:
        return []

    # 1) 按行聚合为「自然段」
    raw_paras = [p for p in text.split("\n") if p.strip()]
    merged = []
    buf = ""
    for p in raw_paras:
        if len(buf) + len(p) <= chunk_size:
            buf = f"{buf}\n{p}" if buf else p
        else:
            if buf:
                merged.append(buf)
            buf = p
    if buf:
        merged.append(buf)

    # 2) 合并后的段若仍超长，按字符滑动窗口切分（带 overlap）
    chunks = []
    for seg in merged:
        if len(seg) <= chunk_size:
            chunks.append(seg)
        else:
            step = max(1, chunk_size - chunk_overlap)
            for i in range(0, len(seg), step):
                piece = seg[i : i + chunk_size]
                if piece.strip():
                    chunks.append(piece)
    return chunks


def build_index(text: str, index_dir: str = DEFAULT_INDEX_DIR,
                chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> int:
    """用文档全文构建 FAISS 向量库并持久化。

    Args:
        text: 文档纯文本（由 read_document 加载得到）。
        index_dir: 索引保存目录。
    Returns:
        分块数量。
    """
    chunks = split_text(text, chunk_size, chunk_overlap)
    if not chunks:
        raise ValueError("文档内容为空或无法分块，请检查文件。")

    vectors = embed(chunks)
    dim = len(vectors[0])
    index = faiss.IndexFlatL2(dim)
    index.add(np.array(vectors, dtype="float32"))

    os.makedirs(index_dir, exist_ok=True)
    faiss.write_index(index, os.path.join(index_dir, "index.faiss"))
    # 保存「向量 id → 文本块」的映射（FAISS 只存向量，文本需自己维护）
    with open(os.path.join(index_dir, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)
    return len(chunks)


def index_exists(index_dir: str = DEFAULT_INDEX_DIR) -> bool:
    """判断本地是否已有构建好的向量库（两个文件都在才算有效）。"""
    base = Path(index_dir)
    return (base / "index.faiss").exists() and (base / "chunks.json").exists()


def retrieve(query: str, k: int = 4, index_dir: str = DEFAULT_INDEX_DIR):
    """从已构建的向量库中检索与 query 最相关的 k 个文本块。

    Args:
        query: 检索问题或关键词。
        k: 返回片段数。
    Returns:
        相关文本块列表（按相似度升序）；索引不存在返回 None。
    """
    if not index_exists(index_dir):
        return None

    index = faiss.read_index(os.path.join(index_dir, "index.faiss"))
    with open(os.path.join(index_dir, "chunks.json"), encoding="utf-8") as f:
        chunks = json.load(f)

    q_vec = np.array(embed([query])[0], dtype="float32").reshape(1, -1)
    # D 为 L2 距离（越小越相似），I 为对应的向量 id
    _distances, ids = index.search(q_vec, k)
    results = []
    for i in ids[0]:
        if 0 <= i < len(chunks):
            results.append(chunks[i])
    return results
