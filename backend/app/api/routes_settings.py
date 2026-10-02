# -*- coding: utf-8 -*-
"""
设置 REST API（角色2：郝英博 · 全厂商目录版）

给测试页「⚙️ 密钥设置」弹窗用：
  - 内置全厂商目录：请求地址、模型名全部预置，用户只需选厂商、点模型、粘 Key
  - 三类能力分开选：文字大脑 / 图片识别 / 语音合成 TTS
  - 保存后热生效（不用重启）+ 立即做一次联通测试（通才用，失败中文报错）
  - 每个厂商的 Key 独立记忆（KEY_<厂商ID>= 写进 .env）

接口：
  GET  /api/settings           当前配置状态（密钥不回显）
  GET  /api/settings/catalog   全厂商目录 + 当前激活 + 谁家已存 Key
  POST /api/settings/test      联通测试（任意厂商，按协议自动适配）
  POST /api/settings           保存配置（保存后自动测试并热生效）
"""
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.core import providers_http
from app.core import providers_catalog as cat
from app.core.llm_client import llm_client
from app.core.asr import asr_service

router = APIRouter(prefix="/api/settings", tags=["系统设置"])


# ============================================================
# 请求体定义
# ============================================================
class SettingsUpdate(BaseModel):
    """保存配置：所有字段都可选，只更新非空的部分"""
    # —— 文字大脑（激活的大模型）——
    provider_id: str = Field("", description="厂商ID（目录里的 id，如 deepseek/minimax/openai）")
    model: str = Field("", description="模型名（目录点选；也可自定义）")
    base_url: str = Field("", description="自定义请求地址（留空=用目录预置地址）")
    key: str = Field("", description="该厂商的 API Key（留空=不改动已存的）")
    # —— 图片/文字识别 ——
    vision_provider_id: str = Field("", description="识图厂商ID（留空=默认识图目录第一个）")
    vision_model: str = Field("", description="识图模型名")
    vision_key: str = Field("", description="识图厂商 Key（与文字同厂商时不重复存）")
    vision_base_url: str = Field("", description="自定义识图请求地址（custom 厂商用）")
    # —— 语音合成 TTS ——
    tts_provider_id: str = Field("", description="TTS厂商ID（volcengine/openai/custom）")
    tts_model: str = Field("", description="TTS模型名")
    tts_key: str = Field("", description="TTS Key（火山引擎填 AppID:AccessToken；GPT 填 sk- 开头）")
    tts_voice: str = Field("", description="默认音色ID（目录 voices 里的 id）")
    tts_speed: str = Field("", description="语速 0.5~2.0")
    tts_base_url: str = Field("", description="自定义 TTS 请求地址（custom 厂商用）")
    # —— 图片生成（GPT 最新 gpt-image 系列 / OpenAI 兼容自定义）——
    image_provider_id: str = Field("", description="生图厂商ID（openai/custom）")
    image_model: str = Field("", description="生图模型名（如 gpt-image-2.5-flare）")
    image_key: str = Field("", description="生图厂商 Key")
    image_base_url: str = Field("", description="自定义生图请求地址（custom 厂商用）")
    # —— 语音识别（兼容旧版字段）——
    volc_asr_api_key: str = Field("", description="火山引擎 ASR API Key（新控制台）")
    volc_asr_app_id: str = Field("", description="火山引擎 ASR AppID（旧控制台）")
    volc_asr_access_token: str = Field("", description="火山引擎 ASR AccessToken（旧控制台）")
    volc_tts_appid: str = Field("", description="火山引擎 TTS AppID（Key 只填 AccessToken 时用）")
    # 地址清空位：切换厂商时把旧的自定义请求地址一并清掉（避免旧地址串台）
    reset_base_url: bool = Field(False, description="清空 LLM 自定义请求地址（回落目录预置）")


