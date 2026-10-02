# -*- coding: utf-8 -*-
"""
图片生成 REST API（GPT 最新 gpt-image-2.5 系列 / 豆包 Seedream）

  GET  /api/image/status       当前生图配置 + 全目录（密钥不回显）
  POST /api/image/generations  {prompt, size, n, quality} → GPT/豆包 生图
  GET  /api/image/history      最近的生图历史（前端侧栏「生图历史」）
  GET  /api/image/file/{name}  读取已生成的图片文件

本路由只做「HTTP 协议 ↔ 业务」的转换：生图、落盘、历史都在
app.core.image_service（MCP 的 generate_image 工具复用同一个服务）。
网络类异常（超时/连不上/未捕获错误）由 main.py 的全局异常处理器统一转译。
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core import image_service
from app.core.image_service import GenerateParams, ImageError
from app.core.参考图 import MAX_IMAGE_BASE64

router = APIRouter(prefix="/api/image", tags=["图片生成"])


class ImageRequest(BaseModel):
    prompt: str = Field(..., description="画面描述（中文即可，GPT 会自己翻译成绘画语言）")
    size: str = Field("1024x1024", description="尺寸：1024x1024 / 1536x1024 / 1024x1536 / auto")
    n: int = Field(1, description="生成张数 1~4")
    quality: str = Field("auto", description="质量：auto / high / medium / low")
    provider_id: str = Field("", description="生图厂商ID（留空=当前激活）")
    model: str = Field("", description="模型名（留空=当前激活）")
    base_url: str = Field("", description="自定义请求地址（高级）")
    key: str = Field("", description="临时 Key（高级；留空=用已保存的）")
    reference_image: str = Field("", max_length=MAX_IMAGE_BASE64, description="一张参考图，data URL 或 base64")
    reference_file: str = Field("", max_length=160, description="已生成原图的文件名，与 reference_image 二选一")


def _to_http(e: ImageError) -> HTTPException:
    return HTTPException(status_code=e.status,
                         detail={"message": e.message, "solution": e.solution})


@router.get("/status", summary="生图配置与目录")
async def image_status():
    return image_service.status_snapshot()


@router.get("/history", summary="生图历史（最近 60 条）")
async def image_history():
    hist = image_service.load_history()
    for it in hist:
        it["exists"] = (image_service.IMAGE_DIR / it.get("file", "")).exists()
    return {"count": len(hist), "items": hist}


@router.get("/file/{name}", summary="读取生成的图片", include_in_schema=False)
async def image_file(name: str, download: bool = False):
    # 只允许纯文件名，防目录穿越
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail={"message": "非法文件名"})
    p = image_service.IMAGE_DIR / name
    if not p.is_file():
        raise HTTPException(status_code=404, detail={"message": "图片不存在或已被清理"})
    return FileResponse(p, media_type="image/png", filename="银龄伴图片.png" if download else None)


@router.delete("/file/{name}", summary="删除一张已生成的图片",
               description="磁盘文件与历史记录一起删除，不可恢复")
async def image_delete(name: str):
    try:
        return image_service.delete_image(name)
    except ImageError as e:
        raise _to_http(e)


@router.post("/generations", summary="GPT/豆包 生图",
             description="文字生图或携带一张参考图进行修改；新图独立保存并写入历史")
async def generate(req: ImageRequest):
    try:
        return await image_service.generate(GenerateParams(**req.model_dump()))
    except ImageError as e:
        raise _to_http(e)
