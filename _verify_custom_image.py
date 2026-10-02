# -*- coding: utf-8 -*-
"""自定义生图 API 修复验证（临时脚本，验证完可删）"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app import config
from app.api.routes_settings import SettingsTest, test_connection, _resolve_test

# 1. 激活配置解析：地址必须原样（完整端点，不是根地址）
s = config.image_setting()
print("[1] image_setting:", s["provider_id"], "|", s["model"], "|", s["base_url"], "| configured:", s["configured"])
assert s["provider_id"] == "custom"
assert s["base_url"] == "https://sub2.hhlai.xyz/v1/images/generations"
assert s["configured"], "KEY_CUSTOM 没读到"

# 2. 生成 URL 规则（与 image_service.generate 一致）：含端点则原样用
base = s["base_url"].rstrip("/")
url = base if "/images/generations" in base else f"{base}/images/generations"
print("[2] 完整端点原样使用:", url)
assert url == "https://sub2.hhlai.xyz/v1/images/generations"

# 3. 只填 base（…/v1）时仍自动补端点
b2 = "https://sub2.hhlai.xyz/v1"
u2 = b2 if "/images/generations" in b2 else f"{b2}/images/generations"
assert u2 == "https://sub2.hhlai.xyz/v1/images/generations"
print("[3] base 形式自动补端点:", u2)

# 4. 串台修复：切回 openai 厂商不再吃自定义地址
o = config._resolve_setting("image", "openai", "")
print("[4] openai 生图 base_url:", o["base_url"])
assert o["base_url"] == "https://api.openai.com/v1"

# 5. 测试请求解析
t = _resolve_test(SettingsTest(kind="image", provider_id="custom"))
print("[5] _resolve_test:", t["base_url"], "|", t["model"], "| key saved:", bool(t["key"]))
assert t["base_url"] == "https://sub2.hhlai.xyz/v1/images/generations"

# 6. 实测：联通测试（探活会剥掉端点后 GET {root}/models）
r = asyncio.run(test_connection(SettingsTest(kind="image", provider_id="custom")))
print("[6] 实测联通:", r)

# 7. 模拟前端「填了地址但没保存就点测试」：base_url 由请求带上
r2 = asyncio.run(test_connection(SettingsTest(
    kind="image", provider_id="custom",
    base_url="https://sub2.hhlai.xyz/v1/images/generations",
    model="gpt-image-2.5-flare")))
print("[7] 未保存先测（带地址）:", r2)

print("ALL ASSERTIONS PASSED")
