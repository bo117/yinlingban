# -*- coding: utf-8 -*-
"""
语音合成服务（角色2 · 统一 TTS 链路）

需求约定：TTS 可自定义，但全部统一接「火山引擎」或「GPT（OpenAI）」两大家，
另留一个 OpenAI 兼容的「自定义」位（硅基流动 CosyVoice / 内网网关等）。

协议实现：
  volc_tts    火山引擎 HTTP 一次性合成（POST /api/v1/tts，返回 base64 mp3）
              Key 格式：AppID:AccessToken（只填 AccessToken 时 AppID 走 VOLC_TTS_APPID）
              M4/M5/F4/F5 大模型音色（*_mars_bigtts）自动降级到 v3 流式接口
  openai_tts  POST {base_url}/audio/speech（GPT gpt-4o-mini-tts / tts-1 / CosyVoice 等）
              返回二进制音频，这里统一转 base64

对外只暴露一个函数：synthesize() → {success, audio_base64, format, ...}，
失败一律中文 message + solution，不抛英文堆栈。
"""
import base64
import json
import uuid

from app import config
from app.core.http_pool import get_client


class TTSError(Exception):
    def __init__(self, message: str, solution: str = ""):
        super().__init__(message)
        self.message = message
        self.solution = solution


def _parse_volc_key(key: str):
    """火山引擎 Key：AppID:AccessToken 两段式；只有一段时 AppID 从 .env 找"""
    key = (key or "").strip()
    if ":" in key:
        appid, token = key.split(":", 1)
        return appid.strip(), token.strip()
    return config.VOLC_TTS_APPID.strip(), key


