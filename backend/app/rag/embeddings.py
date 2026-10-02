# -*- coding: utf-8 -*-
"""
向量化服务（Embedding）（角色2：郝英博）

对应任务 2.3：使用 Embedding 模型将知识片段向量化

双策略：
  1. OpenAI 兼容 Embedding API（配置 EMBEDDING_API_KEY 时，如硅基流动 bge-m3）
  2. 本地字符 n-gram 稀疏向量（零依赖兜底，中文检索效果良好）

向量表示统一约定：
  - 稠密向量：list[float]（来自 API）
  - 稀疏向量：dict{token: weight}（本地 n-gram，JSON 可序列化，存储省空间）
  两者的相似度计算都由 vector_store 适配
"""
import math
import re
from collections import Counter

import httpx

from app import config


# ============================================================
# 本地字符 n-gram 向量（零依赖）
# ============================================================
def _tokenize_zh(text: str) -> list:
    """中文分词（轻量级）：提取汉字 bigram + 单字 + 英文单词"""
    text = re.sub(r"\s+", " ", text)
    tokens = []
    # 英文/数字单词
    for w in re.findall(r"[A-Za-z0-9]+", text.lower()):
        tokens.append(w)
    # 汉字序列
    for seq in re.findall(r"[\u4e00-\u9fa5]+", text):
        if len(seq) == 1:
            tokens.append(seq)
        else:
            tokens.extend(seq[i:i + 2] for i in range(len(seq) - 1))
    return tokens


def local_sparse_vector(text: str) -> dict:
    """
    本地稀疏向量：字符 n-gram 词频 + L2 归一化
    返回 {token: weight}
    """
    tokens = _tokenize_zh(text)
    if not tokens:
        return {}
    counts = Counter(tokens)
    # 加权：bigram 权重 1.0，单词权重 0.8
    weights = {}
    for tok, c in counts.items():
        w = 1.0 if len(tok) > 1 else 0.8
        weights[tok] = c * w
    # L2 归一化
    norm = math.sqrt(sum(v * v for v in weights.values()))
    if norm > 0:
        weights = {k: v / norm for k, v in weights.items()}
    return weights


# ============================================================
# 稠密向量：OpenAI 兼容 Embedding API（如硅基流动 bge-m3）
# ============================================================
# 【性能】共享连接池：TLS 握手只建一次，后续检索请求直接复用
_shared_client: httpx.AsyncClient = None


def _http() -> httpx.AsyncClient:
    global _shared_client
    c = _shared_client
    if c is None or c.is_closed:
        c = httpx.AsyncClient(timeout=30, trust_env=False,
                              limits=httpx.Limits(max_keepalive_connections=2,
                                                  keepalive_expiry=300))
        _shared_client = c
    return c


async def embed_via_api(texts: list) -> list:
    """OpenAI 兼容 Embedding API（如硅基流动 /bge-m3）"""
    url = f"{config.EMBEDDING_BASE_URL.rstrip('/')}/embeddings"
    headers = {"Authorization": f"Bearer {config.EMBEDDING_API_KEY}"}
    r = await _http().post(url, json={
        "model": config.EMBEDDING_MODEL,
        "input": texts,
    }, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"Embedding API 调用失败：HTTP {r.status_code}")
    data = sorted(r.json()["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in data]


# ============================================================
# 统一入口
# ============================================================
_current_mode = None  # 缓存探测结果：api / local


def _decide_mode() -> str:
    """决定向量化模式（启动后缓存）"""
    global _current_mode
    if _current_mode:
        return _current_mode

    p = config.EMBEDDING_PROVIDER
    if p == "api" and config.EMBEDDING_API_KEY:
        _current_mode = "api"
    elif p == "local":
        _current_mode = "local"
    elif p == "auto":
        # 外部 API Key 就绪 → 用稠密向量；否则用本地 n-gram（零依赖兜底）
        _current_mode = "api" if config.EMBEDDING_API_KEY else "local"
    else:
        _current_mode = "local"
    return _current_mode


async def detect_embedding_mode():
    """异步探测向量化模式（服务启动时调用一次）"""
    global _current_mode
    if config.EMBEDDING_PROVIDER != "auto":
        _decide_mode()
        return
    _current_mode = "api" if config.EMBEDDING_API_KEY else "local"


def embedding_mode() -> str:
    """当前向量化模式"""
    return _decide_mode()


async def embed_texts(texts: list) -> list:
    """
    批量向量化统一入口
    返回向量列表（稠密 list[float] 或稀疏 dict）
    失败时自动降级本地稀疏向量
    """
    if not texts:
        return []
    mode = _decide_mode()
    try:
        if mode == "api":
            return await embed_via_api(texts)
    except Exception:
        pass  # 失败降级本地
    return [local_sparse_vector(t) for t in texts]


async def embed_query(text: str):
    """单条查询向量化"""
    vecs = await embed_texts([text])
    return vecs[0] if vecs else {}
