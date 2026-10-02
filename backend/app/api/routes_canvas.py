"""Persist a note canvas with optimistic revisions to prevent silent overwrites."""
import json
import io
import re
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app import config
from app.db.database import get_db
from app.db.models import CanvasBoard, User

router = APIRouter(prefix="/api/users/{user_id}/canvas", tags=["便签画布"])
IMAGE_NAME = re.compile(r"^[0-9a-f]{32}\.jpg$")
MEDIA_DIR = Path(config._env("CANVAS_MEDIA_DIR", str(config.BASE_DIR / "data" / "canvas-media")))


def image_path(user_id: int, name: str) -> Path:
    if not IMAGE_NAME.fullmatch(name):
        raise HTTPException(404, "图片不存在")
    return MEDIA_DIR / str(user_id) / name


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    text: str = Field("", max_length=10000)
    x: float = Field(ge=-100000, le=100000)
    y: float = Field(ge=-100000, le=100000)
    color: Literal["paper", "yellow", "rust"] = "paper"
    date: str = Field("", pattern=r"^$|^\d{4}-(0[1-9]|1[0-2])-([0-2]\d|3[01])$")
    images: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("date")
    @classmethod
    def valid_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def valid_images(self):
        if len(set(self.images)) != len(self.images) or any(not IMAGE_NAME.fullmatch(name) for name in self.images):
            raise ValueError("便签图片名称无效或重复")
        return self


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    source: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    target: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field("", max_length=80)
    date: str = Field("", pattern=r"^$|^\d{4}-(0[1-9]|1[0-2])-([0-2]\d|3[01])$")

    @field_validator("date")
    @classmethod
    def valid_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value


class BoardUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    cards: list[Card] = Field(max_length=200)
    links: list[Link] = Field(default_factory=list, max_length=400)

    @model_validator(mode="after")
    def unique_and_bounded(self):
        if len({card.id for card in self.cards}) != len(self.cards):
            raise ValueError("便签 ID 重复")
        if sum(len(card.text) for card in self.cards) > 300000:
            raise ValueError("画布文字总量超过 30 万字")
        ids = {card.id for card in self.cards}
        if len({link.id for link in self.links}) != len(self.links):
            raise ValueError("连线 ID 重复")
        if any(link.source not in ids or link.target not in ids or link.source == link.target for link in self.links):
            raise ValueError("连线必须连接两条不同且存在的线索")
        if len({(link.source, link.target) for link in self.links}) != len(self.links):
            raise ValueError("不能重复连接同一对线索")
        return self


def require_user(db, user_id):
    if db.get(User, user_id) is None:
        raise HTTPException(404, "用户不存在")


@router.get("")
def read_board(user_id: int, db: Session = Depends(get_db)):
    require_user(db, user_id)
    row = db.get(CanvasBoard, user_id)
    if row is None:
        return {"revision": 0, "cards": [], "links": []}
    document = json.loads(row.document)
    return {"revision": row.revision, "cards": document["cards"], "links": document.get("links", [])}


@router.put("")
def save_board(user_id: int, data: BoardUpdate, db: Session = Depends(get_db)):
    require_user(db, user_id)
    for card in data.cards:
        for name in card.images:
            if not image_path(user_id, name).is_file():
                raise HTTPException(422, "便签照片不存在或不属于当前用户")
    document = json.dumps({"cards": [card.model_dump() for card in data.cards],
                           "links": [link.model_dump() for link in data.links]}, ensure_ascii=False)
    changed = db.query(CanvasBoard).filter_by(user_id=user_id, revision=data.revision).update(
        {"document": document, "revision": data.revision + 1}, synchronize_session=False)
    if not changed:
        if data.revision != 0 or db.get(CanvasBoard, user_id):
            raise HTTPException(409, "画布已在其他窗口更新，请先保存本地副本再加载最新内容。")
        db.add(CanvasBoard(user_id=user_id, document=document, revision=1))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "画布已在其他窗口更新，请重新加载。")
    return {"revision": data.revision + 1}


@router.post("/images", status_code=201)
async def upload_image(user_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    require_user(db, user_id)
    raw = await file.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "每张照片不能超过 5 MB")
    taken = ""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ("JPEG", "PNG", "WEBP") or source.width * source.height > 24_000_000:
                raise ValueError("不支持的图片格式或图片尺寸过大")
            taken = _photo_taken_date(source)
            photo = ImageOps.exif_transpose(source)
            photo.thumbnail((1600, 1600))
            output = io.BytesIO()
            photo.convert("RGB").save(output, "JPEG", quality=85, optimize=True)
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "请选择有效的 JPG、PNG 或 WebP 照片") from exc
    name = f"{uuid4().hex}.jpg"
    path = image_path(user_id, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output.getvalue())
    return {"name": name, "taken": taken}


def _photo_taken_date(source) -> str:
    """从照片 EXIF 里读取拍摄时间，返回 YYYY-MM-DD；读不到则返回空字符串。"""
    tags = (36867, 306)  # DateTimeOriginal, DateTime
    try:
        exif = source.getexif()
        raw_value = None
        for tag in tags:
            raw_value = exif.get(tag)
            if raw_value:
                break
        if not raw_value:
            exif_ifd = exif.get_ifd(0x8769)  # Exif IFD
            raw_value = exif_ifd.get(36867) or exif_ifd.get(306)
    except Exception:
        return ""
    if not isinstance(raw_value, str) or ":" not in raw_value:
        return ""
    try:
        parts = raw_value.strip().split()[0].split(":")  # "YYYY:MM:DD HH:MM:SS"
        if len(parts) < 3:
            return ""
        parsed = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return ""
    return parsed.isoformat()


@router.get("/images/{name}")
def read_image(user_id: int, name: str, db: Session = Depends(get_db)):
    require_user(db, user_id)
    path = image_path(user_id, name)
    if not path.is_file():
        raise HTTPException(404, "图片不存在")
    return FileResponse(path, media_type="image/jpeg", headers={"X-Content-Type-Options": "nosniff"})