class SettingsTest(BaseModel):
    provider_id: str = Field("", description="厂商ID（留空=用当前激活的文字模型）")
    model: str = Field("", description="要测试的模型名")
    key: str = Field("", description="要测试的 API Key（留空=用已存的）")
    base_url: str = Field("", description="要测试的请求地址（留空=用目录预置）")
    kind: str = Field("llm", description="测试哪类目录：llm（默认）/ image")


# ============================================================
# 工具函数
# ============================================================
def _write_env(pairs: dict, path=None) -> None:
    """把键值写进 .env（已有则替换、没有则追加；保留注释与顺序；path 可注入便于单测）"""
    from pathlib import Path as _Path
    path = _Path(path) if path else (config.BASE_DIR / ".env")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines(keepends=True)
    # 历史坑：文件末尾若无换行符，追加的键会粘到最后一行（曾把 TTS_PROVIDER_ID
    # 粘进 EMBEDDING_MODEL 的值里）——先补齐末尾换行再追加
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    newline = "\n"
    out, written = [], set()
    for line in lines:
        clean = line.lstrip()
        if "=" in line and not clean.startswith("#") and clean.split("=", 1)[0].strip() in pairs:
            key = clean.split("=", 1)[0].strip()
            tail = line[-2:] if line.endswith("\r\n") else line[-1:] if line.endswith("\n") else newline
            out.append(f"{key}={pairs[key]}{tail}")
            written.add(key)
            continue
        out.append(line)
    for k, v in pairs.items():
        if k not in written:
            out.append(f"{k}={v}{newline}")
    path.write_text("".join(out), encoding="utf-8")


def _resolve_test(req: SettingsTest) -> dict:
    """把测试请求解析成完整调用配置（厂商目录兜底；kind 可选 llm/image）"""
    kind = "image" if req.kind == "image" else "llm"
    catalog = cat.IMAGE_PROVIDERS if kind == "image" else cat.LLM_PROVIDERS
    default_pid = (config.IMAGE_PROVIDER_ID or "openai") if kind == "image" else config.LLM_PROVIDER_ID
    pid = cat.normalize_pid(req.provider_id or default_pid)
    p = catalog.get(pid)
    if not p:
        raise HTTPException(status_code=400, detail={
            "message": f"目录里没有「{pid}」这家厂商",
            "solution": "请从目录里点选厂商，或在 .env 里配置好厂商ID"})
    # 自定义地址只对 custom 厂商兜底（与 config._resolve_setting 保持一致，防串台）
    if kind == "image":
        custom_base = config.IMAGE_CUSTOM_BASE_URL if pid == "custom" else ""
    else:
        custom_base = config.LLM_BASE_URL
    base_url = (req.base_url or custom_base or p["base_url"]).strip().rstrip("/")
    model = (req.model or (config.IMAGE_MODEL if kind == "image" else config.LLM_MODEL)).strip() \
        or cat.default_model(p)
    key = (req.key or config.provider_key(pid)).strip()
    return {"pid": pid, "name": p["name"], "base_url": base_url,
            "model": model, "key": key, "protocol": p["protocol"],
            "site": p.get("site", ""), "kind": kind}


