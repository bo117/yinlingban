# -*- coding: utf-8 -*-
"""列一下网关支持的 image 模型（临时脚本，验证完可删）"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import httpx
from app import config


async def main():
    key = config.provider_key("custom")
    async with httpx.AsyncClient(timeout=15, trust_env=False) as c:
        r = await c.get("https://sub2.hhlai.xyz/v1/models",
                        headers={"Authorization": f"Bearer {key}"})
    ids = [m.get("id", "") for m in r.json().get("data", [])]
    img = [i for i in ids if any(k in i.lower() for k in ("image", "dall", "flux", "seedream", "draw", "paint"))]
    print("HTTP", r.status_code, "| 总模型数:", len(ids))
    print("生图相关模型:")
    for i in img:
        print("  -", i)
    print("含 gpt-image-2.5-flare:", "gpt-image-2.5-flare" in ids)


asyncio.run(main())
