# -*- coding: utf-8 -*-
"""
「银龄伴」模型自检（查训练/推理不一致bug）

【大白话】训练时候教的是一套分词，预测时候用的可能是另一套——
这种隐蔽bug会让模型"训练时100%、真用起来拉胯"。
自检方法：拿训练集里的句子喂给模型预测，如果连教过的都认不出来，说明训练/推理代码不一致。

用法：D:\\yinlingban_env\\Scripts\\python.exe 蒸馏工具\\自检.py
"""
import importlib.util
import random
import sys
from collections import Counter
from pathlib import Path

工具目录 = Path(__file__).resolve().parent

# 加载模型推理器
spec = importlib.util.spec_from_file_location("m", 工具目录 / "我的模型" / "predict.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# 加载训练数据（随机抽1000条做自检）
import json
数据 = json.loads((工具目录 / "种子数据.json").read_text(encoding="utf-8"))["数据"]
随机 = random.Random(7)
抽样 = 随机.sample(数据, min(1000, len(数据)))


def main():
    print("=" * 56)
    print(f"  模型自检：训练集抽 1000 条喂给模型")
    print("=" * 56)

    # 训练集内准确率（查一致性）
    对 = 0
    分错 = Counter()
    错例 = []
    for 条 in 抽样:
        概率 = m.predict(条["text"])
        猜 = max(概率, key=概率.get)
        真实 = 条["label"]
        if 猜 == 真实:
            对 += 1
        else:
            分错[真实 + "→" + 猜] += 1
            错例.append((条["text"], 真实, 猜))

    正确率 = 对 / len(抽样)
    print(f"  训练集内正确率：{对}/{len(抽样)} = {正确率:.0%}")

    if 正确率 >= 0.99:
        print("  ✓ 一致性良好：训练和推理用的是同一套逻辑，没有隐蔽bug")
    elif 正确率 >= 0.95:
        print("  ⚠ 轻微不一致：少数句子判错，需要检查分词/特征差异")
    else:
        print("  ✗ 严重不一致：训练和推理代码逻辑不同，存在隐蔽BUG！")
        print("    检查点：训练侧 提取特征() 是否和 推理器 predict.py 里的完全一致")
        print("\n  错误分类明细：")
        for k, v in 分错.most_common(10):
            print(f"    {k}：{v} 条")
        for 句, 真, 猜 in 错例[:10]:
            print(f"    ✗「{句}」→{猜}（应{真}）")
    return 0 if 正确率 >= 0.99 else 1


if __name__ == "__main__":
    sys.exit(main())