async def test_connection(req: SettingsTest) -> dict:
    """联通测试：任意厂商、按协议自动适配（不入库），失败给中文报错"""
    try:
        t = _resolve_test(req)
    except HTTPException as e:
        return {"ok": False, "message": e.detail["message"], "suggestion": e.detail["solution"]}

    name, base_url, model, key, protocol = t["name"], t["base_url"], t["model"], t["key"], t["protocol"]
    if not key:
        return {"ok": False, "message": "还没有填 API Key",
                "suggestion": f"把 {name} 的 Key 填到输入框后再测试（官网：{t['site']}）"}

    try:
        if t["kind"] == "image":
            # 生图目录：不真烧一张图的钱，用 /models 探活 + 鉴权
            # 自定义中转：地址必须能拼出来，缺失/无协议时给友好提示而不是 httpx 原始错误
            test_url = base_url if base_url.startswith(("http://", "https://")) \
                else ("https://" + base_url if base_url else "")
            if not test_url:
                return {"ok": False, "message": "还没有填请求地址（自定义中转必填）",
                        "suggestion": "地址填成 https://你的中转域名/v1 这种形式"}
            # 用户可能填的是完整端点（…/images/generations）：探活时剥掉端点路径再拼 /models，
            # 保存的值原样不动（生成时尊重用户填的完整地址，不改根地址）
            probe = test_url.rstrip("/")
            if "/images/generations" in probe:
                probe = probe.split("/images/generations", 1)[0]
            async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
                r = await client.get(f"{probe}/models",
                                     headers={"Authorization": f"Bearer {key}"})
        else:
            # 文字目录：按协议发一次最小 chat 请求（协议适配统一走 providers_http）
            try:
                await providers_http.chat_once(
                    base_url, protocol, model, key,
                    [{"role": "user", "content": "你好"}],
                    max_tokens=1, timeout=8, pool="settings-test")
                code, r_text = 200, ""
            except providers_http.ChatHTTPError as e:
                code, r_text = e.status, e.body
    except httpx.TimeoutException:
        return {"ok": False, "message": "连接超时（8 秒没响应）",
                "suggestion": "请检查网络；若电脑开着代理，请让该厂商地址走直连后重试"}
    except httpx.ConnectError:
        return {"ok": False, "message": "连不上这个 API 地址",
                "suggestion": f"请确认电脑能上外网（或内网访问 {base_url} 正常）"}
    except Exception as e:
        return {"ok": False, "message": f"请求出错（{e}）", "suggestion": "请稍后重试"}

    if t["kind"] == "image":
        code, r_text = r.status_code, r.text
    # llm 分支：code/r_text 已在上面赋值（r 变量只在 image 分支存在）

    if code == 200:
        tail = "可以放心生图了" if t["kind"] == "image" else "可以放心聊天了"
        return {"ok": True, "message": f"✓ 连接成功！{name} 模型「{model}」可用，{tail}。",
                "provider_id": t["pid"], "provider_name": name, "model": model, "base_url": base_url}
    if code == 401:
        return {"ok": False, "message": f"{name} 的 API Key 无效（401 未授权）",
                "suggestion": "检查 Key 有没有多空格/引号；重新到官网申请后粘贴"}
    if code == 402:
        return {"ok": False, "message": f"{name} 账户余额不足（402）",
                "suggestion": f"请登录 {t['site']} 充值后再试"}
    if code == 403:
        return {"ok": False, "message": f"{name} 拒绝了请求（403）",
                "suggestion": f"Key 可能没有开通该模型权限，请到 {t['site']} 控制台开通「{model}」"}
    if code == 429:
        return {"ok": False, "message": "请求太频繁或额度受限（429）",
                "suggestion": "请稍等一分钟再试，或检查账户额度/免费额度是否用完"}
    if code == 404 and t["kind"] == "image":
        return {"ok": False, "message": "网关没有 /models 探活接口（404）",
                "suggestion": "这不一定是配置错：部分纯生图网关不实现 /models。请直接点「生成」实跑一次——"
                              "报 401 是 Key 问题，报 400/404 则是模型名与网关控制台不一致"}
    if code == 400 or code == 404:
        return {"ok": False, "message": f"请求被拒绝（{code}）——模型名「{model}」可能不被这个接口支持",
                "suggestion": f"服务商返回：{r_text[:150]}；请在目录里换一个模型，或填入该平台控制台里的准确模型名/接入点ID"}
    if code >= 500:
        return {"ok": False, "message": f"{name} 服务器繁忙（{code}）", "suggestion": "服务端临时故障，请稍后重试"}
    return {"ok": False, "message": f"连接失败（HTTP {code}）",
            "suggestion": f"服务商返回：{r_text[:150]}；请核对该厂商的请求地址与模型名"}


def _section_state(setting: dict) -> dict:
    """激活配置的对外状态（不带密钥）"""
    return {"provider_id": setting["provider_id"], "provider_name": setting["provider_name"],
            "model": setting["model"], "base_url": setting["base_url"],
            "configured": setting["configured"], "site": setting.get("site", "")}


