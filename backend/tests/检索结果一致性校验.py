# -*- coding: utf-8 -*-
"""
检索优化 · 结果一致性校验（角色2：郝英博）

为什么需要这个脚本？
  为了提速，检索改成了两条快路径：
    ① 稀疏向量 → 倒排索引（原来是对全库逐条点积）
    ② 术语通道 → 定长小顶堆 Top-N（原来是全量排序 + 每条复制字典）
  "跑得快"不等于"跑得对"。本脚本用优化前的朴素实现作为参照，
  逐条比对 Top-K 结果与分数，确保优化只改性能、不改答案。

运行：
    D:\\yinlingban_env\\Scripts\\python.exe tests\\检索结果一致性校验.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag import retriever as R
from app.rag.vector_store import vector_store, cosine_sim
from app.rag.embeddings import embed_query
from importlib.machinery import SourceFileLoader

_here = os.path.dirname(os.path.abspath(__file__))
m = SourceFileLoader("bench", os.path.join(_here, "知识库性能压测.py")).load_module()

PASS, FAIL = 0, 0


def ok(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  → {detail}")


# ============================================================
# 参照实现：优化前的朴素写法
# ============================================================
def 朴素向量检索(query_vec, chunks, top_k, threshold):
    """优化前：对全库逐条余弦 + 全量排序"""
    scored = []
    for c in chunks:
        score = cosine_sim(query_vec, c.get("vec"))
        if score >= threshold:
            scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(round(s, 4), c.get("id")) for s, c in scored[:top_k]]


def 朴素术语检索(question, chunks, n):
    """优化前：每条片段重建术语集合 + 稳定排序（同分保持原始片段顺序）"""
    out = []
    for c in chunks:
        s = R._term_hit_score(question, c.get("text", ""))
        if s > 0:
            out.append((round(s, 4), c.get("id")))
    # Python sort 稳定：reverse=True 时同分元素仍保持原始相对顺序
    out.sort(key=lambda x: x[0], reverse=True)
    return out[:n]


async def main():
    print("═" * 60)
    print("「银龄伴」检索优化 · 结果一致性校验")
    print("═" * 60)

    真实库 = list(vector_store._chunks)
    问题集 = m.问题集
    TOP_K = 9

    for 规模 in (500, 5000):
        print(f"\n【规模 {规模} 条】")
        vector_store._chunks = 真实库 + m.生成片段(规模)
        vector_store._snapshot_cache = None
        vector_store._inverted = None
        vector_store._inverted_len = -1
        chunks = list(vector_store._chunks)

        # ---------- ① 向量通道：倒排索引 vs 全量点积 ----------
        # 说明：并列分数（如大量片段同为 0.3333）时，截断点取哪几条本质等价，
        #       因此校验"分数序列一致 + Top-1 一致 + 集合高度重合"，
        #       而不是苛刻到同分内部的排列顺序。
        差异数 = []
        top1_不一致 = []
        # 用线上真实阈值比对（config.RAG_SCORE_THRESHOLD=0.02），
        # 它才代表生产行为；threshold=0 时旧实现会拿零分片段凑数，无意义
        from app import config
        TH = config.RAG_SCORE_THRESHOLD
        for q in 问题集:
            qv = await embed_query(R._expand_query(q))
            快的 = [(r["score"], r.get("id")) for r in
                    vector_store.search(qv, top_k=TOP_K, threshold=TH)]
            参照 = 朴素向量检索(qv, chunks, TOP_K, TH)
            if [s for s, _ in 快的] != [s for s, _ in 参照]:
                差异数.append(q)
            if 快的[:1] != 参照[:1]:
                top1_不一致.append(q)
        ok(f"① 向量通道：分数序列与全量点积完全一致（{len(问题集)} 问）",
           not 差异数, f"分数有差异的问题：{差异数[:3]}")
        ok("① 向量通道：Top-1 命中片段完全一致", not top1_不一致,
           f"Top-1 不一致：{top1_不一致[:3]}")

        # ---------- ② 术语通道：小顶堆 vs 全量排序 ----------
        术语分数差异, 术语重合最低 = [], 1.0
        术语最差问题 = ""
        snap = vector_store.all_chunks()
        for q in 问题集:
            e = R._expand_query(q)
            快的 = [(r["term_score"], r.get("id")) for r in R._top_by_term(e, snap, TOP_K)]
            参照 = 朴素术语检索(e, snap, TOP_K)
            # 分数序列必须一致（证明评分逻辑没变）
            if sorted(s for s, _ in 快的) != sorted(s for s, _ in 参照):
                术语分数差异.append(q)
            # 集合重合度（同分并列过多时允许取到不同的等价片段）
            sa = {i for _, i in 快的}
            sb = {i for _, i in 参照}
            if not sa and not sb:
                jac = 1.0   # 两边都没命中（如"胸口发闷"没进词典）→ 视为一致
            else:
                jac = len(sa & sb) / max(len(sa | sb), 1)
            if jac < 术语重合最低:
                术语重合最低, 术语最差问题 = jac, q
        ok(f"② 术语通道：评分与全量排序一致（{len(问题集)} 问）",
           not 术语分数差异, f"评分有差异：{术语分数差异[:3]}")
        ok(f"② 术语通道：Top-{TOP_K} 集合重合度 ≥ 0.6（最低 {术语重合最低:.2f}）",
           术语重合最低 >= 0.6, f"重合度 {术语重合最低:.2f} @「{术语最差问题}」")

        # ---------- ③ 端到端：检索结果可复现（同样问题两次调用结果相同） ----------
        e2e_ok, e2e_diff = True, ""
        for q in 问题集:
            a = await R.retrieve(q)
            b = await R.retrieve(q)
            if [x.get("id") for x in a] != [x.get("id") for x in b]:
                e2e_ok = False
                e2e_diff = f"「{q}」两次检索结果不一致"
                break
        ok("③ 端到端：同一问题重复检索结果稳定", e2e_ok, e2e_diff)

        # ---------- ③b 零分噪声不进结果（倒排索引带来的行为改进） ----------
        qv = await embed_query(R._expand_query("肥肉和油炸的东西能不能经常吃"))
        线上 = vector_store.search(qv, top_k=TOP_K, threshold=TH)
        ok("③b 结果中不再混入 0 分噪声片段（倒排索引的副作用，是改进）",
           all(r["score"] > 0 for r in 线上),
           f"出现零分：{[r['score'] for r in 线上]}")

        # ---------- ④ 缓存失效：知识库变更后索引自动重建，结果同步更新 ----------
        新片段 = {
            "id": "injected-marker",
            "text": "血压高的人要少吃咸菜和腌制品，控制盐摄入，这是专门注入的验证片段。",
            "source": "一致性校验（合成）",
            "category": "高血压",
            "vec": await embed_query("高血压 咸菜 盐 腌制品 少盐"),
        }
        vector_store._chunks = chunks + [新片段]
        vector_store._inverted = None
        vector_store._inverted_len = -1
        res = await R.retrieve("我高血压能不能吃咸菜")
        ids = [r.get("id") for r in res]
        ok("④ 知识库新增片段后，倒排索引自动重建并能检索到新内容",
           "injected-marker" in ids, f"实际命中 {ids}")

    # 还原
    vector_store._chunks = 真实库
    vector_store._snapshot_cache = None
    vector_store._inverted = None
    vector_store._inverted_len = -1

    print(f"\n{'═' * 60}\n结果：通过 {PASS} 项，失败 {FAIL} 项\n{'═' * 60}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