def _b64_of(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


async def _volc_tts_v1(text: str, voice: str, speed: float, key: str) -> str:
    """火山引擎 v1 一次性合成 → base64 mp3（经典音色 BV001/BV002 等）"""
    appid, token = _parse_volc_key(key)
    if not token:
        raise TTSError("火山引擎的 AccessToken 没有配置",
                       "在设置里把 Key 填成 AppID:AccessToken（控制台 → 语音技术 → 应用管理）")
    payload = {
        "app": {"appid": appid, "token": "access_token", "cluster": "volcano_tts"},
        "user": {"uid": "yinlingban-user"},
        "audio": {"voice_type": voice, "encoding": "mp3",
                  "speed_ratio": max(0.2, min(3.0, speed or 1.0))},
        "request": {"reqid": uuid.uuid4().hex, "text": text,
                    "text_type": "plain", "operation": "query"},
    }
    r = await get_client("tts", 60).post(
        config.VOLC_TTS_BASE_URL.rstrip("/") or "https://openspeech.bytedance.com/api/v1/tts",
        json=payload, headers={"Authorization": f"Bearer;{token}"})
    try:
        data = r.json()
    except Exception:
        raise TTSError(f"火山引擎返回了无法解析的内容（HTTP {r.status_code}）",
                       f"返回片段：{r.text[:150]}")
    if data.get("code") != 3000:
        # 3001/3005 多为音色不存在或未开通该音色
        raise TTSError(f"火山引擎合成失败（code {data.get('code')}：{data.get('message', '')}）",
                       "经典音色（F1~F3/M1~M3）需开通「语音合成」；大模型音色（F4/F5/M4/M5）"
                       "需在同应用下开通「大模型语音合成」，或先换经典音色试听")
    return data.get("data") or ""


async def _volc_tts_v3(text: str, voice: str, speed: float, key: str) -> str:
    """火山引擎 v3 大模型语音合成（流式逐行 JSON，这里聚合为一个 mp3）"""
    appid, token = _parse_volc_key(key)
    if not token:
        raise TTSError("火山引擎的 AccessToken 没有配置",
                       "在设置里把 Key 填成 AppID:AccessToken（控制台 → 语音技术 → 应用管理）")
    reqid = uuid.uuid4().hex
    payload = {
        "user": {"uid": "yinlingban-user"},
        "req_params": {
            "text": text,
            "speaker": voice,
            "audio_params": {"format": "mp3", "sample_rate": 24000},
            "additions": {"reqid": reqid},
        },
    }
    audio_b64_parts = []
    try:
        async with get_client("tts", 60).stream(
            "POST",
            (config.VOLC_TTS_V3_URL or
             "https://openspeech.bytedance.com/api/v3/tts/unidirectional/streaming"),
            json=payload,
            headers={
                "X-Api-App-Key": appid,
                "X-Api-Access-Key": token,
                "X-Api-Resource-Id": config.VOLC_TTS_V3_RESOURCE_ID,
                "X-Api-Request-Id": reqid,
            },
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread())[:200]
                raise TTSError(f"火山引擎大模型音色合成失败（HTTP {resp.status_code}）",
                               f"返回片段：{body.decode('utf-8', 'ignore')}")
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                # 逐行 JSON 里挖 base64 音频（字段随版本可能是 data / audio.data）
                b64 = item.get("data") or ""
                if not b64 and isinstance(item.get("audio"), dict):
                    b64 = item["audio"].get("data") or ""
                if b64:
                    audio_b64_parts.append(b64)
    except TTSError:
        raise
    except Exception as e:
        raise TTSError(f"火山引擎大模型音色连接失败（{e}）", "请检查网络后重试")
    if not audio_b64_parts:
        raise TTSError("火山引擎大模型音色没有返回音频",
                       "请确认应用已开通「大模型语音合成」并勾选了该音色")
    return "".join(audio_b64_parts)


async def _openai_compatible_tts(base_url: str, model: str, key: str,
                                 text: str, voice: str, speed: float) -> str:
    """OpenAI 兼容 /audio/speech（GPT gpt-4o-mini-tts、CosyVoice2 等）→ base64 mp3"""
    if not key:
        raise TTSError("还没有配置这家 TTS 的 API Key",
                       "点「⚙️ 密钥设置」→「语音合成」，把 Key 填进去保存即可")
    payload = {"model": model, "input": text, "voice": voice or "alloy",
               "response_format": "mp3", "speed": max(0.25, min(4.0, speed or 1.0))}
    r = await get_client("tts", 120).post(
        f"{base_url.rstrip('/')}/audio/speech",
        json=payload, headers={"Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        # OpenAI 报错是 JSON；兼容网关可能返回纯文本
        hint = r.text[:200]
        solution = "检查 Key / 模型名 / 音色名；若用自定义地址，确认该服务支持 /audio/speech 接口"
        if r.status_code == 401:
            solution = "API Key 无效（401），请到服务商控制台重新生成"
        elif r.status_code == 404:
            solution = "请求地址不对（404）：确认填的是 .../v1 这类根地址，接口会自动拼 /audio/speech"
        raise TTSError(f"TTS 合成失败（HTTP {r.status_code}）", f"服务商返回：{hint}；{solution}")
    return _b64_of(r.content)


async def synthesize(text: str, voice: str = "", model: str = "",
                     speed: float = None, provider_id: str = "",
                     base_url_override: str = "", key_override: str = "") -> dict:
    """统一合成入口：返回 {success, audio_base64, format, provider, model, voice}"""
    text = (text or "").strip()
    if not text:
        raise TTSError("要合成的文本是空的", "先在输入框里写点要念的文字")

    if provider_id:
        from app.core import providers_catalog as cat
        p = cat.TTS_PROVIDERS.get(provider_id.strip().lower())
        if not p:
            raise TTSError(f"目录里没有「{provider_id}」这家 TTS",
                           f"可用：{'、'.join(cat.TTS_PROVIDERS)}")
        s = config._resolve_setting("tts", p["id"], model)
        if base_url_override:
            s["base_url"] = base_url_override
        if key_override:
            s["key"] = key_override
    else:
        s = config.tts_setting()
        if model:
            s["model"] = model
        if base_url_override:
            s["base_url"] = base_url_override
        if key_override:
            s["key"] = key_override

    voice = (voice or s.get("voice") or "").strip()
    speed = float(speed if speed is not None else s.get("speed") or 1.0)
    protocol = s["protocol"]

    if protocol == "volc_tts":
        # 大模型音色走 v3 流式；经典音色走 v1 一次性
        if "_mars" in voice:
            audio = await _volc_tts_v3(text, voice, speed, s["key"])
        else:
            audio = await _volc_tts_v1(text, voice or "BV001_streaming", speed, s["key"])
    else:  # openai_tts（含 GPT 与自定义兼容服务）
        base_url = s.get("base_url") or config.TTS_CUSTOM_BASE_URL
        if not base_url:
            raise TTSError("自定义 TTS 还没有填请求地址",
                           "点「设置」→「语音合成」把地址填上（如 https://api.siliconflow.cn/v1）")
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url  # 用户常省略协议，自动补
        from app.core.声音克隆 import fish_base, speech, CloneError
        fish_url = fish_base(base_url)
        if fish_url:
            try:
                audio = await speech(fish_url,s['key'],text,voice,speed)
            except CloneError as exc:
                raise TTSError(str(exc),'请检查声音克隆中的音色和账户配置。') from exc
            s['model'] = '音色默认模型'
        else:
            audio = await _openai_compatible_tts(
                base_url, s["model"] or "gpt-4o-mini-tts", s["key"], text, voice, speed)

    return {
        "success": True,
        "audio_base64": audio,
        "format": "mp3",
        "provider": s["provider_name"],
        "provider_id": s["provider_id"],
        "model": s["model"],
        "voice": voice,
        "speed": speed,
    }


def list_voices(provider_id: str = "") -> list:
    """某家（默认当前激活）TTS 的音色表，供前端音色胶囊渲染"""
    pid = (provider_id or config.TTS_PROVIDER_ID or "volcengine").strip().lower()
    from app.core import providers_catalog as cat
    p = cat.TTS_PROVIDERS.get(pid) or {}
    return p.get("voices", [])
