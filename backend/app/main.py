# -*- coding: utf-8 -*-
"""
「银龄伴」后端主应用（角色2：郝英博）

FastAPI 应用组装：
  - lifespan 启动时：初始化数据库、探测大模型、自动导入知识库、启动提醒调度器
  - 路由挂载：对话 / 用户 / 提醒 / 工具 / 知识库 / WebSocket
  - 静态测试页：http://localhost:8000/ （联调用，无需前端工程即可体验全流程）
"""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app import config
from app.db.database import init_db
from app.core.llm_client import llm_client
from app.rag.knowledge_base import import_knowledge, knowledge_stats
from app.rag.vector_store import vector_backend
from app.rag.embeddings import detect_embedding_mode, embedding_mode
from app.core.asr import asr_service
from app.db.cache import cache
from app.api import routes_chat, routes_user, routes_reminder, routes_tools, routes_settings, routes_mcp, routes_vision, routes_tts, routes_image, ws
from app.api import routes_avatar
from app.api import routes_sessions
from app.api import routes_canvas

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("yinlingban")


async def _post_start_warmup():
    """后台预热：知识导入（空库时）+ 检索索引构建（不阻塞端口开放）"""
    try:
        stats = knowledge_stats()
        if stats.get("total", 0) == 0:
            logger.info("知识库为空，后台导入 data/health_knowledge/ 示例知识……")
            stats = await import_knowledge(reset=True)
            logger.info("知识导入完成：%s 篇文档 → %s 个片段",
                        stats.get("documents"), stats.get("chunks"))
        import asyncio as _aio
        from app.rag.retriever import warmup_retrieval
        w = await _aio.to_thread(warmup_retrieval)  # 同步函数放线程池，不阻塞事件循环
        logger.info("检索索引预热完成：%s 个片段，耗时 %sms", w["chunks"], w["ms"])
    except Exception:
        logger.exception("后台预热失败（不影响服务，首次检索会自行构建）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动初始化 / 关闭清理"""
    logger.info("=" * 60)
    logger.info("「银龄伴」后端服务启动中……")

    # 1. 初始化数据库
    init_db()
    logger.info("数据库初始化完成（%s）", "SQLite" if config.DATABASE_URL.startswith("sqlite") else "PostgreSQL")

    # 2. 探测大模型提供方（DeepSeek 云 API；未配 Key 会给出配置提示）
    logger.info("大模型：%s（%s）", llm_client.model, llm_client.provider)

    # 3. 探测向量化模式
    await detect_embedding_mode()
    logger.info("向量化模式：%s", embedding_mode())

    # 4/4b. 知识导入与检索预热挪到后台任务：端口先开放、页面先打开，
    #       启动体感提速（首次问答如遇预热未完成，检索器会自行兜底构建）
    import asyncio
    warmup_task = asyncio.create_task(_post_start_warmup())

    # 5. 启动提醒调度器（到点主动提醒）
    task = asyncio.create_task(ws.reminder_scheduler())

    logger.info("=" * 60)
    logger.info("服务就绪！（访问地址以上方 start.py 打印的为准，自动换端口时地址会变）")
    logger.info("当前配置 → 模型:%s | 向量:%s | 缓存:%s | ASR:%s",
                llm_client.provider, embedding_mode(), cache.backend, asr_service.mode)

    yield

    # 关闭清理
    task.cancel()
    warmup_task.cancel()
    logger.info("「银龄伴」后端服务已停止")


# ============================================================
# FastAPI 应用
# ============================================================
app = FastAPI(
    title="「银龄伴」独居老人情感陪伴数字人 后端服务",
    description="""
## 「银龄伴」API 接口文档

**角色2（郝英博）负责的全部后端接口**，供前端（角色1）联调使用。

### 核心能力
- **情感陪伴**：多轮对话 + 情绪识别（开心/难过/焦虑/生气/平静）+ 共情回复
- **健康科普**：RAG 知识库检索增强问答，回答标注来源
- **生活服务**：智能提醒 / 天气查询 / 社区信息（Function Calling）
- **对话记忆**：自动记住老人的称呼、喜好、家人、慢性病

### 快速开始
1. `POST /api/users` 创建用户（拿到 user_id）
2. `POST /api/chat` 发送对话（或走 WebSocket /ws 流式对话）
3. `GET /api/model` 查看当前生效的 AI 模型

### 给前端工程师的对接说明
- WebSocket 协议与事件说明见 `操作文档.md` 第 5 节
- 回复中的 expression / action 字段直接映射数字人表情与动作
""",
    version="1.0.0",
    lifespan=lifespan,
)

# ============================================================
# CORS 跨域放行（给角色1前端联调用——赵华的页面在别的端口/域名也能直接调接口）
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 允许任何来源（比赛项目，方便联调）
    allow_credentials=False,
    allow_methods=["*"],        # 允许所有方法（GET/POST/PUT/OPTIONS…）
    allow_headers=["*"],       # 允许所有请求头
)

# ============================================================
# 全局异常处理器（FastAPI 官方「Handling Errors」推荐做法）：
#   网络类/未知异常在这里统一转译成中文 {message, solution}，
#   业务路由不再各自重复写 try/except 样板。
# 注意：HTTPException 仍走 FastAPI 内置处理器，不会被这里拦截。
# ============================================================
import httpx
from fastapi.responses import JSONResponse


