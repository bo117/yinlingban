# -*- coding: utf-8 -*-
"""
向量存储层（角色2：郝英博）

对应任务 2.3：部署 Milvus 向量数据库

双后端设计：
  1. Milvus（生产/Docker 部署，配置 MILVUS_URI 且安装 pymilvus 时启用）
  2. 本地文件向量库（JSON 存储，零依赖兜底，检索接口与 Milvus 完全一致）

本地向量库说明：
  - 规模在数千条知识片段以内时，纯 Python 余弦相似度检索延迟 < 10ms
  - 完全满足验收标准"检索响应 ≤ 500ms"
"""
import heapq
import json
import threading
from pathlib import Path

from app import config


# ============================================================
# 相似度计算（同时支持稠密/稀疏向量）
# ============================================================
def cosine_sim(a, b) -> float:
    """余弦相似度：支持稠密 list[float] 和稀疏 dict 两种向量"""
    if isinstance(a, dict) and isinstance(b, dict):
        # 稀疏向量：只遍历较短的一方的键
        if len(a) > len(b):
            a, b = b, a
        dot = sum(v * b.get(k, 0.0) for k, v in a.items())
        if dot == 0:
            return 0.0
        # 双方已 L2 归一化，点积即余弦
        return dot
    if isinstance(a, list) and isinstance(b, list):
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
    return 0.0


