# -*- coding: utf-8 -*-
"""
本地知识库 · 规模化性能压测（角色2：郝英博）

为什么需要这个脚本？
  仓库自带的 8 条知识片段太小了 —— 检索 0.0ms 是"假快"，
  根本测不出真实瓶颈。老人真实使用时知识库会长到几百上千条，
  本脚本用合成片段把库撑到 1000 / 5000 条，量出真实延迟。

运行（不用启动服务、不需要 API Key）：
    D:\\yinlingban_env\\Scripts\\python.exe tests\\知识库性能压测.py

做法：临时把合成片段灌进 vector_store 的内存列表（不写盘、不污染真实库），
      测完原样还原。
"""
import asyncio
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag import retriever as rag_retriever
from app.rag.vector_store import vector_store
from app.rag.embeddings import local_sparse_vector, embedding_mode

PASS, FAIL = 0, 0


def ok(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}" + (f"  → {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  ✗ {name}  → {detail}")


def line(title: str):
    print(f"\n{'─' * 60}\n{title}\n{'─' * 60}")


# ============================================================
# 合成知识库：模拟真实规模
# ============================================================
# 用真实健康主题的词汇组合出逼真的片段（中文 bigram 分布接近真实语料）
主题词库 = [
    ("高血压", ["血压", "降压药", "低盐", "测量", "晨峰", "头晕", "遵医嘱", "钠"]),
    ("糖尿病", ["血糖", "胰岛素", "主食", "粗粮", "含糖", "水果", "热量", "监测"]),
    ("冠心病", ["心脏", "心绞痛", "硝酸甘油", "血脂", "胆固醇", "胸闷", "支架"]),
    ("合理用药", ["吃药", "用药", "漏服", "剂量", "副作用", "医嘱", "温水送服", "按时"]),
    ("饮食", ["膳食", "营养", "蛋白质", "蔬菜", "水果", "补钙", "清淡", "少油"]),
    ("运动", ["锻炼", "太极", "散步", "走路", "活动", "晨练", "拉伸", "关节"]),
    ("睡眠", ["失眠", "入睡", "午觉", "作息", "生物钟", "睡前", "泡脚"]),
    ("秋冬", ["保暖", "感冒", "流感", "疫苗", "通风", "干燥", "加湿"]),
]
句式 = [
    "老人{cat}方面要注意：{a}和{b}都很关键，建议每天坚持{c}，同时避免{d}。",
    "关于{c}，医生建议：控制{a}，适当{b}，如果出现{d}要及时就医并{c}。",
    "{cat}的日常管理：一是{a}，二是{b}，三是{c}；特别要当心{d}带来的风险。",
    "很多老人问{c}怎么办。正确做法是保持{a}、减少{b}，并且规律{c}，远离{d}。",
    "温馨提示：{a}过量会加重{b}。建议以{c}为主，少吃{d}，身体会更舒服。",
    "{cat}护理要点：早晨{a}、中午{b}、晚上{c}；一旦{d}请马上联系家人。",
]


def 生成片段(n: int) -> list:
    """生成 n 条合成知识片段（带向量），分布贴近真实中文健康语料"""
    import random
    random.seed(42)  # 固定种子 → 每次压测数据一致，结果可比
    out = []
    for i in range(n):
        cat, words = 主题词库[i % len(主题词库)]
        a, b, c, d = random.sample(words, 4)
        text = 句式[i % len(句式)].format(cat=cat, a=a, b=b, c=c, d=d)
        text += f" 这是第{i}条健康提示，供参考（来源：银龄伴健康知识库）。"
        out.append({
            "id": f"synthetic-{i}",
            "text": text,
            "source": f"{cat}健康提示（合成）",
            "category": cat,
            "vec": local_sparse_vector(text),
        })
    return out


# ============================================================
# 压测主流程
# ============================================================
问题集 = [
    "我高血压能不能吃咸菜",
    "血压高早上起来头晕怎么办",
    "糖尿病人水果能多吃吗",
    "晚上睡不着觉有什么办法",
    "降压药忘了吃要不要补上",
    "冬天早上出门锻炼好不好",
    "我口味重，吃盐多对身体有什么影响",
    "肥肉和油炸的东西能不能经常吃",
    "喝茶水送药行不行",
    "胸口发闷是怎么回事",
    "感冒了能多吃两颗药好的快吗",
    "老人补钙吃什么好",
    "我心里发慌是不是心脏有问题",
    "血糖高主食该吃多少",
]


def 清空缓存():
    """彻底清空 RAG 缓存（CacheService 没有 clear()，直接清内存字典）"""
    from app.db.cache import cache
    with cache._memory._lock:
        cache._memory._store.clear()
        cache._memory._expire.clear()


async def 压测一轮(规模: int, 真实库: list):
    """在指定规模下压测真实检索（绕过缓存），返回 (avg, p95, max)"""
    # 灌入合成数据（只在内存，不写盘）
    vector_store._chunks = 真实库 + 生成片段(规模)
    vector_store._snapshot_cache = None   # 强制重建快照
    vector_store._inverted = None         # 强制重建倒排索引
    vector_store._inverted_len = -1
    清空缓存()

    次数 = 3
    timings = []
    for _ in range(次数):
        for q in 问题集:
            清空缓存()  # 每问都清空 → 测的是真实检索，不是缓存命中
            t0 = time.perf_counter()
            await rag_retriever.retrieve(q)  # 直接调检索核心，绕开缓存层
            timings.append((time.perf_counter() - t0) * 1000)
    timings.sort()
    return (statistics.mean(timings),
            timings[int(len(timings) * 0.95) - 1],
            timings[-1])


async def main():
    print("═" * 60)
    print("「银龄伴」本地知识库 · 规模化性能压测")
    print("═" * 60)
    print(f"  向量化模式：{embedding_mode()}")
    print(f"  真实知识片段：{vector_store.stats().get('total', 0)} 条")

    真实库 = list(vector_store._chunks)  # 备份，测完还原
    基线 = {}

    for 规模 in (0, 1000, 3000, 5000):
        total = len(真实库) + 规模
        avg, p95, mx = await 压测一轮(规模, 真实库)
        基线[规模] = (avg, p95, mx)
        print(f"\n  【规模 {total:>5} 条】avg {avg:7.2f}ms | p95 {p95:7.2f}ms | max {mx:7.2f}ms")

    # 还原真实库
    vector_store._chunks = 真实库
    vector_store._snapshot_cache = None

    # ========== 验收 ==========
    line("验收：检索延迟 ≤ 500ms（p95）")
    for 规模, (avg, p95, mx) in 基线.items():
        ok(f"规模 {len(真实库) + 规模} 条 · p95 {p95:.1f}ms ≤ 500ms", p95 <= 500,
           f"p95={p95:.1f}ms")

    # 规模增长是否线性劣化（5000 条 vs 1000 条，应接近 5 倍以内，说明无明显超线性热点）
    if 基线[1000][0] > 0.01 and 基线[5000][0] > 0:
        倍率 = 基线[5000][0] / 基线[1000][0]
        print(f"\n  规模 1000→5000（5倍）延迟增长：{倍率:.2f} 倍")
        ok("延迟随规模线性增长（5倍规模 ≤ 8倍耗时，无超线性热点）", 倍率 <= 8.0,
           f"实际 {倍率:.2f} 倍")

    print(f"\n{'═' * 60}\n结果：通过 {PASS} 项，失败 {FAIL} 项\n{'═' * 60}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
