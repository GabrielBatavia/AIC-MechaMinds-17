# app/infra/cache/redis_cache.py
import redis.asyncio as redis
import json, os
from app.domain.ports import CachePort

class RedisCache(CachePort):
    def __init__(self):
        self.r = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )

    async def get(self, k): 
        v = await self.r.get(k)
        return json.loads(v) if v else None

    async def set(self, k, v, ttl=43200):
        await self.r.set(k, json.dumps(v, default=str), ex=ttl)