def _keys_state() -> dict:
    """哪些厂商已存 Key（只报真伪，绝不回显密钥内容）"""
    out = {}
    for section in ("llm", "vision", "image"):
        for pid in cat.get_catalog(section):
            out.setdefault(pid, bool(config.provider_key(pid)))
    out["_tts"] = {pid: bool(config.tts_provider_key(pid))
                   for pid in cat.TTS_PROVIDERS}
    return out


# ============================================================
# 接口
# ============================================================
@router.get("", summary="查看当前配置状态")
async def get_settings():
    return {
        "llm": _section_state(config.llm_setting()),
        "vision": _section_state(config.vision_setting()),
        "tts": _section_state(config.tts_setting()),
        "image": _section_state(config.image_setting()),
        "asr": {
            "mode": asr_service.mode,
            "configured": asr_service.mode == "volcengine",
            "hint": "火山引擎语音识别（新控制台 API Key 最简）",
        },
        "keys": _keys_state(),
    }


@router.get("/catalog", summary="全厂商模型目录", description="内置目录：请求地址与模型名全部预置好，前端点选即可")
async def get_catalog():
    return {
        "llm": [cat.public_card(p) for p in cat.LLM_PROVIDERS.values()],
        "vision": [cat.public_card(p) for p in cat.VISION_PROVIDERS.values()],
        "tts": [cat.public_card(p) for p in cat.TTS_PROVIDERS.values()],
        "image": [cat.public_card(p) for p in cat.IMAGE_PROVIDERS.values()],
        "active": {
            "llm": _section_state(config.llm_setting()),
            "vision": _section_state(config.vision_setting()),
            "tts": _section_state(config.tts_setting()),
            "image": _section_state(config.image_setting()),
        },
        "keys": _keys_state(),
    }


@router.post("/test", summary="联通测试", description="任意厂商试连一次（按协议自动适配），成功返回 OK，失败中文原因")
async def api_test_connection(req: SettingsTest):
    return await test_connection(req)


