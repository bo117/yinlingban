# -*- coding: utf-8 -*-
"""
语音识别服务 ASR（角色2：郝英博）

对接火山引擎「录音文件识别极速版」（语音输入理解）：
  - 接口：POST https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash
  - 新控制台鉴权：X-Api-Key（VOLC_ASR_API_KEY）
  - 旧控制台鉴权：X-Api-App-Key + X-Api-Access-Key（VOLC_ASR_APP_ID + VOLC_ASR_ACCESS_TOKEN）
  - 一次请求即返回识别结果，无需轮询

未配置火山引擎密钥时，前端仍可用浏览器 Web Speech API 识别（零成本）；
后端 /api/asr 会给出清晰的中文配置引导。

错误提示全部使用中文 + 解决方法。
"""
import base64
import os
import uuid

import httpx

from app import config


class ASRService:
    """语音识别服务：火山引擎录音文件识别极速版"""

    def __init__(self):
        self.mode = "volcengine" if self._configured() else "unconfigured"

    def refresh(self):
        """按最新配置重新确定生效状态（设置页改完密钥后热生效，无需重启）"""
        self.mode = "volcengine" if self._configured() else "unconfigured"

    def _configured(self) -> bool:
        """是否已配置火山引擎密钥（新/旧控制台任一种）"""
        return bool(config.VOLC_ASR_API_KEY or
                    (config.VOLC_ASR_APP_ID and config.VOLC_ASR_ACCESS_TOKEN))

    def info(self) -> dict:
        """当前 ASR 模式信息"""
        if self.mode == "volcengine":
            return {
                "mode": "volcengine",
                "mode_name": "火山引擎语音识别",
                "hint": "已配置火山引擎录音文件识别，可直接上传音频到 /api/asr",
            }
        return {
            "mode": "unconfigured",
            "mode_name": "语音识别（未配置火山引擎）",
            "hint": "前端可用浏览器 Web Speech API 识别后传文字（零成本）；"
                    "如需后端识别，请在 .env 配置 VOLC_ASR_API_KEY（新控制台）"
                    "或 VOLC_ASR_APP_ID + VOLC_ASR_ACCESS_TOKEN（旧控制台）",
        }

    @staticmethod
    def _audio_format(filename: str) -> str:
        """按文件名后缀推断音频格式（火山引擎支持的格式）"""
        ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
        return ext if ext in ("wav", "mp3", "ogg", "pcm", "amr", "aac", "m4a") else "wav"

    async def transcribe(self, audio_bytes: bytes, filename: str = "audio.wav") -> dict:
        """音频转文字（火山引擎录音文件识别极速版）"""
        if not audio_bytes:
            return {"success": False, "message": "音频内容是空的",
                    "solution": "请录制或选择一段有效的语音再试"}
        if self.mode != "volcengine":
            return {
                "success": False,
                "message": "后端未配置火山引擎语音识别密钥。",
                "solution": "请家人帮您：在 backend/.env 里填上火山引擎的 "
                            "VOLC_ASR_API_KEY（新控制台）或 VOLC_ASR_APP_ID + VOLC_ASR_ACCESS_TOKEN"
                            "（旧控制台），保存后重启小伴。"
                            "在配置好之前，也可用浏览器自带的语音识别直接说话（点话筒），不用配密钥。",
            }

        url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
        fmt = self._audio_format(filename)
        # 鉴权头：新控制台用 X-Api-Key；旧控制台用 X-Api-App-Key + X-Api-Access-Key
        headers = {
            "X-Api-Resource-Id": config.VOLC_ASR_RESOURCE_ID,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Sequence": "-1",
        }
        if config.VOLC_ASR_API_KEY:
            headers["X-Api-Key"] = config.VOLC_ASR_API_KEY
        else:
            headers["X-Api-App-Key"] = config.VOLC_ASR_APP_ID
            headers["X-Api-Access-Key"] = config.VOLC_ASR_ACCESS_TOKEN

        payload = {
            "user": {"uid": "yinlingban_elder"},
            "audio": {"data": base64.b64encode(audio_bytes).decode("ascii"), "format": fmt},
            "request": {"model_name": "bigmodel", "enable_itn": True, "enable_punc": True},
        }
        try:
            # 共享连接池：keep-alive 复用，省每次 TLS 握手（语音输入链路少等一拍）
            from app.core.http_pool import get_client
            r = await get_client("asr", 60).post(url, json=payload, headers=headers)
            if r.status_code == 401:
                return {"success": False, "message": "火山引擎语音识别密钥无效（401）",
                        "solution": "请检查 .env 中 VOLC_ASR_API_KEY 或 APP_ID/ACCESS_TOKEN 是否正确"}
            if r.status_code == 429:
                return {"success": False, "message": "火山引擎语音识别请求太频繁（429）",
                        "solution": "请稍等一分钟再试"}
            if r.status_code != 200:
                return {"success": False,
                        "message": f"火山引擎语音识别调用失败（HTTP {r.status_code}）",
                        "solution": "请查看后端控制台日志排查；也可先用浏览器自带语音识别"}
            data = r.json()
            status_code = r.headers.get("X-Api-Status-Code", "")
            if status_code not in ("", "20000000"):
                msg = data.get("message") or "服务端拒绝"
                return {"success": False, "message": f"火山引擎识别失败：{msg}",
                        "solution": "请检查密钥权限；若提示未开通，需在火山引擎控制台开通"
                                    "「录音文件识别极速版」服务"}
            text = (data.get("result") or {}).get("text", "").strip()
            if not text:
                return {"success": False, "message": "没有识别到语音内容",
                        "solution": "请离麦克风近一点、说得慢一些再试；或确认音频里确实有人在说话"}
            return {"success": True, "text": text}
        except httpx.TimeoutException:
            return {"success": False, "message": "语音识别超时",
                    "solution": "音频可能太长，请录制15秒以内的语音再试"}
        except Exception as e:
            return {"success": False, "message": f"语音识别出错（{e}）",
                    "solution": "请稍后重试"}

    # ---------- 工具方法 ----------
    @staticmethod
    def decode_base64_audio(b64_data: str) -> bytes:
        """解码 base64 音频（WebSocket 语音帧用）"""
        try:
            return base64.b64decode(b64_data)
        except Exception:
            return b""


# 全局单例
asr_service = ASRService()