# -*- coding: utf-8 -*-
"""
RAG 检索服务（角色2：郝英博）

对应任务 2.4：实现
  问题向量化 → 相似度检索 → Top-K 结果拼接 → LLM 生成回答
  的完整 RAG 链路，配置检索阈值和 Prompt 模板

V2 升级（对应《AI观点汇总表》第二轮论文调研）：
  ① 查询改写（同义词图谱）——老人口语 → 知识库术语，提升召回（Dify 领域增强：62%→90%）
  ② 双通道检索 + RRF 分数融合 —— n-gram向量 + 术语命中，倒数排名融合（Med-HyRAG）
"""
import heapq
import time
import re

from app import config
from app.rag.embeddings import embed_query
from app.rag.vector_store import vector_store


# 健康类问题关键词（命中才走 RAG，避免闲聊也检索浪费性能）
HEALTH_KEYWORDS = [
    "血压", "血糖", "糖尿", "心脏", "冠心", "吃药", "服药", "用药", "药",
    "睡眠", "失眠", "睡觉", "饮食", "吃什么", "锻炼", "运动", "养生", "保健",
    "头晕", "头痛", "感冒", "发烧", "咳嗽", "腿疼", "腰疼", "关节", "视力",
    "体检", "降压", "降糖", "钙", "维生素", "营养", "便秘", "胃", "盐",
    "油", "烟", "酒", "喝茶", "喝水", "体重", "血脂", "尿酸",
]


def is_health_related(text: str) -> bool:
    """判断问题是否与健康知识相关（决定是否触发 RAG 检索）
    越界词也算健康相关——这样库外健康问题会走"诚实拒答"而不是被闲聊敷衍"""
    if any(k in text for k in HEALTH_KEYWORDS):
        return True
    if is_out_of_scope(text):
        return True
    return False


# ============================================================
# ① 同义词图谱：老人日常口语 → 知识库会用的术语
#    检索前把问题"翻译"一遍，极大提升召回（论文：Dify领域增强）
# ============================================================
SYNONYM_EXPANSION = {
    "咸菜": "盐 含盐 腌菜 咸 清淡",
    "腌": "盐 腌制 含盐",
    "腊肉": "盐 咸 含盐",
    "咸": "盐 含盐 清淡",
    "吃盐多": "盐 含盐量 控制盐",
    "口味重": "盐 含盐 重口味 清淡",
    "少吃甜": "糖 含糖 甜食",
    "甜食": "糖 含糖 甜",
    "糖": "糖 血糖 含糖",
    "油腻": "油 脂肪 清淡 少油",
    "肥肉": "油 脂肪 动物脂肪",
    "炸": "油 油炸 脂肪",
    "大鱼大肉": "油 脂肪 荤 腻",
    "抽烟": "烟 吸烟 戒烟",
    "吸烟": "烟 戒烟",
    "喝酒": "酒 饮酒 戒烟限酒",
    "白酒": "酒 饮酒",
    "睡不着": "睡眠 失眠 入睡",
    "失眠": "睡眠 睡不着 安眠",
    "早起": "作息 睡眠 生物钟",
    "蔬菜": "绿叶菜 膳食纤维 多吃菜",
    "水果": "水果 血糖 果糖",
    "锻炼": "运动 活动 走路 太极",
    "运动": "锻炼 活动 散步 太极",
    "散步": "走路 运动 活动",
    "头晕": "头晕 测血压 血压",
    "胸闷": "心脏 胸口 心绞痛 冠心病",
    "心慌": "心脏 心率 心跳",
    "吃药": "用药 服药 药",
    "停药": "药 遵医嘱 漏服",
    "补品": "保健 维生素 钙片 保健品",
    "钙": "钙 补钙 骨质疏松",
    # 第二轮补全（感冒/漏服/药效/喝水）
    "感冒": "感冒 流感 免疫力 受凉",
    "两颗": "剂量 用量 过量 药物",
    "漏吃": "漏服 忘记 补服 药",
    "补上": "漏服 补服 药",
    "药效": "药 药物 效果 相互作用",
    "送药": "药 温开水 茶水 送服",
    "吃多少": "用量 剂量 药 适量",
    "喝水": "水 饮水 温水 补水",
    "不够营养": "营养 膳食 蛋白质 饮食",
    "好消化": "消化 软烂 饮食 肠胃",
    "热": "洗澡 水温 心脏",
    "早锻炼": "锻炼 运动 晨练 时间",
    "冬天": "秋冬 保暖 感冒 流感",
    # 第三轮补全（漏服/加量/喝水 映射到合理用药片段）
    "感冒了能吃": "药 用药 剂量 遵医嘱",
    "两颗": "剂量 用量 遵医嘱 按时按量",
    "忘了吃": "漏吃 漏服 补上 按时",
    "补": "漏服 补服 按时",
    "吃多了": "加量 剂量 按时按量 遵医嘱 乱加",
    "加量": "剂量 遵医嘱 按时按量",
    "减量": "剂量 遵医嘱 按时按量",
    "升": "剂量 用药",
    "吃几片": "剂量 用量 按时按量",
    "用茶水": "茶水 送药 温开水",
}