@router.post("", summary="保存配置（含联通测试与热生效）")
async def save_settings(req: SettingsUpdate):
    """只更新非空字段；保存后热生效 + 自动联通测试当前文字模型"""
    pairs = {}
    # —— 文字大脑 ——
    if req.provider_id.strip():
        pid = cat.normalize_pid(req.provider_id)
        if pid not in cat.LLM_PROVIDERS:
            raise HTTPException(status_code=400, detail={
                "message": f"目录里没有「{pid}」这家文字模型厂商",
                "solution": "请从目录里点选厂商"})
        pairs["LLM_PROVIDER_ID"] = pid
    if req.model.strip():
        pairs["LLM_MODEL"] = req.model.strip().replace(" ", "")
    elif req.provider_id.strip() and cat.normalize_pid(req.provider_id) != config.LLM_PROVIDER_ID:
        pairs["LLM_MODEL"] = ""  # Resolve the new provider's default, never reuse the previous model.
    if req.base_url.strip():
        pairs["LLM_BASE_URL"] = req.base_url.strip().rstrip("/")
    elif req.reset_base_url:
        pairs["LLM_BASE_URL"] = ""  # 切换厂商：清掉旧自定义地址，回落目录预置
    if req.key.strip():
        pid = cat.normalize_pid(req.provider_id) or config.LLM_PROVIDER_ID
        pairs[f"KEY_{pid.upper()}"] = req.key.strip()
    # —— 图片/文字识别 ——
    if req.vision_provider_id.strip():
        vpid = cat.normalize_pid(req.vision_provider_id)
        if vpid not in cat.VISION_PROVIDERS:
            raise HTTPException(status_code=400, detail={
                "message": f"目录里没有「{vpid}」这家识图厂商",
                "solution": "请从目录里点选识图厂商"})
        pairs["VISION_PROVIDER_ID"] = vpid
    if req.vision_model.strip():
        pairs["VISION_MODEL"] = req.vision_model.strip().replace(" ", "")
    if req.vision_key.strip():
        vpid = req.vision_provider_id.strip().lower() or config.vision_setting()["provider_id"]
        pairs[f"KEY_{vpid.upper()}"] = req.vision_key.strip()
    if req.vision_base_url.strip():
        pairs["VISION_CUSTOM_BASE_URL"] = req.vision_base_url.strip().rstrip("/")
    # —— 语音合成 TTS ——
    if req.tts_provider_id.strip():
        tpid = req.tts_provider_id.strip().lower()
        if tpid not in cat.TTS_PROVIDERS:
            raise HTTPException(status_code=400, detail={
                "message": f"目录里没有「{tpid}」这家语音合成厂商",
                "solution": "请从目录里点选 TTS 厂商"})
        pairs["TTS_PROVIDER_ID"] = tpid
    if req.tts_model.strip():
        pairs["TTS_MODEL"] = req.tts_model.strip().replace(" ", "")
    if req.tts_key.strip():
        tpid = req.tts_provider_id.strip().lower() or config.tts_setting()["provider_id"]
        pairs[f"KEY_TTS_{tpid.upper()}"] = req.tts_key.strip()
        pairs["TTS_API_KEY"] = req.tts_key.strip()  # 通用位也存一份（向后兼容）
    if req.tts_voice.strip():
        pairs["TTS_VOICE"] = req.tts_voice.strip()
    if req.tts_speed.strip():
        try:
            float(req.tts_speed)
            pairs["TTS_SPEED"] = req.tts_speed.strip()
        except ValueError:
            pass
    if req.tts_base_url.strip():
        pairs["TTS_CUSTOM_BASE_URL"] = req.tts_base_url.strip().rstrip("/")
    if req.volc_tts_appid.strip():
        pairs["VOLC_TTS_APPID"] = req.volc_tts_appid.strip()
    # —— 图片生成（GPT 最新 gpt-image 系列 / 自定义兼容）——
    if req.image_provider_id.strip():
        ipid = req.image_provider_id.strip().lower()
        if ipid not in cat.IMAGE_PROVIDERS:
            raise HTTPException(status_code=400, detail={
                "message": f"目录里没有「{ipid}」这家生图厂商",
                "solution": "请从目录里点选生图厂商"})
        pairs["IMAGE_PROVIDER_ID"] = ipid
    if req.image_model.strip():
        pairs["IMAGE_MODEL"] = req.image_model.strip().replace(" ", "")
    if req.image_key.strip():
        ipid = req.image_provider_id.strip().lower() or config.image_setting()["provider_id"]
        pairs[f"KEY_{ipid.upper()}"] = req.image_key.strip()
    if req.image_base_url.strip():
        pairs["IMAGE_CUSTOM_BASE_URL"] = req.image_base_url.strip().rstrip("/")
    # —— 火山引擎 ASR（兼容旧字段）——
    if req.volc_asr_api_key.strip():
        pairs["VOLC_ASR_API_KEY"] = req.volc_asr_api_key.strip()
    if req.volc_asr_app_id.strip():
        pairs["VOLC_ASR_APP_ID"] = req.volc_asr_app_id.strip()
    if req.volc_asr_access_token.strip():
        pairs["VOLC_ASR_ACCESS_TOKEN"] = req.volc_asr_access_token.strip()

    if pairs:
        _write_env(pairs)
        config.apply_runtime(pairs)
        llm_client.refresh()
        asr_service.refresh()

    # 自动联通测试当前文字模型（刚保存的 Key 立即参与测试）
    test = await test_connection(SettingsTest())
    return {
        "success": True,
        "saved": list(pairs.keys()),
        "llm": _section_state(config.llm_setting()),
        "vision": _section_state(config.vision_setting()),
        "tts": _section_state(config.tts_setting()),
        "image": _section_state(config.image_setting()),
        "asr": {"configured": asr_service.mode == "volcengine", "mode": asr_service.mode},
        "message": "已保存并立即生效（不用重启小伴）。",
        "test": test,
    }
