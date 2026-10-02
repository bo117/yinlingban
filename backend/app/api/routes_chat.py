# -*- coding: utf-8 -*-
"""
对话与语音 REST API（角色2：郝英博）

接口清单：
  POST /api/chat     对话接口（一次性返回完整结构化结果）
  POST /api/asr      语音识别接口（上传音频转文字）
  GET  /api/model    当前生效的 AI 模型信息
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, Field

from app.core.dialogue import handle_message
from app.core.asr import asr_service
from app.core.llm_client import llm_client

router = APIRouter(prefix="/api", tags=["对话服务"])


class ChatRequest(BaseModel):
    """对话请求"""
    user_id: int = Field(..., description="用户 ID（先创建用户）", examples=[1])
    text: str = Field(..., min_length=1, max_length=500, description="用户说的话", examples=["今天天气怎么样？"])
    session_id: int = Field(None, description="会话 ID，不传则新建会话")
    lang: str = Field("zh", description="对话语言：zh 中文 / en 英语 / yue 粤语 等，小伴按此语言回答", examples=["zh"])


@router.post("/chat", summary="对话接口", description="发送一句话，小伴返回带情绪/表情/动作标签的结构化回复")
async def chat(req: ChatRequest):
    result = await handle_message(req.user_id, req.text, req.session_id, lang=req.lang)
    if "error" in result:
        raise HTTPException(status_code=409 if result.get("code") == "api_key_required" else 404, detail=result)
    return result


@router.post("/asr", summary="语音识别", description="上传音频文件（wav/webm/mp3），返回识别文字。需要先在 .env 配置 ASR 或安装 whisper")
async def asr(file: UploadFile = File(..., description="音频文件")):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail={"message": "音频文件是空的", "solution": "请选择有效的录音文件"})
    result = await asr_service.transcribe(content, file.filename or "audio.webm")
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/model", summary="当前 AI 模型", description="查看当前生效的大模型（前端可展示）")
async def model_info():
    return {
        "llm": llm_client.info(),
        "asr": asr_service.info(),
    }
