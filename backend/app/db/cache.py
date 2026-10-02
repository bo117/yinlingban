# -*- coding: utf-8 -*-
"""
缓存服务（角色2：郝英博）

- 配置 REDIS_URL 时使用 Redis（Docker 生产部署）
- 未配置时自动降级为进程内存缓存（本地开发零安装）
- 两者接口一致，上层代码无感知
"""
import time
import threading


class MemoryCache:
    """进程内存缓存：带 TTL 过期的线程安全字典"""

    def __init__(self):
        self._store: dict = {}
        self._expire: dict = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            exp = self._expire.get(key)
            if exp is not None and time.time() > exp:
                self._store.pop(key, None)
                self._expire.pop(key, None)
                return None
            return self._store.get(key)

    def set(self, key: str, value, ttl: int = 600):
        with self._lock:
            self._store[key] = value
            self._expire[key] = time.time() + ttl if ttl else None

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)
            self._expire.pop(key, None)


class CacheService:
    """统一缓存服务：优先 Redis，降级内存"""

    def __init__(self, redis_url: str = ""):
        self.backend = "memory"
        self._redis = None
        if redis_url:
            try:
                import redis  # 可选依赖
                self._redis = redis.from_url(redis_url, decode_responses=True, socket_timeout=2)
                self._redis.ping()
                self.backend = "redis"
            except Exception:
                # Redis 连不上 → 降级内存缓存，绝不阻塞启动
                self._redis = None
                self.backend = "memory"
        self._memory = MemoryCache()

    def get(self, key: str):
        try:
            if self.backend == "redis":
                return self._redis.get(key)
        except Exception:
            pass
        return self._memory.get(key)

    def set(self, key: str, value, ttl: int = 600):
        try:
            if self.backend == "redis":
                self._redis.set(key, value, ex=ttl)
                return
        except Exception:
            pass
        self._memory.set(key, value, ttl)

    def delete(self, key: str):
        try:
            if self.backend == "redis":
                self._redis.delete(key)
                return
        except Exception:
            pass
        self._memory.delete(key)


# 全局单例（导入即用）
from app import config  # noqa: E402
cache = CacheService(config.REDIS_URL)
