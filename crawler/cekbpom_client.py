import os, asyncio, time
from contextlib import asynccontextmanager
import httpx

BASE = os.getenv("CEKBPOM_BASE", "https://cekbpom.pom.go.id")
UA   = os.getenv("SCRAPER_USER_AGENT", "MedVerifyAI/0.1 (+contact)")
RATE = float(os.getenv("SCRAPER_RATE_PER_SEC", "1"))
CONC = int(os.getenv("SCRAPER_CONCURRENCY", "2"))

class RateLimiter:
    def __init__(self, rate_per_sec: float):
        self.interval = 1.0 / max(rate_per_sec, 0.1)
        self._last = 0.0
        self._lock = asyncio.Lock()
    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            sleep = self._last + self.interval - now
            if sleep > 0: await asyncio.sleep(sleep)
            self._last = time.monotonic()

limiter = RateLimiter(RATE)
sema = asyncio.Semaphore(CONC)

@asynccontextmanager
async def client():
    headers = {"User-Agent": UA, "Accept": "text/html,application/json;q=0.9"}
    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as c:
        yield c

async def fetch(path: str, params=None):
    url = path if path.startswith("http") else f"{BASE}{path}"
    async with sema:
        await limiter.wait()
        async with client() as c:
            r = await c.get(url, params=params)
            if r.status_code in (429, 503):
                await asyncio.sleep(2)
                r = await c.get(url, params=params)
            r.raise_for_status()
            return r
