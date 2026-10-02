"""Public, secret-free integration contract for the XmovAvatar JS SDK."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/avatar", tags=["数字人接入"])


@router.get("/config")
async def avatar_config():
    return {
        "provider": "xingyun", "display_name": "魔珐星云", "status": "reserved",
        "contract_version": "1.0", "container_id": "#avatar-container",
        "sdk_url": "https://media.xingyun3d.com/xingyun3d/general/litesdk/xmovAvatar@latest.js",
        "gateway_server": "https://nebula-agent.xingyun3d.com/user/v1/ttsa/session",
        "documentation_url": "https://www.xingyun3d.com/developers/52-183",
        "event_source": "/ws", "bridge": "window.avatarBridge.attach(sdk)",
        "events": {
            "emotion": "listen", "thinking": "think", "reply_delta": "speak:buffer",
            "reply_done": "speak:finish", "interrupted": "interactiveidle",
            "reminder_due": "interactiveidle+speak", "care": "interactiveidle+speak",
            "error": "interactiveidle",
        },
        "credentials_required": ["appId", "appSecret"],
    }
