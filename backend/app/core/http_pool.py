# -*- coding: utf-8 -*-
"""
共享 HTTP 连接池（角色2：郝英博 · 性能优化）

问题：识图 / 语音识别 / 天气查询之前每次调用都新建 AsyncClient，
每次请求都要重做一次 TCP+TLS 握手（约 0.2~1 秒），老人等得急。

方案：按名字共享连接池（keep-alive 复用），第二次起直接进入数据传输。
事件循环更换（如测试与正式服务混跑）时自动重建。
"""
import asyncio

import httpx

_pools: dict = {}


def get_client(name: str, timeout: float) -> httpx.AsyncClient:
    """取指定名字的共享连接池客户端（没有就建；循环更换或超时参数变化时重建）"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    entry = _pools.get(name)

    def _same(a, b):
        try:
            return abs(a - b) <= 0.5
        except TypeError:
            return a == b

    if entry is None or entry[0].is_closed or entry[1] is not loop \
            or not _same(entry[2], timeout):  # 超时需求不同 → 重建（否则首次超时会被沿用）
        c = httpx.AsyncClient(
            timeout=timeout,
            trust_env=False,
            transport=httpx.AsyncHTTPTransport(retries=1),  # 建连失败自动重试一次（官方参数）：吸收死 keepalive 连接/瞬时 DNS 抖动
limits=httpx.Limits(max_keepalive_connections=4,
                                keepalive_expiry=300),
        )
        _pools[name] = (c, loop, timeout)
        return c
    return entry[0]
