# -*- coding: utf-8 -*-
"""
「银龄伴」严格考试错题回炉（真实泛化错题 → 翻回教材重学）

与「大考错题回炉」的区别（这点很关键）：
  大考错题   = 留出法考卷的错题。考卷虽没参与训练，但语料与训练同源、句式相近，
               实测回炉时 73 道错题里有 73 道已在种子里 → 新回炉 0 道，收益为零。
  严格考试错 = 全部手写、模型从没见过的句子。答错就是真的"没学会"，
               翻回教材重学才能补上真实泛化的短板（急躁型、依赖型尤其缺）。

用法：D:\\yinlingban_env\\Scripts\\python.exe 蒸馏工具\\严格考试错题回炉.py
之后：python 蒸馏工具\\一键蒸馏.py（重训） → 严格考试.py（复考）
"""
import json
from pathlib import Path

工具目录 = Path(__file__).resolve().parent
种子文件 = 工具目录 / "种子数据.json"
错题文件 = 工具目录 / "严格考试错题.json"


def main():
    print("=" * 62)
    print("  严格考试错题回炉：把手写句错题翻回种子数据")
    print("=" * 62)

    if not 错题文件.exists():
        print("  ✗ 找不到 严格考试错题.json，请先运行 严格考试.py")
        return

    报告 = json.loads(错题文件.read_text(encoding="utf-8"))
    错题 = 报告.get("错题", [])
    if not 错题:
        print(f"  ✓ 上次严格考试满分（{报告.get('答对')}/{报告.get('总句数')}），无需回炉")
        return

    载 = json.loads(种子文件.read_text(encoding="utf-8"))
    旧 = 载["数据"]
    seen = {(x["text"], x["label"]) for x in 旧}

    加 = 0
    for e in 错题:
        t, label = e["text"], e["真答案"]
        if (t, label) not in seen:
            旧.append({"text": t, "label": label})
            seen.add((t, label))
            加 += 1

    种子文件.write_text(
        json.dumps({"说明": "「银龄伴」训练种子数据：十类 + 小类扩充 + 大考/严格考试错题回炉（2026-09-10）",
                    "数据": 旧}, ensure_ascii=False),
        encoding="utf-8")
    print(f"  上次成绩：{报告.get('答对')}/{报告.get('总句数')} = {报告.get('正确率')}")
    print(f"  错题 {len(错题)} 道 → 新回炉 {加} 道（已在种子里的不重复入）")
    print(f"  种子数据：{len(旧)} 条")
    print("  ✓ 完成。下一步：一键蒸馏.py 重训 → 严格考试.py 复考")


if __name__ == "__main__":
    main()