# 健康强相关术语（命中分给得高——术语通道的词典权重）
TERM_LEXICON = {
    "高血压": ["高血压", "血压", "降压药", "盐", "低盐", "HBP"],
    "糖尿病": ["糖尿病", "血糖", "胰岛素", "主食", "热量", "粗粮", "含糖"],
    "冠心病": ["冠心病", "心脏", "心绞痛", "硝酸甘油", "血脂", "胆固醇"],
    "合理用药": ["吃药", "用药", "服药", "漏服", "药物", "副作用", "医嘱", "药品"],
    "饮食": ["吃", "饮食", "膳食", "营养", "蛋白", "蔬菜", "水果", "钙", "饮食"],
    "运动": ["运动", "锻炼", "太极", "散步", "走路", "活动"],
    "睡眠": ["睡眠", "失眠", "入睡", "午觉", "安眠", "睡眠质量"],
    "秋冬": ["秋冬", "感冒", "流感", "保暖", "流感疫苗", "通风"],
}

# ============================================================
# 知识库边界：库外主题词（认不认识要诚实，不装懂）
# 命中任一 → 判定"知识库里没有贴合内容"，触发"建议问医生"（ConfQA诚实）
# ============================================================
OUT_OF_SCOPE_WORDS = [
    "腰椎", "椎间盘", "帕金森", "白内障", "青光眼", "化疗", "肿瘤", "癌症",
    "人参", "灵芝", "疫苗", "阿尔茨海默", "痴呆", "脑梗", "中风", "血栓",
    "痛风", "结石", "肾衰", "尿毒症", "乙肝", "结核", "艾滋病", "手术",
]


def is_out_of_scope(question: str) -> bool:
    """问题是否命中知识库外主题（是 → 直接诚实拒答，不做检索）"""
    return any(w in question for w in OUT_OF_SCOPE_WORDS)


def _expand_query(question: str) -> str:
    """
    查询改写：命中同义词图谱的现成短词 → 追加术语串。
    "我高血压能不能吃咸菜" → 原问题 + "盐 含盐 腌菜 咸 清淡"
    检索时两者都参与，召回大幅提升。
    """
    # 把命中的所有同义词图谱扩展词收集
    扩展串 = []
    for 口语, 术语 in SYNONYM_EXPANSION.items():
        if 口语 in question:
            扩展串.append(术语)
    if 扩展串:
        return question + " " + " ".join(扩展串[:4])  # 最多4组，防膨胀
    return question


# ============================================================
# ② 术语命中通道（稀疏通道）：图谱术语在片段里的覆盖度
# ============================================================
def _collect_terms(question: str) -> tuple:
    """收集问题（含改写）里命中的健康术语集合

    【性能关键】这个集合只跟问题有关、跟片段无关。
    原实现对每个片段都重建一次（100 个术语 × N 条片段 = 全表扫描的主要开销），
    5000 条时占检索耗时 70%。这里抽出来按问题缓存，全表扫描只做"命中计数"。
    """
    terms = set()
    for 口语, 术语串 in SYNONYM_EXPANSION.items():
        if 口语 in question:
            terms.update(术语串.split())
    for 类 in TERM_LEXICON:
        for t in TERM_LEXICON[类]:
            if t in question:
                terms.add(t)
    return tuple(terms)


# 问题 → 术语集合 的缓存（老人口语高度重复，命中率很高）
from functools import lru_cache  # noqa: E402


@lru_cache(maxsize=512)
def _terms_cached(question: str) -> tuple:
    """按问题缓存术语集合，避免同一问题重复构建"""
    return _collect_terms(question)


