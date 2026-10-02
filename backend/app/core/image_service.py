# -*- coding: utf-8 -*-
"""
图片生成服务层（GPT 最新 gpt-image 系列 / 豆包 Seedream / OpenAI 兼容中转）

为什么独立成服务（而不是写在路由里）：
  - 图片生成要被两个入口复用：HTTP 路由（前端生图页）与 MCP 工具（generate_image），
    服务层只做业务，路由只做协议转换 —— 官方「Bigger Applications」推荐的结构
  - 非空字段裁剪、尺寸白名单、落盘、历史记录都不该是路由的职责

对外只暴露 generate()，失败抛 ImageError（message/solution 全中文，status 建议值随异常带上）。
"""
import base64
import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from pydantic import BaseModel, Field

from app import config
from app.core import providers_catalog as cat
from app.core.http_pool import get_client
from app.core.参考图 import read_reference, MAX_IMAGE_BASE64

logger = logging.getLogger("yinlingban.image")

# 生成图片落盘目录与历史文件
IMAGE_DIR = Path(config._env("GENERATED_IMAGE_DIR", str(config.BASE_DIR / "data" / "generated_images")))
HISTORY_FILE = IMAGE_DIR / "history.json"
HISTORY_MAX = 60

ALLOWED_SIZES = ("auto", "1024x1024", "1536x1024", "1024x1536")
ALLOWED_QUALITY = ("auto", "high", "medium", "low")


class GenerateParams(BaseModel):
    """一次生图的业务参数（路由模型做过校验后传入；MCP 直接构造）"""
    prompt: str
    size: str = "1024x1024"
    n: int = 1
    quality: str = "auto"
    provider_id: str = ""
    model: str = ""
    base_url: str = ""
    key: str = ""
    reference_image: str = Field("", max_length=MAX_IMAGE_BASE64)
    reference_file: str = Field("", max_length=160)


class ImageError(Exception):
    """生图业务错误（携带建议 HTTP 状态码 + 中文说明）"""

    def __init__(self, message: str, solution: str = "", status: int = 400):
        super().__init__(message)
        self.message = message
        self.solution = solution
        self.status = status


# ------------------------------------------------------------
# 配置解析（与 routes_settings 的目录兜底保持一致）
# ------------------------------------------------------------

def _setting(provider_id: str = "", model: str = "",
             base_url: str = "", key: str = "") -> dict:
    s = config.image_setting()
    if provider_id:
        p = cat.IMAGE_PROVIDERS.get(provider_id.strip().lower())
        if not p:
            raise ImageError(
                f"目录里没有「{provider_id}」这家生图厂商",
                f"可用：{'、'.join(cat.IMAGE_PROVIDERS)}")
        s = config._resolve_setting("image", p["id"], model)
    if model:
        s["model"] = model
    if base_url:
        s["base_url"] = base_url
    if key:
        s["key"] = key
    # Temporary credentials must participate in readiness, just like saved keys.
    s["configured"] = bool(s.get("key"))
    return s


def status_snapshot() -> dict:
    """生图配置 + 目录（密钥不回显），供路由 /api/image/status 复用"""
    s = config.image_setting()
    return {
        "provider_id": s["provider_id"], "provider_name": s["provider_name"],
        "model": s["model"], "base_url": s["base_url"],
        "configured": s["configured"], "site": s.get("site", ""),
        "note": s.get("note", ""),
        "key_hint": cat.IMAGE_PROVIDERS.get(s["provider_id"], {}).get("key_hint", ""),
        "providers": [cat.public_card(p) for p in cat.IMAGE_PROVIDERS.values()],
        "keys_saved": {pid: bool(config.provider_key(pid)) for pid in cat.IMAGE_PROVIDERS},
    }


# ------------------------------------------------------------
# 历史记录（落盘失败不影响生图本身，但必须留痕排查）
# ------------------------------------------------------------

def load_history() -> list:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as e:  # 历史文件损坏时兜底为空，不阻塞生图
        logger.warning("生图历史读取失败（已按空处理）：%s", e)
        return []


