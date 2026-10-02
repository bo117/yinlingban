# -*- coding: utf-8 -*-
"""DELETE /api/image/file/{name} 路由级验证（临时脚本，验证完可删）"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from fastapi.testclient import TestClient
from app.main import app
from app.core import image_service

client = TestClient(app)

# 造一张待删假图 + 历史记录
IMAGE_DIR = image_service.IMAGE_DIR
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.joinpath("test_route_del.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
hist = image_service.load_history()
if not any(h.get("file") == "test_route_del.png" for h in hist):
    hist.insert(0, {"file": "test_route_del.png", "prompt": "路由删除测试", "model": "m",
                    "provider": "p", "size": "1024x1024", "n": 1, "created_at": "2026-09-13 21:05:00"})
    image_service.HISTORY_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")

# 1. DELETE 正常删除
r = client.delete("/api/image/file/test_route_del.png")
print("[1] DELETE status:", r.status_code, "| body:", r.json())
assert r.status_code == 200 and r.json()["success"]
assert not (IMAGE_DIR / "test_route_del.png").exists()
assert not any(h.get("file") == "test_route_del.png" for h in image_service.load_history())

# 2. 历史接口里也不再有它
r = client.get("/api/image/history")
files = [i.get("file") for i in r.json()["items"]]
print("[2] 历史现存条数:", len(files), "| 含已删文件:", "test_route_del.png" in files)
assert "test_route_del.png" not in files

# 3. 删除不存在的文件 → 404 + 中文 detail
r = client.delete("/api/image/file/no_such_file.png")
print("[3] 不存在文件 status:", r.status_code, "| detail:", r.json().get("detail"))
assert r.status_code == 404

print("ROUTE TESTS PASSED")
