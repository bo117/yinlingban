# -*- coding: utf-8 -*-
"""
知识处理流水线（角色2：郝英博）

对应职责 3.2.3：实现知识文档的
  加载 → 清洗 → 分段 → 向量化 → 存储 完整流水线
  支持批量导入和增量更新

知识文件格式约定（给角色3的协作规范）：
  data/health_knowledge/ 目录下放 .md 或 .txt 文件，每个文件头部写元信息：

      标题：高血压老人日常注意事项
      分类：慢病管理
      来源：国家卫健委《老年健康核心信息》

      正文第一段……
      正文第二段……

  - 头部三行"标题/分类/来源"为元信息（缺省时用文件名/未分类/知识库）
  - 正文按空行分段，段落聚合为约500字的片段，相邻片段重叠50字
"""
import re
from pathlib import Path

from app import config
from app.rag.embeddings import embed_texts
from app.rag.vector_store import vector_store


# ============================================================
# 1. 加载与解析
# ============================================================
def _parse_meta(lines: list) -> tuple:
    """解析文件头部元信息，返回 (meta_dict, 正文起始行号)"""
    meta = {}
    idx = 0
    for i, line in enumerate(lines[:10]):
        m = re.match(r"^(标题|分类|来源)[：:]\s*(.+)$", line.strip())
        if m:
            meta[m.group(1)] = m.group(2).strip()
            idx = i + 1
        elif line.strip() == "" and idx == i:
            continue
        elif not line.strip() and idx > 0:
            break
    return meta, idx


def load_documents(directory: Path = None) -> list:
    """
    加载目录下所有知识文档
    返回 [{title, category, source, text, filename}]
    """
    directory = directory or config.KNOWLEDGE_DIR
    if not directory.exists():
        return []
    docs = []
    for fp in sorted(directory.glob("*")):
        if fp.suffix.lower() not in (".md", ".txt"):
            continue
        try:
            content = fp.read_text(encoding="utf-8")
        except Exception:
            continue  # 编码问题跳过该文件
        lines = content.splitlines()
        meta, body_start = _parse_meta(lines)
        body = "\n".join(lines[body_start:]).strip()
        if not body:
            continue
        docs.append({
            "title": meta.get("标题", fp.stem),
            "category": meta.get("分类", "未分类"),
            "source": meta.get("来源", "「银龄伴」知识库"),
            "text": body,
            "filename": fp.name,
        })
    return docs


# ============================================================
# 2. 清洗
# ============================================================
def clean_text(text: str) -> str:
    """清洗正文：去多余空白、去 markdown 井号、去分隔线"""
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)   # markdown 标题符
    text = re.sub(r"^[-*=_]{3,}\s*$", "", text, flags=re.M)  # 分隔线
    text = re.sub(r"[ \t]+", " ", text)                  # 行内多空格
    text = re.sub(r"\n{3,}", "\n\n", text)               # 多空行
    return text.strip()


# ============================================================
# 3. 分段（按段落聚合，带重叠）
# ============================================================
def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> list:
    """
    把长文本切分为带重叠的知识片段
    切分策略：优先按空行分段 → 段落聚合到 chunk_size 字 → 硬切兜底
    """
    chunk_size = chunk_size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks, buf = [], ""
    for para in paragraphs:
        # 单段超长 → 硬切
        if len(para) > chunk_size:
            if buf:
                chunks.append(buf)
                buf = ""
            for i in range(0, len(para), chunk_size - overlap):
                piece = para[i:i + chunk_size]
                if len(piece.strip()) >= 50:  # 过滤过短碎片
                    chunks.append(piece)
            continue
        # 聚合
        if len(buf) + len(para) + 1 <= chunk_size:
            buf = f"{buf}\n{para}".strip()
        else:
            chunks.append(buf)
            # 重叠：带上前段结尾
            tail = buf[-overlap:] if overlap > 0 else ""
            buf = f"{tail}{para}".strip()
    if buf:
        chunks.append(buf)

    # 相邻片段补充重叠（对硬切的段落已处理，聚合段落加尾部重叠）
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for prev, cur in zip(chunks, chunks[1:]):
            tail = prev[-overlap:]
            overlapped.append(tail + cur)
        chunks = overlapped
    return chunks


# ============================================================
# 4. 完整流水线：导入知识库
# ============================================================
async def import_knowledge(reset: bool = False, directory: Path = None) -> dict:
    """
    知识导入主流程：加载 → 清洗 → 分段 → 向量化 → 入库
    返回导入统计信息
    """
    stats = {"documents": 0, "chunks": 0, "category": {}, "backend": type(vector_store).__name__}

    docs = load_documents(directory)
    stats["documents"] = len(docs)
    if not docs:
        return stats

    # 清洗 + 分段
    all_chunks = []
    for doc in docs:
        clean = clean_text(doc["text"])
        for ci, chunk in enumerate(chunk_text(clean)):
            all_chunks.append({
                "id": f"{doc['filename']}-{ci}",
                "text": chunk,
                "source": f"{doc['title']}（{doc['source']}）",
                "category": doc["category"],
            })
    stats["chunks"] = len(all_chunks)
    if not all_chunks:
        return stats

    # 清空旧库
    if reset:
        vector_store.clear()

    # 向量化（批量，100 条一批）
    vecs = []
    for i in range(0, len(all_chunks), 100):
        batch = all_chunks[i:i + 100]
        vecs.extend(await embed_texts([c["text"] for c in batch]))

    # 组装记录并入库
    records = []
    for chunk, vec in zip(all_chunks, vecs):
        if not vec:
            continue
        records.append({**chunk, "vec": vec})
    vector_store.add(records)

    # 统计分类
    for c in all_chunks:
        stats["category"][c["category"]] = stats["category"].get(c["category"], 0) + 1
    return stats


def knowledge_stats() -> dict:
    """知识库统计（供健康检查接口展示）"""
    return vector_store.stats()