def _append_history(item: dict) -> None:
    try:
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        hist = load_history()
        hist.insert(0, item)
        HISTORY_FILE.write_text(
            json.dumps(hist[:HISTORY_MAX], ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        logger.warning("生图历史写入失败（不影响生图结果）：%s", e)


def delete_image(name: str) -> dict:
    """删除一张已生成的图片：磁盘文件 + 历史记录一起清（文件名防目录穿越）"""
    fname = (name or "").strip()
    if not fname or "/" in fname or "\\" in fname or ".." in fname:
        raise ImageError("非法文件名", "只能删除生图历史里的图片文件", status=400)
    deleted_file = False
    p = IMAGE_DIR / fname
    try:
        if p.exists():
            p.unlink()
            deleted_file = True
    except ImageError:
        raise
    except Exception as e:
        logger.warning("删除图片文件失败：%s", e)
        raise ImageError("删除失败，文件可能被占用", "请关闭预览后稍后再试", status=500)
    hist = load_history()
    new_hist = [h for h in hist if h.get("file") != fname]
    removed = len(hist) - len(new_hist)
    if not deleted_file and not removed:
        raise ImageError("图片不存在或已被删除", "刷新一下生图历史再看", status=404)
    if removed:
        try:
            HISTORY_FILE.write_text(
                json.dumps(new_hist, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            logger.warning("生图历史回写失败（文件已删，记录可能残留）：%s", e)
    return {"success": True, "deleted": fname,
            "file_deleted": deleted_file, "removed_from_history": removed}


# ------------------------------------------------------------
# 核心：调 GPT / 豆包 生图
# ------------------------------------------------------------

def _image_url(base: str, edit: bool) -> str:
    parts = urlsplit(base)
    path = parts.path.rstrip("/")
    for ending in ("/images/generations", "/images/edits"):
        if path.endswith(ending):
            path = path[:-len(ending)]
            break
    path += "/images/edits" if edit else "/images/generations"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


async def generate(p: GenerateParams) -> dict:
    prompt = (p.prompt or "").strip()
    if not prompt:
        raise ImageError("提示词是空的", "先描述想要的画面，例如：一只在星空下奔跑的机械狼")

    try:
        reference = await asyncio.to_thread(read_reference, p.reference_image, p.reference_file, IMAGE_DIR)
    except ValueError as exc:
        raise ImageError(str(exc), "请重新添加参考图后重试。", status=422) from exc

    s = _setting(p.provider_id, p.model, p.base_url, p.key)
    if not s["configured"]:
        raise ImageError(
            "还没有配置生图的 API Key（GPT 云端生图用 OpenAI Key，豆包生图用火山方舟 Key）",
            "点「设置」→「图片生成」，粘贴 Key 保存即可")
    if reference and (s["model"].lower() == "dall-e-3" or "seedream-3-0-t2i" in s["model"].lower()):
        raise ImageError("当前模型只支持文字生图", "请选择支持参考图编辑的模型，例如 GPT Image 或 Seedream 4。")

    n = max(1, min(4, p.n or 1))
    size = p.size if p.size in ALLOWED_SIZES else "1024x1024"
    quality = p.quality if p.quality in ALLOWED_QUALITY else "auto"
    # 豆包 Seedream 不认 auto，落到 1024x1024
    if size == "auto" and s["provider_id"] == "doubao":
        size = "1024x1024"

    # 协议显式化：当前目录里的生图厂商都走 OpenAI /images/generations 协议
    #（GPT gpt-image 系列、豆包 Seedream、OpenAI 兼容中转同构）；
    #  未来接其它协议（如 chat 内生图/私有端点）在这里分叉
    if s.get("protocol") not in (None, "", "openai_images"):
        raise ImageError(f"暂不支持生图协议「{s['protocol']}」",
                         "请在设置里改用 GPT / 豆包 / OpenAI 兼容中转")

    payload = {"model": s["model"], "prompt": prompt, "n": n, "size": size}
    if quality != "auto":
        payload["quality"] = quality
    # gpt-image 系列恒返 b64_json（不收 response_format）；豆包/DALL-E 显式要 b64
    if s["model"].startswith(("doubao", "dall-e")):
        payload["response_format"] = "b64_json"

    # 自定义中转地址：用户常省略 http(s):// 前缀，自动补上；没填地址给中文报错
    base = s["base_url"]
    if base and not base.startswith(("http://", "https://")):
        base = "https://" + base
    if not base:
        raise ImageError("还没有填生图请求地址（自定义中转必填）",
                         "地址填成 https://你的中转域名/v1 这种形式")
    # Seedream 将参考图放入 generations 的 image 字段；OpenAI 及兼容网关
    # 使用 multipart /images/edits。完整端点只替换末尾路径，保留网关前缀和参数。
    seedream = s["provider_id"] == "doubao"
    url = _image_url(base, edit=bool(reference) and not seedream)
    import httpx as _httpx
    request = {"json": payload}
    if reference:
        raw, extension, mime = reference
        if seedream:
            payload["image"] = f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
        else:
            request = {"data": {key: str(value) for key, value in payload.items()},
                       "files": {"image": (f"reference.{extension}", raw, mime)}}
    r = await get_client("image", _httpx.Timeout(10.0, read=300.0, write=60.0)).post(
        url, **request, headers={"Authorization": f"Bearer {s['key']}"})

    if r.status_code != 200:
        solution = "请稍后重试，或换个提示词"
        if r.status_code == 401:
            solution = "API Key 无效（401），请到厂商控制台检查"
        elif r.status_code == 429:
            solution = "额度用完或请求太频繁（429），请检查账单"
        elif reference and r.status_code in (400, 404, 405, 415, 422, 501):
            solution = "当前模型或网关可能不支持参考图编辑，请换用支持图片编辑的服务；原图仍然保留"
        elif r.status_code in (400, 404):
            solution = "模型名可能不被支持：请在模型下拉里换一个，或检查自定义网关是否支持该模型"
        raise ImageError(
            f"{'参考图修改' if reference else '生图'}请求失败（HTTP {r.status_code}）",
            f"服务商返回：{r.text[:200]}；{solution}", status=502)

    data = r.json().get("data", [])
    if not data:
        raise ImageError("生图服务没有返回图片", "请稍后重试，或换个模型/提示词", status=502)

    images = []
    ts = time.strftime("%Y%m%d_%H%M%S")
    for i, item in enumerate(data):
        b64 = item.get("b64_json") or ""
        if not b64 and item.get("url"):
            images.append({"url": item["url"], "b64": ""})
            continue
        try:
            IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            fname = f"img_{ts}_{uuid4().hex[:8]}_{i}.png"
            (IMAGE_DIR / fname).write_bytes(base64.b64decode(b64))
            images.append({"b64": b64, "file": fname, "url": f"/api/image/file/{fname}"})
            _append_history({
                "file": fname, "prompt": prompt[:200], "model": s["model"],
                "provider": s["provider_name"], "size": size, "n": n,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "operation": "edit" if reference else "generate",
                "reference_file": p.reference_file,
            })
        except Exception as e:
            logger.warning("生成图片落盘失败（改用内联返回）：%s", e)
            images.append({"b64": b64, "file": "", "url": ""})

    return {
        "success": True,
        "images": images,
        "model": s["model"],
        "provider": s["provider_name"],
        "protocol": s.get("protocol", ""),
        "size": size,
        "quality": quality,
        "prompt": prompt,
        "operation": "edit" if reference else "generate",
    }
