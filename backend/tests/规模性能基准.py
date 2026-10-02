# -*- coding: utf-8 -*-
"""
知识库规模性能基准（角色2：郝英博）

把向量库临时扩充到 200 片段（验收要求 80+ 篇文档入库后的规模），
测混合检索延迟；测完自动还原。用于评估检索层优化效果。

运行：
    D:\\yinlingban_env\\Scripts\\python.exe tests\\规模性能基准.py
"""
import asyncio
import shutil
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.vector_store import vector_store
from app.rag import retriever
from app.rag.embeddings import local_sparse_vector

STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "vector_store.json"
QUESTIONS = [
    "我高血压能不能吃咸菜", "糖尿病人水果能多吃吗", "晚上失眠睡不着怎么办",
    "降压药忘了吃要不要补上", "胸口闷心慌怎么回事",
]


def _expand_to(n: int):
    """把向量库临时扩充到 n 片段（内存态，不落盘）"""
    tpl = ("高血压饮食要清淡少盐每天不超过5克,戒烟限酒,规律服药监测血压,"
           "多吃绿叶蔬菜和水果,适量运动如散步太极,避免熬夜情绪波动")
    real = list(vector_store._chunks)
    fake = []
    for i in range(n - len(real)):
        t = f"片段{i} " + tpl[(i % 7) * 3:] + tpl[:(i % 11) * 4]
        fake.append({"id": f"fake{i}", "text": t, "source": f"bench{i}",
                     "category": "bench", "vec": local_sparse_vector(t)})
    vector_store._chunks = real + fake
    vector_store._snapshot_cache = None
    if hasattr(vector_store, "_term_index_cache"):
        vector_store._term_index_cache = None
    return real


def _restore(real: list):
    vector_store._chunks = real
    vector_store._snapshot_cache = None
    if hasattr(vector_store, "_term_index_cache"):
        vector_store._term_index_cache = None


async def bench(n_chunks: int, repeat: int = 8) -> dict:
    backup = STORE_PATH.with_suffix(".json.benchbak")
    shutil.copy(STORE_PATH, backup)
    try:
        real = _expand_to(n_chunks)
        ts = []
        for q in QUESTIONS * repeat:
            t0 = time.perf_counter()
            await retriever.retrieve(q)  # 不走问题缓存，测真实检索成本
            ts.append((time.perf_counter() - t0) * 1000)
        ts.sort()
        result = {
            "chunks": n_chunks, "queries": len(ts),
            "avg_ms": round(statistics.mean(ts), 1),
            "p95_ms": round(ts[int(len(ts) * 0.95) - 1], 1),
            "max_ms": round(ts[-1], 1),
        }
        # 冷启动（扩充后第一次检索）单独看
        return result
    finally:
        _restore(real)
        shutil.copy(backup, STORE_PATH)
        backup.unlink(missing_ok=True)


async def main():
    print("知识库规模性能基准（混合检索，不含问题缓存）")
    for n in (8, 80, 200, 400):
        r = await bench(n)
        print(f"  {r['chunks']:>4} 片段 × {r['queries']} 问："
              f"avg {r['avg_ms']:>6.1f}ms | p95 {r['p95_ms']:>6.1f}ms | max {r['max_ms']:>6.1f}ms")


if __name__ == "__main__":
    asyncio.run(main())
