# -*- coding: utf-8 -*-
"""
语音合成 REST API（统一火山引擎 / GPT，可自定义）

  GET  /api/tts/status    当前 TTS 配置 + 全目录 + 音色表（密钥不回显）
  POST /api/tts/synthesize  {text, voice?, speed?, provider_id?, model?}
                          → {audio_base64, format:"mp3", provider, model, voice}

前端「语音合成」页与语音通话播报都走这里；浏览器 Web Speech 只是兜底。
"""
from fastapi import APIRouter, HTTPException, File, UploadFile, Form
import httpx
from pydantic import BaseModel, Field

from app import config
from app.core import providers_catalog as cat
from app.core import tts_service
from app.core.tts_service import TTSError
from app.core import 声音克隆 as voice_clone

router = APIRouter(prefix="/api/tts", tags=["语音合成 TTS"])


@router.get('/clone/voices', summary='查询个人克隆音色')
async def clone_voices():
    try:
        return {'voices':await voice_clone.list_voices()}
    except voice_clone.CloneError as exc:
        raise HTTPException(exc.status, {'message':str(exc)}) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, {'message':'音色列表暂时无法读取，请检查网络后刷新。'}) from exc


@router.post('/clone', summary='上传录音创建私有音色')
async def clone_voice(name: str = Form(...,max_length=80), reference_text: str = Form('',max_length=5000), audio: UploadFile = File(...)):
    try:
        raw = await audio.read(voice_clone.MAX_AUDIO+1)
        return {'success':True,'voice':await voice_clone.create_voice(name,raw,audio.filename,reference_text)}
    except voice_clone.CloneError as exc:
        raise HTTPException(exc.status, {'message':str(exc)}) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, {'message':'未能确认音色创建结果。请先刷新音色列表，确认是否已创建成功，避免重复提交。'}) from exc
    finally:
        await audio.close()


class TTSRequest(BaseModel):
    text: str = Field(..., description="要合成的文本")
    voice: str = Field("", description="音色ID（目录 voices 里的 id，留空=默认音色）")
    speed: float = Field(0, description="语速 0.5~2.0（0=用配置默认）")
    provider_id: str = Field("", description="TTS厂商ID（留空=当前激活）")
    model: str = Field("", description="模型名（留空=当前激活）")
    base_url: str = Field("", description="自定义请求地址（高级；留空=目录预置）")
    key: str = Field("", description="临时 Key（高级；留空=用已保存的）")


def _status() -> dict:
    s = config.tts_setting()
    return {
        "provider_id": s["provider_id"], "provider_name": s["provider_name"],
        "model": s["model"], "voice": s.get("voice", ""), "speed": s.get("speed", 1.0),
        "base_url": s["base_url"], "configured": s["configured"],
        "site": s.get("site", ""), "note": s.get("note", ""),
        "key_hint": cat.TTS_PROVIDERS.get(s["provider_id"], {}).get("key_hint", ""),
        "voices": tts_service.list_voices(s["provider_id"]),
        "providers": [cat.public_card(p) for p in cat.TTS_PROVIDERS.values()],
        "keys_saved": {pid: bool(config.tts_provider_key(pid)) for pid in cat.TTS_PROVIDERS},
    }


@router.get("/status", summary="TTS 配置与音色表")
async def tts_status():
    return _status()


@router.post("/synthesize", summary="合成语音（返回 base64 mp3）",
             description="统一走火山引擎 / GPT；未配置厂商时中文报错引导，不抛英文堆栈")
async def synthesize(req: TTSRequest):
    try:
        result = await tts_service.synthesize(
            req.text, voice=req.voice, model=req.model,
            speed=req.speed or None, provider_id=req.provider_id,
            base_url_override=req.base_url, key_override=req.key)
        return result
    except TTSError as e:
        raise HTTPException(status_code=400, detail={"message": e.message, "solution": e.solution})
    except Exception as e:
        raise HTTPException(status_code=500, detail={
            "message": f"语音合成出错（{e}）",
            "solution": "请稍后重试；或在设置里换一家 TTS（火山引擎 / GPT）"})


@router.post("/test", summary="TTS 联通试音（合成一句极短的话）",
             description="真实合成一次「你好」，成功才说明 Key / 音色真的可用")
async def tts_test(req: TTSRequest):
    try:
        result = await tts_service.synthesize(
            req.text or "您好，我是小伴。",
            voice=req.voice, model=req.model, speed=req.speed or None,
            provider_id=req.provider_id or config.TTS_PROVIDER_ID,
            base_url_override=req.base_url, key_override=req.key)
        audio_len = len(result.get("audio_base64") or "")
        return {"ok": True,
                "message": f"✓ 试音成功！{result['provider']}「{result['model']}」音色「{result['voice']}」可用"
                           f"（音频 {audio_len // 1024}KB）",
                "audio_base64": result["audio_base64"], "format": result["format"]}
    except TTSError as e:
        return {"ok": False, "message": e.message, "suggestion": e.solution}
    except Exception as e:
        return {"ok": False, "message": f"试音出错（{e}）", "suggestion": "请稍后重试"}