@app.exception_handler(httpx.TimeoutException)
async def _upstream_timeout_handler(request, exc):
    logger.warning("上游超时：%s %s → %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=504, content={"detail": {
        "message": "上游服务响应超时（等太久没有回音）",
        "solution": "请稍后重试；生图精绘可能要一两分钟，属正常现象"}})


@app.exception_handler(httpx.ConnectError)
async def _upstream_connect_handler(request, exc):
    logger.warning("上游连不上：%s %s → %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": {
        "message": "连不上上游服务",
        "solution": "请检查电脑网络；若开了代理，请让该厂商地址走直连"}})


@app.exception_handler(Exception)
async def _unhandled_handler(request, exc):
    logger.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": {
        "message": f"服务器内部错误（{exc}）",
        "solution": "请稍后重试；如反复出现，请把操作步骤反馈给开发者排查"}})


# ============================================================
# 慢请求监控（演示排查利器：任何接口超过 1.5s 都会在控制台留痕，
# 响应头带 X-Process-Ms 方便前端定位"哪一步慢"）
# ============================================================
_START_TS = time.time()


@app.middleware("http")
async def _slow_request_logger(request, call_next):
    t0 = time.monotonic()
    resp = await call_next(request)
    ms = (time.monotonic() - t0) * 1000
    resp.headers["X-Process-Ms"] = str(int(ms))
    if ms > 1500:
        logger.warning("慢请求：%s %s 耗时 %.0fms", request.method, request.url.path, ms)
    return resp

# 挂载路由
app.include_router(routes_chat.router)
app.include_router(routes_user.router)
app.include_router(routes_reminder.router)
app.include_router(routes_tools.router)
app.include_router(routes_settings.router)
app.include_router(routes_mcp.router)
app.include_router(routes_vision.router)
app.include_router(routes_tts.router)
app.include_router(routes_image.router)
app.include_router(ws.router)
app.include_router(routes_avatar.router)
app.include_router(routes_sessions.router)
app.include_router(routes_canvas.router)
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent.parent / "static"), name="static")


@app.get("/ready", tags=["系统"])
async def ready():
    """本地启动探针：不访问模型、数据库统计或外部服务。"""
    return {"status": "ok", "service": "yinlingban"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """浏览器会自动请求 favicon，返回空响应避免 404 噪音"""
    return Response(status_code=204)


@app.get("/health", tags=["系统"], summary="健康检查")
async def health():
    """服务健康检查（Docker 编排与监控用）"""
    stats = knowledge_stats()
    return {
        "status": "ok",
        "service": "「银龄伴」后端",
        "version": "1.1.0",
        "uptime_s": round(time.time() - _START_TS),
        "components": {
            "llm": llm_client.info(),
            "embedding": {"mode": embedding_mode()},
            "vector_store": {"backend": vector_backend, "stats": stats},
            "cache": {"backend": cache.backend},
            "asr": asr_service.info(),
            "mcp": {"endpoint": "/mcp", "tools": len(routes_mcp._mcp_tools()),
                    "memory_tools": ["memory_read", "memory_write"],
                    "说明": "MCP HTTP 工具端点：生活服务、陪聊、生图、配音及持久化记忆读写"},
            "vision": {
                "provider": config.vision_setting()["provider_name"],
                "model": config.vision_setting()["model"],
                "configured": config.vision_setting()["configured"],
                "说明": "图片/文字识别（POST /api/vision/recognize）",
            },
            "tts": {
                "provider": config.tts_setting()["provider_name"],
                "model": config.tts_setting()["model"],
                "configured": config.tts_setting()["configured"],
                "说明": "语音合成 TTS（POST /api/tts/synthesize，统一火山引擎 / GPT）",
            },
            "image": {
                "provider": config.image_setting()["provider_name"],
                "model": config.image_setting()["model"],
                "configured": config.image_setting()["configured"],
                "说明": "图片生成（POST /api/image/generations，GPT 最新 gpt-image 系列）",
            },
        },
        # 上下文容量（明确写出来，便于排查"它记得多少"）
        "context": {
            "对话历史": {
                "最大轮数": config.LLM_MAX_HISTORY,
                "说明": f"小伴一次能记住您最近 {config.LLM_MAX_HISTORY} 轮对话（再多就被截掉）",
            },
            "健康知识库(RAG)": {
                "知识片段总数": stats.get("total", 0),
                "每次检索返回": config.RAG_TOP_K,
                "说明": "健康问题会从知识库里检索，但只返回能力之内（Top-K）的依据",
            },
            "长期记忆": {
                "每次注入上限": config.MEMORY_MAX_FACTS,
                "说明": "您的称呼/年龄/身高体重/喜好/家人会被记进长期档案，聊天时自动用上",
            },
        },
    }


# ============================================================
# 联调测试页（静态 HTML，无需前端工程即可体验完整流程）
# ============================================================
_INDEX_PAGE = Path(__file__).resolve().parent.parent / "templates" / "index.html"


@app.get("/", tags=["系统"], summary="联调测试页", include_in_schema=False)
async def index():
    """内置联调测试页：文字对话 / 流式输出 / 提醒 / 天气 全流程可视化"""
    if _INDEX_PAGE.exists():
        # no-store：界面迭代快，绝不允许浏览器拿旧缓存页
        return FileResponse(_INDEX_PAGE, media_type="text/html",
                            headers={"Cache-Control": "no-store, must-revalidate"})
    return {"message": "测试页不存在，请检查 templates/index.html"}
