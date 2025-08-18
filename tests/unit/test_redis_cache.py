# tests/unit/test_redis_cache.py
import asyncio
from app.infra.cache.redis_cache import RedisCache

async def _run():
    c = RedisCache.from_env()
    await c.set_json("t:x", {"a":1})
    assert (await c.get_json("t:x"))["a"] == 1
    await c.hset("t:h", {"k":"v"})
    assert (await c.hgetall("t:h"))["k"] == "v"
    await c.lpush_cap("t:l", {"i":1}, cap=2)
    await c.lpush_cap("t:l", {"i":2}, cap=2)
    await c.lpush_cap("t:l", {"i":3}, cap=2)
    xs = await c.lrange_json("t:l", 0, 10)
    assert len(xs) == 2 and xs[0]["i"] == 3

def test_cache_ops():
    asyncio.get_event_loop().run_until_complete(_run())
