# -*- coding: utf-8 -*-
"""真实生图一次（最小成本验证，验证完可删）"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.core import image_service
from app.core.image_service import GenerateParams


async def main():
    r = await image_service.generate(GenerateParams(
        prompt="一朵向日葵，简笔画风格",
        size="1024x1024", n=1, quality="low"))
    print("success:", r["success"])
    print("model:", r["model"], "| provider:", r["provider"], "| size:", r["size"])
    for im in r["images"]:
        print("image:", {"file": im.get("file"), "url": im.get("url"), "b64_len": len(im.get("b64") or "")})


asyncio.run(main())
