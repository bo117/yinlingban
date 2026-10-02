# -*- coding: utf-8 -*-
"""删除图片接口验证（临时脚本，验证完可删）"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.core import image_service
from app.core.image_service import ImageError

IMAGE_DIR = image_service.IMAGE_DIR
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# 1. 造一张假图 + 历史记录
IMAGE_DIR.joinpath("test_del_me.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
hist = image_service.load_history()
hist.insert(0, {"file": "test_del_me.png", "prompt": "测试删除", "model": "m",
                "provider": "p", "size": "1024x1024", "n": 1, "created_at": "2026-09-13 21:00:00"})
image_service.HISTORY_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
assert (IMAGE_DIR / "test_del_me.png").exists()
assert any(h.get("file") == "test_del_me.png" for h in image_service.load_history())
print("[1] 假数据就绪")

# 2. 正常删除：文件 + 记录都没了
r = image_service.delete_image("test_del_me.png")
print("[2] 删除结果:", r)
assert r["success"] and r["file_deleted"] and r["removed_from_history"] == 1
assert not (IMAGE_DIR / "test_del_me.png").exists()
assert not any(h.get("file") == "test_del_me.png" for h in image_service.load_history())

# 3. 再删一次 → 404
try:
    image_service.delete_image("test_del_me.png")
    raise SystemExit("应该抛 404 才对")
except ImageError as e:
    print("[3] 重复删除按 404 拒绝:", e.message, "| status:", e.status)
    assert e.status == 404

# 4. 目录穿越 → 400
for bad in ("../.env", "..\\..\\.env", "a/b.png", ""):
    try:
        image_service.delete_image(bad)
        raise SystemExit(f"应该拒绝 {bad!r}")
    except ImageError as e:
        assert e.status == 400, (bad, e.status)
print("[4] 目录穿越全部按 400 拒绝")

# 5. 真文件存在但历史里没有 → 只删文件也成功
IMAGE_DIR.joinpath("test_orphan.png").write_bytes(b"fake")
r = image_service.delete_image("test_orphan.png")
print("[5] 孤儿文件删除:", r)
assert r["file_deleted"] and r["removed_from_history"] == 0

print("ALL DELETE TESTS PASSED")