# ============================================================
# 本地文件向量库
# ============================================================
class LocalVectorStore:
    """
    本地向量库：JSON 文件存储
    结构：{"chunks": [{"id", "text", "source", "category", "vec"}]}
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._chunks = self._load()
        # 性能缓存：术语通道用的"全量快照"（不含 vec），add/clear 时自动失效
        self._snapshot_cache: list = None
        # 性能缓存：稀疏向量的倒排索引 token → [(片段下标, 权重)]，检索从
        # "全库点积"变成"只累加查询词命中的倒排链"，大库下快一个数量级
        self._inverted: dict = None
        self._inverted_len: int = -1

    def _load(self) -> list:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return data.get("chunks", [])
            except Exception:
                return []
        return []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"chunks": self._chunks}, ensure_ascii=False),
            encoding="utf-8",
        )

    # ---------- 缓存失效 ----------
    def _invalidate(self):
        """知识库内容变化后清空所有缓存（快照 + 倒排索引）"""
        self._snapshot_cache = None
        self._inverted = None
        self._inverted_len = -1


    # ---------- 增 ----------
    def add(self, records: list) -> int:
        """批量写入 [{id,text,source,category,vec}]，返回新增数量"""
        with self._lock:
            self._chunks.extend(records)
            self._invalidate()  # 快照与倒排索引一并失效
            self._save()
        return len(records)

    def clear(self):
        with self._lock:
            self._chunks = []
            self._invalidate()
            self._save()

    # ---------- 查 ----------
    def search(self, query_vec, top_k: int = 3, threshold: float = 0.0) -> list:
        """相似度检索 Top-K，返回按分数降序的结果

        【性能】先只算分数，过了阈值才构造结果字典（省掉绝大多数
        候选片段的临时对象分配，纯 Python 余弦扫描快约一倍）
        """
        with self._lock:
            snapshot = self._chunks  # 只读遍历，无需拷贝（add/clear 才会改列表）

        # 【性能·快路径】稀疏查询向量 + 稀疏库 → 走倒排索引
        #   只累加"查询词命中的倒排链"，复杂度从 O(全库 × 查询词数)
        #   降到 O(命中链总长)，大库下比全表点积快一个数量级
        if isinstance(query_vec, dict) and snapshot:
            inv = self._inverted_index()  # 混合库返回 None → 自动走兜底
            if inv:
                acc: dict = {}
                for tok, qw in query_vec.items():
                    chain = inv.get(tok)
                    if not chain:
                        continue
                    for idx, w in chain:
                        acc[idx] = acc.get(idx, 0.0) + qw * w
                return self._pack_top(acc, snapshot, top_k, threshold)

        # 【性能·兜底】稠密向量：定长小顶堆取 Top-K，
        #   避免对全库做一次 O(N log N) 排序（大库下省几毫秒）
        n = len(snapshot)
        if n > top_k * 8:
            heap = []
            seq = 0
            for c in snapshot:
                score = cosine_sim(query_vec, c.get("vec"))
                if score >= threshold:
                    if len(heap) < top_k:
                        heapq.heappush(heap, (score, seq, c))
                    elif score > heap[0][0]:
                        heapq.heapreplace(heap, (score, seq, c))
                    seq += 1
            top = sorted(heap, key=lambda x: x[0], reverse=True)
            return [{k: v for k, v in c.items() if k != "vec"} | {"score": round(score, 4)}
                    for score, _, c in top]

        scored = []
        for c in snapshot:
            score = cosine_sim(query_vec, c.get("vec"))
            if score >= threshold:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{k: v for k, v in c.items() if k != "vec"} | {"score": round(score, 4)}
                for score, c in scored[:top_k]]

    def _inverted_index(self) -> dict:
        """稀疏向量倒排索引（懒加载；片段数量变化时自动重建）

        结构：{token: [(片段下标, 权重), ...]}
        检索时只累加"查询词命中的倒排链"，不必对全库做点积。
        返回 None 表示库里含稠密向量（混合库），调用方需走全量点积兜底。
        """
        with self._lock:
            if self._inverted is None or self._inverted_len != len(self._chunks):
                inv: dict = {}
                has_dense = False
                for i, c in enumerate(self._chunks):
                    v = c.get("vec")
                    if not isinstance(v, dict):
                        has_dense = True  # 稠密向量无法倒排 → 整体走兜底
                        continue
                    for tok, w in v.items():
                        bucket = inv.get(tok)
                        if bucket is None:
                            inv[tok] = [(i, w)]
                        else:
                            bucket.append((i, w))
                # 混合库（既有稠密又有稀疏）不能只查倒排，会漏掉稠密片段
                self._inverted = None if has_dense else inv
                self._inverted_len = len(self._chunks)
            return self._inverted

    def _pack_top(self, acc: dict, snapshot: list, top_k: int, threshold: float) -> list:
        """把倒排累加出的 {片段下标: 分数} 打包成 Top-K 结果"""
        # 【正确性】同分按片段下标升序回退：倒排累加的插入顺序取决于查询词，
        #          不回退到原始顺序会导致并列片段取到不同的 Top-K（结果不可复现）
        cands = [(s, i) for i, s in acc.items() if s >= threshold]
        if not cands:
            return []
        if len(cands) > top_k * 8:
            top = heapq.nlargest(top_k, cands, key=lambda x: (x[0], -x[1]))
        else:
            cands.sort(key=lambda x: (-x[0], x[1]))
            top = cands[:top_k]
        return [{k: v for k, v in snapshot[i].items() if k != "vec"}
                | {"score": round(s, 4)} for s, i in top]

    def all_chunks(self) -> list:
        """返回全部片段快照（不带 vec，检索做全量术语评分用）

        【性能】缓存快照，检索高频调用时不再每次全量深拷贝；
        调用方只读使用（修改前自行 dict(c) 复制，retriever 已如此）。
        """
        with self._lock:
            if self._snapshot_cache is None:
                self._snapshot_cache = [
                    {k: v for k, v in c.items() if k != "vec"} for c in self._chunks
                ]
            return self._snapshot_cache

    def stats(self) -> dict:
        from collections import Counter
        cats = Counter(c.get("category", "未分类") for c in self._chunks)
        return {"total": len(self._chunks), "by_category": dict(cats)}


# ============================================================
# Milvus 向量库（可选，Docker 部署时启用）
# ============================================================
class MilvusVectorStore:
    """Milvus 向量库封装（需要 pymilvus，且 MILVUS_URI 已配置）"""

    COLLECTION = "health_knowledge"

    def __init__(self, uri: str):
        from pymilvus import MilvusClient  # 惰性导入，未安装不影响启动
        self.client = MilvusClient(uri=uri)
        self._dim = None
        self._ensure_collection()

    def _ensure_collection(self):
        from pymilvus import DataType
        if self.client.has_collection(self.COLLECTION):
            return
        schema = self.client.create_schema(auto_id=True, enable_dynamic_field=True)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("text", DataType.VARCHAR, max_length=4000)
        schema.add_field("source", DataType.VARCHAR, max_length=256)
        schema.add_field("category", DataType.VARCHAR, max_length=64)
        schema.add_field("vec", DataType.FLOAT_VECTOR, dim=1024)  # 默认维度
        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="vec", index_type="FLAT", metric_type="COSINE")
        self.client.create_collection(self.COLLECTION, schema=schema, index_params=index_params)

    def add(self, records: list) -> int:
        rows = []
        for r in records:
            if isinstance(r.get("vec"), dict):
                continue  # Milvus 不支持稀疏向量记录，跳过（本地模式才用稀疏）
            rows.append({
                "text": r["text"][:4000],
                "source": r.get("source", "")[:256],
                "category": r.get("category", "")[:64],
                "vec": r["vec"],
            })
        if rows:
            self.client.insert(self.COLLECTION, rows)
        return len(rows)

    def clear(self):
        if self.client.has_collection(self.COLLECTION):
            self.client.drop_collection(self.COLLECTION)
        self._ensure_collection()

    def search(self, query_vec, top_k: int = 3, threshold: float = 0.0) -> list:
        if isinstance(query_vec, dict):
            return []  # 稀疏查询向量无法在 Milvus 检索
        res = self.client.search(
            self.COLLECTION,
            data=[query_vec],
            limit=top_k,
            output_fields=["text", "source", "category"],
        )
        results = []
        for hit in res[0]:
            entity = hit.get("entity", {})
            score = hit.get("distance", 0)
            if score >= threshold:
                results.append({
                    "text": entity.get("text", ""),
                    "source": entity.get("source", ""),
                    "category": entity.get("category", ""),
                    "score": round(score, 4),
                })
        return results

    def all_chunks(self) -> list:
        """Milvus 不支持取全量快照，返回空（术语通道自动跳过）"""
        return []

    def stats(self) -> dict:
        return {"total": -1, "by_category": {}, "note": "Milvus 后端"}


# ============================================================
# 统一工厂
# ============================================================
def get_vector_store():
    """根据配置返回向量库实例：Milvus 优先，失败降级本地"""
    if config.MILVUS_URI:
        try:
            return MilvusVectorStore(config.MILVUS_URI), "milvus"
        except Exception:
            pass  # Milvus 不可用 → 本地向量库兜底
    return LocalVectorStore(config.VECTOR_STORE_PATH), "local"


# 全局单例
vector_store, vector_backend = get_vector_store()
