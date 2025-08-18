# app/infra/cache/redis_cache.py
import os
import json
from typing import Any, Optional, List
import redis.asyncio as aioredis

from app.domain.ports import CachePort  # keeps compatibility with your port


DEFAULT_TTL = int(os.getenv("SESSION_TTL_SECONDS", "172800"))  # 48h default

class RedisCache(CachePort):
    """
    Backward-compatible Redis cache with richer helpers for session state.

    Existing code using:
        cache.get(key) -> JSON-decoded object or None
        cache.set(key, value, ttl=43200)

    New helpers:
        get_json/set_json, hset/hgetall, lpush_cap/lrange_json, expire, delete
        from_env()  -> construct from REDIS_URL
    """
    def __init__(self, client: Optional[aioredis.Redis] = None):
        self.r = client or aioredis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            encoding="utf-8",
            decode_responses=True,
        )

    # ------- Back-compat API (kept as-is) -------
    async def get(self, k: str):
        v = await self.r.get(k)
        return json.loads(v) if v else None

    async def set(self, k: str, v: Any, ttl: int = 43200):
        # old default: 12h; keep it to avoid surprise
        await self.r.set(k, json.dumps(v, ensure_ascii=False, default=str), ex=ttl)

    # ------- New, explicit JSON helpers -------
    @classmethod
    def from_env(cls):
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        return cls(aioredis.from_url(url, encoding="utf-8", decode_responses=True))

    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.r.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: Any, ttl: int = DEFAULT_TTL):
        await self.r.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)

    # ------- Hash helpers (for session :meta etc.) -------
    async def hset(self, key: str, mapping: dict, ttl: int = DEFAULT_TTL):
        if not mapping:
            return
        await self.r.hset(key, mapping=mapping)
        await self.r.expire(key, ttl)

    async def hgetall(self, key: str) -> dict:
        return await self.r.hgetall(key)

    # ------- List helpers (compact conversation history) -------
    async def lpush_cap(self, key: str, item: Any, cap: int = 30, ttl: int = DEFAULT_TTL):
        await self.r.lpush(key, json.dumps(item, ensure_ascii=False, default=str))
        # keep newest N entries (0..cap-1)
        await self.r.ltrim(key, 0, cap - 1)
        await self.r.expire(key, ttl)

    async def lrange_json(self, key: str, start: int = 0, end: int = 19) -> List[Any]:
        raw_items = await self.r.lrange(key, start, end)
        out: List[Any] = []
        for it in raw_items:
            try:
                out.append(json.loads(it))
            except Exception:
                # tolerate stray plaintext entries
                out.append({"_raw": it})
        return out

    # ------- Utility -------
    async def expire(self, key: str, ttl: int = DEFAULT_TTL):
        await self.r.expire(key, ttl)

    async def delete(self, *keys: str) -> int:
        return await self.r.delete(*keys)


# Optional alias so imports like `from app.infra.cache.redis_store import RedisStore`
# can be trivially redirected if you switch filenames later.
RedisStore = RedisCache
