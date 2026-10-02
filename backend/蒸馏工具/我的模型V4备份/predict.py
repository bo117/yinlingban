# -*- coding: utf-8 -*-
"""
「银龄伴」蒸馏模型·推理器（由一键蒸馏.py自动生成，勿手改）
后端通过它调用您的模型：predict(老人的话) → 十类概率
"""
import json
import re
from collections import Counter
from pathlib import Path

_模型文件 = Path(__file__).resolve().parent / "模型.json"
_模型 = json.loads(_模型文件.read_text(encoding="utf-8"))

# 云端地址：想用云端模型时填这里（POST接口，收 text 字段，返回十类概率JSON）
# 留空 = 用本地模型；云端失败自动切回本地
云端地址 = ""


def predict(text: str) -> dict:
    """后端调用的唯一入口：返回十类概率，如 {"孤独型": 0.7, ...}"""
    if 云端地址:
        try:
            import urllib.request
            req = urllib.request.Request(
                云端地址,
                data=json.dumps({"text": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            if isinstance(result, dict):
                return result
        except Exception:
            pass  # 云端失败 → 退回本地模型
    return _本地预测(text)


def _本地预测(text: str) -> dict:
    """V3 推理：TF-IDF 贝叶斯 + 语义信号 + 转折感知（与训练逻辑一致）"""
    import math

    五种类型 = _模型["类型列表"]
    _信号 = _模型.get("语义信号", {})
    _信号权重 = _模型.get("信号权重", 3.0)
    _转折权重 = _模型.get("转折权重", 2.0)

    def 分词(s):
        s = re.sub(r"\s+", " ", s)
        tokens = []
        for w in re.findall(r"[A-Za-z0-9]+", s.lower()):
            tokens.append(w)
        for seq in re.findall(r"[\u4e00-\u9fa5]+", s):
            if len(seq) == 1:
                tokens.append(seq)
            else:
                tokens.extend(seq[i:i + 2] for i in range(len(seq) - 1))
                tokens.append(seq)
        return tokens

    def 提取特征(s):
        特征 = 分词(s)
        # 转折感知（与训练侧一致）
        转折词 = ["可照样", "可挡不住", "可还是", "可我不", "可我", "可我说", "可挡不",
                 "但是", "可是", "然而", "其实", "照样", "却还", "却"]
        for 词 in 转折词:
            idx = s.find(词)
            if idx >= 0:
                后半 = s[idx + len(词):]
                if len(后半) >= 3:
                    for t in 分词(后半):
                        特征.append(f"TURN:{t}")
                    for 类型, 信号表 in _信号.items():
                        for 信号 in 信号表:
                            if 信号 in 后半:
                                特征.append(f"TURN:SIG:{类型}:1")
                break
        # 全句语义信号
        for 类型, 信号表 in _信号.items():
            命中 = sum(1 for 信号 in 信号表 if 信号 in s)
            if 命中 > 0:
                特征.append(f"SIG:{类型}:{min(命中, 3)}")
        return 特征

    N = _模型["样本总数"]
    文档频率 = _模型.get("文档频率", {})
    词频 = {t: Counter(c) for t, c in _模型["词频"].items()}
    词表大小 = max(sum(len(c) for c in 词频.values()), 1)

    特征 = 提取特征(text)
    加权 = Counter()
    for f in 特征:
        idf = math.log((N + 1) / (文档频率.get(f, 0) + 1)) + 1.0
        加权[f] += idf
    for f in 加权:
        if f.startswith("SIG:"):
            加权[f] *= _信号权重
        elif f.startswith("TURN:"):
            加权[f] *= _转折权重

    分数 = {}
    for 类型 in 五种类型:
        先验 = (_模型["类计数"].get(类型, 0) + 1) / (N + 5)
        log分 = math.log(先验)
        该类词频 = 词频.get(类型, Counter())
        该类总词 = _模型["总词数"].get(类型, 0)
        for f, 权 in 加权.items():
            p = (该类词频.get(f, 0) + 0.5) / (该类总词 + 0.5 * 词表大小)
            log分 += 权 * math.log(p)
        分数[类型] = log分
    最高 = max(分数.values())
    exp分 = {t: math.exp(s - 最高) for t, s in 分数.items()}
    总和 = sum(exp分.values())
    return {t: round(v / 总和, 4) for t, v in exp分.items()}
