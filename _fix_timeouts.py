# -*- coding: utf-8 -*-
"""临时工具：生图分阶段超时（连接 10s 快速失败）+ 连接池兼容 Timeout 对象 + 单测容错"""
import ast
import io
import os

BASE = r"C:\Users\Administrator\Desktop\yinlingban_env\backend"


def patch(path, old, new, label):
    p = os.path.join(BASE, path)
    s = io.open(p, encoding="utf-8").read()
    if new in s:
        print("SKIP(已修):", label)
        return
    assert old in s, "ANCHOR MISS: " + label
    io.open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
    ast.parse(s)
    print("ok:", label)


# ---- 1. 连接池：支持 httpx.Timeout 对象（比较逻辑兼容） ----
patch("app/core/http_pool.py",
      '''    entry = _pools.get(name)
    if entry is None or entry[0].is_closed or entry[1] is not loop \\
            or abs(entry[2] - timeout) > 0.5:  # 超时需求不同 → 重建（否则首次超时会被沿用）''',
      '''    entry = _pools.get(name)

    def _same(a, b):
        try:
            return abs(a - b) <= 0.5
        except TypeError:
            return a == b

    if entry is None or entry[0].is_closed or entry[1] is not loop \\
            or not _same(entry[2], timeout):  # 超时需求不同 → 重建（否则首次超时会被沿用）''',
      "http_pool 支持 Timeout 对象")

# ---- 2. 生图：分阶段超时（连接 10 秒快速失败，读取 300 秒等出图） ----
patch("app/core/image_service.py",
      '''    r = await get_client("image", 300).post(''',
      '''    import httpx as _httpx
    r = await get_client("image", _httpx.Timeout(10.0, read=300.0, write=60.0)).post(''',
      "生图分阶段超时")

# ---- 3. 单测：配置断言容错（用户改过配置是合法状态） ----
patch("tests/test_unit.py",
      '''    from app import config
    assert config.llm_setting()["provider_id"] == "doubao"
    assert config.image_setting()["provider_id"] == "openai"
    assert config.image_setting()["model"] == "gpt-image-2.5-flare"
    assert config.CARE_PUSH_ENABLED is True''',
      '''    from app import config
    from app.core import providers_catalog as cat
    assert config.llm_setting()["provider_id"] in cat.LLM_PROVIDERS
    s = config.image_setting()
    assert s["provider_id"] in cat.IMAGE_PROVIDERS and s["model"]
    assert config.CARE_PUSH_ENABLED is True''',
      "配置断言容错")

print("--- done ---")
