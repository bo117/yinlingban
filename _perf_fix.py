# -*- coding: utf-8 -*-
"""临时工具：后端修 ①测试超时 15→8 秒 ②自定义地址补协议+友好报错 ③启动预热后台化"""
import ast
import io
import os

BASE = r"C:\Users\Administrator\Desktop\yinlingban_env\backend"


def patch(path, old, new, label, count=1):
    p = os.path.join(BASE, path)
    s = io.open(p, encoding="utf-8").read()
    if new in s:
        print("SKIP(已修):", label)
        return
    assert old in s, "ANCHOR MISS: " + label
    io.open(p, "w", encoding="utf-8").write(s.replace(old, new, count))
    ast.parse(s)
    print("ok:", label)


# ---- 1. 联通测试提速：15 秒 → 8 秒 ----
patch("app/api/routes_settings.py",
      '''        else:
            # 文字目录：按协议发一次最小 chat 请求（协议适配统一走 providers_http）
            try:
                await providers_http.chat_once(
                    base_url, protocol, model, key,
                    [{"role": "user", "content": "你好"}],
                    max_tokens=1, timeout=15, pool="settings-test")''',
      '''        else:
            # 文字目录：按协议发一次最小 chat 请求（协议适配统一走 providers_http）
            try:
                await providers_http.chat_once(
                    base_url, protocol, model, key,
                    [{"role": "user", "content": "你好"}],
                    max_tokens=1, timeout=8, pool="settings-test")''',
      "chat 测试超时 8 秒")

patch("app/api/routes_settings.py",
      '''            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                r = await client.get(f"{base_url}/models",
                                     headers={"Authorization": f"Bearer {key}"})''',
      '''            # 自定义中转：地址必须能拼出来，缺失/无协议时给友好提示而不是 httpx 原始错误
            test_url = base_url if base_url.startswith(("http://", "https://")) \\
                else ("https://" + base_url if base_url else "")
            if not test_url:
                return {"ok": False, "message": "还没有填请求地址（自定义中转必填）",
                        "suggestion": "地址填成 https://你的中转域名/v1 这种形式"}
            async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
                r = await client.get(f"{test_url}/models",
                                     headers={"Authorization": f"Bearer {key}"})''',
      "image 测试超时 8 秒 + 地址校验")

patch("app/api/routes_settings.py",
      '''        return {"ok": False, "message": "连接超时（15 秒没响应）",
                "suggestion": "请检查网络；若电脑开着代理，请让该厂商地址走直连后重试"}''',
      '''        return {"ok": False, "message": "连接超时（8 秒没响应）",
                "suggestion": "请检查网络；若电脑开着代理，请让该厂商地址走直连后重试"}''',
      "超时文案 8 秒")

# ---- 2. 生图服务：自定义地址补协议 + 空地址友好报错 ----
patch("app/core/image_service.py",
      '''    r = await get_client("image", 300).post(
        f"{s['base_url'].rstrip('/')}/images/generations",
        json=payload, headers={"Authorization": f"Bearer {s['key']}"})''',
      '''    # 自定义中转地址：用户常省略 http(s):// 前缀，自动补上；没填地址给中文报错
    base = s["base_url"]
    if base and not base.startswith(("http://", "https://")):
        base = "https://" + base
    if not base:
        raise ImageError("还没有填生图请求地址（自定义中转必填）",
                         "地址填成 https://你的中转域名/v1 这种形式")
    r = await get_client("image", 300).post(
        f"{base.rstrip('/')}/images/generations",
        json=payload, headers={"Authorization": f"Bearer {s['key']}"})''',
      "生图地址补协议")