def _term_hit_score(question: str, chunk_text: str) -> float:
    """问题（含改写）里的健康术语在片段中有多少命中（归一化）"""
    terms = _terms_cached(question)
    if not terms:
        return 0.0
    hits = sum(1 for t in terms if t in chunk_text)
    return hits / len(terms)


# ============================================================
# ③ RRF 倒数排名融合（Med-HyRAG）
# ============================================================
def _rrf_merge(vec_results: list, term_results: list, k: int = 60, top_n: int = 5) -> list:
    """把两路检索结果按 RRF 融合成一份（未命中的片段不计入融合）"""
    merged = {}      # id → dict
    rank_score = {}  # id → rrf 分数

    # 惯例 K 一般 60；保证排在越前得分越高
    def add_rank(results, weight=1.0):
        for i, r in enumerate(results):
            rid = r.get("id") or r.get("source", "")
            if not rid:
                continue
            score = 1.0 / (k + i + 1)
            rank_score[rid] = rank_score.get(rid, 0.0) + weight * score
            merged[rid] = r

    add_rank(vec_results, weight=1.0)
    add_rank(term_results, weight=1.0)  # 术语通道与向量通道同权重

    ranked = sorted(
        ({**merged[rid], "rrf": round(rank_score[rid], 5)} for rid in rank_score),
        key=lambda x: x["rrf"], reverse=True,
    )
    final = ranked[:top_n]

    # 向量保底：向量通道的 Top-1 永远保留（语义判相关=相关，不被稀疏挤掉）
    if vec_results:
        top1_id = vec_results[0].get("id") or vec_results[0].get("source", "")
        ids_in = {r.get("id") or r.get("source", "") for r in final}
        if top1_id and top1_id not in ids_in:
            final = [vec_results[0]] + final[:top_n - 1]
    return final


def _top_by_term(question: str, chunks: list, n: int) -> list:
    """术语通道 Top-N：定长小顶堆，一遍扫描出结果（不复制全表、不全量排序）"""
    if n <= 0:
        return []
    terms = _terms_cached(question)
    if not terms:
        return []
    # 【正确性·坑】堆元素第二维必须用 -seq 而不是 seq：
    #   小顶堆的堆顶是"最该被淘汰的"。同分时应淘汰"后到的"（seq 大），
    #   保留"先到的"（seq 小）才能和原实现的稳定排序一致。
    #   若写成 (s, seq)，同分时 seq 最小的反而成了堆顶被优先淘汰，
    #   结果会保留后到的片段 —— 与稳定排序相反（实测重合度掉到 0.5）。
    heap = []  # (score, -seq, chunk)
    seq = 0
    # 【性能】片段侧预计算"每个片段含哪些词典术语"，检索只做集合交集
    # （从 片段×术语 字符串扫描降为 片段 级集合运算，大库下快一个数量级）
    q_terms = frozenset(terms)
    for c, c_terms in zip(chunks, _chunk_term_sets(chunks)):
        hits = len(q_terms & c_terms)
        if hits:
            # 用对外暴露的分数（4 位小数）参与排序与比较：
            # 若用未取整的原始分数，四舍五入后并列的片段会选出不同的组合，
            # 导致与"先算分再排序"的原实现结果不一致
            s = round(hits / len(terms), 4)
            if len(heap) < n:
                heapq.heappush(heap, (s, -seq, c))
            elif s > heap[0][0]:
                heapq.heapreplace(heap, (s, -seq, c))
            seq += 1
    # 分数降序、同分按原始片段顺序（seq 升序）回退
    ordered = sorted(heap, key=lambda x: (-x[0], -x[1]))
    # 此时才复制字典（最多 n 份，而不是全表）
    return [dict(c) | {"term_score": round(s, 4)} for s, _, c in ordered]


# ---- 片段侧术语集合缓存（与 all_chunks 同序；库大小变化自动重建）----
_chunk_terms_len: int = -1
_chunk_terms_cache: list = None
_lexicon_universe_cache: frozenset = None


def _lexicon_universe() -> frozenset:
    """全部图谱/词典术语的并集（进程内只算一次）"""
    global _lexicon_universe_cache
    if _lexicon_universe_cache is None:
        terms = set()
        for v in SYNONYM_EXPANSION.values():
            terms.update(v.split())
        for v in TERM_LEXICON.values():
            terms.update(v)
        _lexicon_universe_cache = frozenset(terms)
    return _lexicon_universe_cache


