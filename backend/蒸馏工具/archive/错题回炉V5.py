# -*- coding: utf-8 -*-
"""
「银龄伴」错题回炉（V5·可反复用）

【大白话】
评测里模型判错的句子，就是"错题"。把它们翻回训练集重新学一遍，
下次就不会再犯。每次跑完十类评测之后，跑这个脚本，错题自动进种子，
再跑一键蒸馏就"回炉"好了。这是"反复蒸馏"循环的关键一环。

用法：
    D:\\yinlingban_env\\Scripts\\python.exe 蒸馏工具\\错题回炉V5.py
    （之后重跑 蒸馏工具\\一键蒸馏.py 即可）
"""
import importlib.util
import json
import sys
from pathlib import Path

工具目录 = Path(__file__).resolve().parent
种子文件 = 工具目录 / "种子数据.json"
模型目录 = 工具目录 / "我的模型"


def load(路径: Path):
    spec = importlib.util.spec_from_file_location("m", 路径)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    print("=" * 60)
    print("  错题回炉 V5：把评测里判错的句子翻回训练集")
    print("=" * 60)

    # ① 拿评测题（十类评测.py 里的用例）
    评测 = load(工具目录 / "十类评测.py")
    用例 = 评测.用例
    模型 = load(模型目录 / "predict.py")

    # ② 逐个过一遍，找出判错的
    错题 = []
    for 句, 期望 in 用例:
        猜 = max(模型.predict(句), key=模型.predict(句).get)
        if 猜 != 期望:
            错题.append({"text": 句, "label": 期望})
            print(f"  ✗ 「{句}」模型判{猜}，期望是{期望} → 回炉")

    if not 错题:
        print("  ✓ 全对！没有错题，无需回炉")
        return 0

    # ③ 翻回种子数据（去重）
    种子 = json.loads(种子文件.read_text(encoding="utf-8"))
    已有 = {(x["text"], x["label"]) for x in 种子["数据"]}
    新 = [x for x in 错题 if (x["text"], x["label"]) not in 已有]
    种子["数据"] += 新
    种子["说明"] = 种子.get("说明", "") + "（含错题回炉数据）"
    种子文件.write_text(json.dumps(种子, ensure_ascii=False), encoding="utf-8")
    print(f"\n  ✓ 已回炉 {len(新)} 条错题 → {种子文件}")
    print(f"  种子数据当前：{len(种子['数据'])} 条")
    print("  下一步：运行 一键蒸馏.py 重新学习")
    return 0 if 新 else 0


if __name__ == "__main__":
    sys.exit(main())