# ---- 3. TTS 自定义地址：同样补协议 ----
patch("app/core/tts_service.py",
      '''        base_url = s.get("base_url") or config.TTS_CUSTOM_BASE_URL
        if not base_url:
            raise TTSError("自定义 TTS 还没有填请求地址",
                           "点「⚙️ 密钥设置」→「语音合成」把地址填上（如 https://api.siliconflow.cn/v1）")
        audio = await _openai_compatible_tts(''',
      '''        base_url = s.get("base_url") or config.TTS_CUSTOM_BASE_URL
        if not base_url:
            raise TTSError("自定义 TTS 还没有填请求地址",
                           "点「设置」→「语音合成」把地址填上（如 https://api.siliconflow.cn/v1）")
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url  # 用户常省略协议，自动补
        audio = await _openai_compatible_tts(''',
      "TTS 自定义地址补协议")

# ---- 4. 启动提速：知识导入/索引预热挪到后台（端口先开放，页面先开） ----
patch("app/main.py",
      '''    # 3. 探测向量化模式
    await detect_embedding_mode()
    logger.info("向量化模式：%s", embedding_mode())

    # 4. 知识库：为空时自动导入示例知识
    stats = knowledge_stats()
    if stats.get("total", 0) == 0:
        logger.info("知识库为空，自动导入 data/health_knowledge/ 示例知识……")
        stats = await import_knowledge(reset=True)
        logger.info("知识导入完成：%s 篇文档 → %s 个片段", stats.get("documents"), stats.get("chunks"))
    else:
        logger.info("知识库已就绪：%s 个片段", stats.get("total"))

    # 4b. 预热检索索引：把倒排索引和术语集合在启动期建好，
    #     避免老人问第一句话时才现建（大库下会多出上百毫秒卡顿）
    from app.rag.retriever import warmup_retrieval
    w = warmup_retrieval()
    logger.info("检索索引预热完成：%s 个片段，耗时 %sms", w["chunks"], w["ms"])

    # 5. 启动提醒调度器（到点主动提醒）
    import asyncio
    task = asyncio.create_task(ws.reminder_scheduler())

    logger.info("=" * 60)''',
      '''    # 3. 探测向量化模式
    await detect_embedding_mode()
    logger.info("向量化模式：%s", embedding_mode())

    # 4/4b. 知识导入与检索预热挪到后台任务：端口先开放、页面先打开，
    #       启动体感提速（首次问答如遇预热未完成，检索器会自行兜底构建）
    import asyncio
    warmup_task = asyncio.create_task(_post_start_warmup())

    # 5. 启动提醒调度器（到点主动提醒）
    task = asyncio.create_task(ws.reminder_scheduler())

    logger.info("=" * 60)''',
      "预热后台化")

patch("app/main.py",
      '''    # 关闭清理
    task.cancel()
    logger.info("「银龄伴」后端服务已停止")''',
      '''    # 关闭清理
    task.cancel()
    warmup_task.cancel()
    logger.info("「银龄伴」后端服务已停止")''',
      "关闭时取消预热任务")

patch("app/main.py",
      '''@asynccontextmanager
async def lifespan(app: FastAPI):''',
      '''async def _post_start_warmup():
    """后台预热：知识导入（空库时）+ 检索索引构建（不阻塞端口开放）"""
    try:
        stats = knowledge_stats()
        if stats.get("total", 0) == 0:
            logger.info("知识库为空，后台导入 data/health_knowledge/ 示例知识……")
            stats = await import_knowledge(reset=True)
            logger.info("知识导入完成：%s 篇文档 → %s 个片段",
                        stats.get("documents"), stats.get("chunks"))
        from app.rag.retriever import warmup_retrieval
        w = warmup_retrieval()
        logger.info("检索索引预热完成：%s 个片段，耗时 %sms", w["chunks"], w["ms"])
    except Exception:
        logger.exception("后台预热失败（不影响服务，首次检索会自行构建）")


@asynccontextmanager
async def lifespan(app: FastAPI):''',
      "后台预热函数")

io.open(os.path.join(BASE, "app", "main.py"), encoding="utf-8").read()
print("--- backend patches done ---")