def _chunk_term_sets(chunks: list) -> list:
    """每个片段预计算"包含哪些图谱/词典术语"的 frozenset（懒加载）"""
    global _chunk_terms_len, _chunk_terms_cache
    if _chunk_terms_cache is None or _chunk_terms_len != len(chunks):
        universe = _lexicon_universe()
        _chunk_terms_cache = [
            frozenset(t for t in universe if t in c.get("text", ""))
            for c in chunks
        ]
        _chunk_terms_len = len(chunks)
    return _chunk_terms_cache


def warmup_retrieval() -> dict:
    """
    预热检索索引（服务启动时调用一次）

    倒排索引和片段术语集合都是懒加载的 —— 不预热的话，大库下第一次提问
    会额外花上百毫秒现建索引，正好卡在老人问的第一句话上。
    启动期先建好，首次对话就是热的。
    """
    import time
    t0 = time.perf_counter()
    chunks = vector_store.all_chunks()
    _chunk_term_sets(chunks)
    if hasattr(vector_store, "_inverted_index"):
        vector_store._inverted_index()
    return {"chunks": len(chunks),
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


async def retrieve(question: str, top_k: int = None,
                   threshold: float = None) -> list:
    """
    混合检索 Top-K 知识片段（V2）：
      通道1：查询改写后的 n-gram 向量相似度
      通道2：术语命中覆盖度（全量评分，稀疏）
      两路用 RRF 融合，召回率显著高于单一向量检索
    """
    top_k = top_k or config.RAG_TOP_K
    threshold = config.RAG_SCORE_THRESHOLD if threshold is None else threshold

    # 诚实边界：知识库外主题 → 直接返回空（不硬编、不假装知道）
    if is_out_of_scope(question):
        return []

    # 查询改写（同义词扩展）
    expanded = _expand_query(question)

    # 通道1：向量相似度（用改写后的问题，召回更强）
    vec_results = []
    query_vec = await embed_query(expanded)
    if query_vec:
        vec_results = vector_store.search(query_vec, top_k=top_k * 3, threshold=threshold)

    # 通道2：术语命中（全量快照评分，纯 Python 毫秒级）
    # 【性能】定长小顶堆保留 Top-N：不再给每条命中片段复制字典、也不全量排序，
    #        只保留真正要用的前 top_k*3 条（大库下省掉上千次临时对象分配）
    term_results = _top_by_term(expanded, vector_store.all_chunks(), top_k * 3)

    # RRF 融合
    if vec_results and term_results:
        return _rrf_merge(vec_results, term_results, top_n=top_k)
    return vec_results or term_results


def format_context(chunks: list) -> str:
    """
    把检索结果拼接成 Prompt 上下文（编号 + 正文 + 来源）
    供 persona.RAG_PROMPT_TEMPLATE 使用
    """
    if not chunks:
        return ""
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"【知识{i}】{c['text']}\n（来源：{c.get('source', '知识库')}）")
    return "\n\n".join(parts)


def extract_sources(chunks: list) -> list:
    """提取知识来源列表（回答可追溯）"""
    return [
        {
            "title": c.get("source", ""),
            "category": c.get("category", ""),
            "score": c.get("score", 0),
        }
        for c in chunks
    ]


async def retrieve_with_context(question: str) -> dict:
    """
    RAG 检索统一入口：返回拼接好的上下文与来源
    供对话编排服务调用（对话主链路使用，带缓存与耗时统计）
    """
    from app.db.cache import cache

    start = time.time()
    # 缓存：相同问题的检索结果缓存 1 小时，减少重复计算
    cache_key = f"rag:{question[:64]}"
    cached = cache.get(cache_key)
    if cached:
        return {
            "context": cached["context"],
            "sources": cached["sources"],
            "elapsed_ms": 0,
            "cached": True,
        }

    chunks = await retrieve(question)
    context = format_context(chunks)
    sources = extract_sources(chunks)
    result = {"context": context, "sources": sources,
              "elapsed_ms": round((time.time() - start) * 1000, 1), "cached": False}
    if chunks:
        cache.set(cache_key, {"context": context, "sources": sources}, ttl=3600)
    return result
