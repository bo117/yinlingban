# -*- coding: utf-8 -*-
"""
社区信息查询工具（角色2：郝英博）

对应任务 3.4：内置社区活动、养老服务、便民电话等本地信息数据库，支持关键词查询

数据来源：data/community_info.json（示例数据由角色3收集维护）
"""
import json
import re

from app import config
from app.db.cache import cache


def _load_community_info() -> dict:
    """加载社区信息库（带缓存，文件修改后重启生效）"""
    cached = cache.get("community_info")
    if cached:
        return cached
    try:
        data = json.loads(config.COMMUNITY_INFO_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    cache.set("community_info", data, ttl=86400)
    return data


# 查询意图 → 信息类别映射
INTENT_CATEGORY_MAP = {
    "活动": "社区活动",
    "合唱": "社区活动",
    "太极": "社区活动",
    "晨练": "社区活动",
    "课堂": "社区活动",
    "义诊": "社区活动",
    "吃饭": "养老服务",
    "食堂": "养老服务",
    "送餐": "养老服务",
    "上门": "养老服务",
    "照料": "养老服务",
    "托管": "养老服务",
    "养老": "养老服务",
    "改造": "养老服务",
    "电话": "便民电话",
    "联系": "便民电话",
    "居委会": "便民电话",
    "物业": "便民电话",
    "维修": "便民电话",
}


def search_community_info(query: str = "") -> dict:
    """
    关键词检索社区信息

    返回：
      {
        "success": True,
        "results": [{"type": "社区活动", "detail": "…", "display": "给老人念的文本"}],
        "message": "完整话术"
      }
    """
    data = _load_community_info()
    if not data:
        return {"success": False,
                "message": "社区信息库还没有数据，等管理员补充一下就好。"}

    query = query.strip()
    results = []

    # 1. 确定检索的类别（命中意图词的类别优先）
    target_categories = []
    for kw, cat in INTENT_CATEGORY_MAP.items():
        if kw in query:
            if cat not in target_categories:
                target_categories.append(cat)

    # 2. 全部类别里做关键词匹配（无类别限制时）
    for category, items in data.items():
        if category in ("说明",):
            continue
        if isinstance(items, dict):
            items = [items]
        for item in items:
            text = json.dumps(item, ensure_ascii=False)
            # 命中判定：类别明确指向 或 文本中有查询词
            category_hit = category in target_categories
            keyword_hit = bool(query) and any(
                ch in text for ch in _extract_keywords(query))
            if category_hit or keyword_hit or not query:
                display = _format_item(category, item)
                results.append({
                    "type": category,
                    "detail": item,
                    "display": display,
                })

    # 限制数量
    results = results[:6]

    if not results:
        return {"success": False,
                "message": "社区信息里暂时没有找到相关内容。您可以问问社区活动、养老服务或者便民电话。"}

    # 生成话术
    parts = [r["display"] for r in results[:4]]
    message = "我帮您打听到了：" + "。".join(parts) + "。还想了解什么，接着问我。"
    return {"success": True, "results": results, "message": message}


def _extract_keywords(query: str) -> list:
    """提取查询中的检索关键词（2字以上的词组 + 单字）"""
    words = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]+", query)
    kws = []
    for w in words:
        kws.append(w)
        if len(w) >= 2:
            kws.extend(w[i:i + 2] for i in range(len(w) - 1))
    return list(set(kws)) or [""]


def _format_item(category: str, item: dict) -> str:
    """把一条信息格式化成给老人听的文本"""
    if category == "社区活动":
        return (f"{item.get('名称', '活动')}，{item.get('时间', '')}"
                f"在{item.get('地点', '')}，{item.get('费用', '免费')}")
    if category == "养老服务":
        return (f"{item.get('名称', '服务')}：{item.get('服务', '')}，"
                f"{item.get('价格', '')}，{item.get('条件', '')}")
    if category == "便民电话":
        return f"{item.get('名称', '')}的电话是{item.get('电话', '')}（{item.get('说明', '')}）"
    return json.dumps(item, ensure_ascii=False)
