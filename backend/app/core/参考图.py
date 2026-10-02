"""校验上传的参考图或本机生成图片，保留原始图片数据供编辑接口使用。"""
import base64
import binascii
import io
import re
from pathlib import Path

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BASE64 = ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 100


def read_reference(image_data: str, filename: str, directory: Path):
    if not image_data and not filename:
        return None
    if image_data and filename:
        raise ValueError("一次只能使用一张参考图，请移除多余图片。")
    if filename:
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp)", filename, re.I):
            raise ValueError("参考图片名称无效，请从历史图片中重新选择。")
        path = (directory / filename).resolve()
        if path.parent != directory.resolve() or not path.is_file():
            raise ValueError("原图不存在或已被删除，请重新选择参考图。")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError("参考图不能超过 10 MB。")
        raw = path.read_bytes()
    else:
        # 前端 FileReader 产生 data URL；同时接受接口直接提交纯 base64。
        if image_data.startswith("data:"):
            header, separator, image_data = image_data.partition(",")
            if not separator or header.lower() not in (
                    "data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64"):
                raise ValueError("请选择 PNG、JPG 或 WebP 图片。")
        if len(image_data) > MAX_IMAGE_BASE64:
            raise ValueError("参考图不能超过 10 MB。")
        try:
            raw = base64.b64decode(image_data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("参考图数据无效，请重新添加图片。") from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("参考图不能为空，且不能超过 10 MB。")
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image_format = image.format
            if image_format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("请选择 PNG、JPG 或 WebP 图片。")
            if image.width * image.height > 25_000_000:
                raise ValueError("参考图分辨率过大，请缩小到 2500 万像素以内。")
            image.verify()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("参考图无法读取，请重新选择有效图片。") from exc
    extension, mime = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"),
                       "WEBP": ("webp", "image/webp")}[image_format]
    return raw, extension, mime
