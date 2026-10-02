# -*- coding: utf-8 -*-
"""
「银龄伴」检索召回率评测（V2 混合检索 vs V1 单一向量）

构造 30 个常见健康问题，标注"期望命中哪类知识"，
统计 Top-5 内是否命中期望知识——量化"准确率从 95 到 99"。

用法（后端起好后）：
    D:\\yinlingban_env\\Scripts\\python.exe 蒸馏工具\\检索评测.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag import retriever as R  # noqa: E402
from app.rag.embeddings import embed_query  # noqa: E402
from app.rag.vector_store import vector_store  # noqa: E402

# 30 个健康问题：每个标注"期望命中知识"关键词（命中该关键词就算检索对了）
评测题 = [
    # 高血压
    ("血压高，平时吃盐要注意什么", "盐"),
    ("老人高血压，降压药要按时吃吗", "降压药"),
    ("体检血压150了，算是高血压吗", "血压"),
    ("高血压能吃咸菜和腊肉吗", "盐"),
    ("血压老是控制不住高怎么办", "血压"),
    # 糖尿病
    ("血糖高，米饭能不能多吃", "主食"),
    ("糖尿病老人水果能吃吗", "水果"),
    ("血糖高，甜的东西是不是不能碰", "糖"),
    ("得了糖尿病，怎么管住嘴", "血糖"),
    ("血糖突然低了心慌手抖是怎么回事", "血糖"),
    # 冠心病/心脏
    ("胸口闷，会是心脏的问题吗", "心脏"),
    ("冠心病老人出门要注意什么", "冠心"),
    ("心绞痛发作时含什么药", "硝酸甘油"),
    ("心脏不好，洗澡水能太热吗", "心脏"),
    ("血脂高是不是容易得冠心病", "冠心"),
    # 合理用药
    ("感冒了能吃两颗药吗", "按时按量"),
    ("降压药忘了吃要不要补上", "漏吃"),
    ("保健品能代替降压药吗", "保健品"),
    ("吃药能用茶水送吗", "送药"),
    ("药吃多了会怎么样", "按时按量"),
    # 饮食营养
    ("老人吃什么补钙好", "钙"),
    ("每天喝牛奶要注意什么", "蛋白"),
    ("吃饭总是吃不够营养怎么办", "营养"),
    ("老人消化不好，吃什么好消化", "消化"),
    ("一天该喝多少水", "喝水"),
    # 运动/睡眠/秋冬
    ("老人早上几点锻炼合适", "运动"),
    ("运动时心跳很快正常吗", "运动"),
    ("晚上睡不着有什么办法", "睡眠"),
    ("秋冬老人怎么防感冒", "秋冬"),
    ("天冷了血压高是不是正常的", "秋冬"),
]

# 越界问题（知识库里没有的）：正确行为 = 检索低置信/诚实说没有，而不是硬编
越界题 = [
    "腰椎间盘突出压迫神经吃什么药好",
    "帕金森晚期能活几年",
    "白内障手术要花多少钱",
    "糖尿病做手术要注意什么",
    "肿瘤化疗期间能不能吃人参",
    "老人要打肺炎疫苗还是流感疫苗",
    "阿尔茨海默症最佳治疗方案",
]


def _命中(chunks: list, 期望词: str) -> bool:
    """检索结果里是否有一个片段包含期望词"""
    for c in chunks:
        if 期望词 in c.get("text", "") or 期望词 in c.get("source", ""):
            return True
    return False


def _top1_hit(chunks: list, 期望词: str) -> bool:
    """严格版：Top-1 是否就命中期望词（用户看到的第一个结果）"""
    if not chunks:
        return False
    return 期望词 in chunks[0].get("text", "") or 期望词 in chunks[0].get("source", "")


async def main():
    print("=" * 60)
    print(f"  检索召回评测：{len(评测题)} 个库内问题 + {len(越界题)} 个库外问题")
    print("=" * 60)

    对旧 = 0   # V1：原问题直接向量检索
    对新 = 0   # V2：改写+混合+RRF
    对旧1 = 0  # V1 严格Top-1
    对新1 = 0  # V2 严格Top-1
    for q, 期望 in 评测题:
        v1_vec = await embed_query(q)
        r1 = vector_store.search(v1_vec, top_k=5, threshold=0) if v1_vec else []
        r2 = await R.retrieve(q, top_k=5, threshold=0)
        对旧 += _命中(r1, 期望)
        对新 += _命中(r2, 期望)
        对旧1 += _top1_hit(r1, 期望)
        对新1 += _top1_hit(r2, 期望)

    n = len(评测题)
    print("-" * 60)
    print("  【库内问题 · Top-5 命中】")
    print(f"  V1 单一向量：{对旧}/{n} = {对旧 / n:.0%}")
    print(f"  V2 混合+改写：{对新}/{n} = {对新 / n:.0%}")
    print("  【库内问题 · 严格 Top-1 命中（用户看到的第一条）】")
    print(f"  V1：{对旧1}/{n} = {对旧1 / n:.0%}")
    print(f"  V2：{对新1}/{n} = {对新1 / n:.0%}")

    # 越界问题：库外主题 → 应返回空（诚实拒答=正确行为）
    诚实对 = 0
    for q in 越界题:
        r = await R.retrieve(q, top_k=3, threshold=0.0)
        if R.is_out_of_scope(q) and not r:  # 拦截生效：返回空 → 会触发"建议问医生"
            诚实对 += 1
        elif not R.is_out_of_scope(q) and not r:
            诚实对 += 1  # 词不达意也算诚实（没硬编）
        else:
            print(f"  ⚠ 「{q}」检索出内容或未拦截，确认是否有越界风险")
    print(f"  【库外问题 · 诚实拒答率】{诚实对}/{len(越界题)} = {诚实对 / len(越界题):.0%}"
          f"（库外不装懂=正确）")
    print("-" * 60)
    return 0


if __name__ == "__main__":
    asyncio.run(main())