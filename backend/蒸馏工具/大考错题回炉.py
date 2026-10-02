# -*- coding: utf-8 -*-
"""
「银龄伴」大考错题回炉（正式工具）

把 2700 条大考里所有批出的错题（第一轮 96 道 + 回炉轮剩余错题）
按"真实答案"翻回种子数据 → 重跑 一键蒸馏.py 后，线上模型就用上了
这些错题的教训（Reflexion 错题本机制的正式化）。

用法：D:\\yinlingban_env\\Scripts\\python.exe 蒸馏工具\\大考错题回炉.py
之后：python 蒸馏工具\\一键蒸馏.py
"""
import json
from pathlib import Path

工具目录 = Path(__file__).resolve().parent
种子文件 = 工具目录 / "种子数据.json"
报告文件 = 工具目录 / "大评测报告.json"


def main():
    print("=" * 60)
    print("  大考错题回炉：把大考错题翻回种子数据")
    print("=" * 60)

    if not 报告文件.exists():
        print("  ✗ 找不到 大评测报告.json，请先运行 大规模评测.py")
        return

    报告 = json.loads(报告文件.read_text(encoding="utf-8"))
    错题 = list(报告.get("一轮", {}).get("错题", []))
    for 轮 in 报告.get("回炉", []):
        错题.extend(轮.get("剩余错题", []))

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
        json.dumps({"说明": "「银龄伴」训练种子数据：十类 + 小类扩充 + 大考错题回炉（2026-09-08）",
                    "数据": 旧}, ensure_ascii=False),
        encoding="utf-8")
    print(f"  大考错题（去重后）：{len(错题)} 道 → 新回炉 {加} 道（已在种子里吃过的不重复入）")
    print(f"  种子数据：{len(旧)} 条")
    print("  ✓ 完成。下一步运行 一键蒸馏.py 重训线上模型。")


if __name__ == "__main__":
    main()