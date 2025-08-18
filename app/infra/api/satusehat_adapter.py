# app/infra/api/satusehat_adapter.py
import httpx, os, asyncio, datetime as dt
from app.domain.ports import SatusehatPort
from app.domain.models import Product

BASE = "https://api-satusehat-stg.dto.kemkes.go.id"

class SatusehatAdapter(SatusehatPort):
    def __init__(self, cache):
        self.cache = cache

    async def token(self):
        t = await self.cache.get("satusehat_token")
        if t:
            return t
        async with httpx.AsyncClient() as c:
            res = await c.post(f"{BASE}/oauth2/v1/accesstoken", data={
                "client_id": os.getenv("SATUSEHAT_CLIENT_ID"),
                "client_secret": os.getenv("SATUSEHAT_CLIENT_SECRET"),
                "grant_type": "client_credentials",
            })
            res.raise_for_status()
            data = res.json()
            await self.cache.set("satusehat_token", data["access_token"], ttl=data["expires_in"]-30)
            return data["access_token"]

    async def smart_lookup(self, nie: str | None, text: str | None):
        if not nie:
            return None, "none"
        toks = await self.token()
        async with httpx.AsyncClient() as c:
            res = await c.get(
                f"{BASE}/kfa-v2/products",
                params={"identifier":"nie", "code":nie},
                headers={"Authorization": f"Bearer {toks}"})
            if res.status_code == 404:
                return None, "satusehat"
            res.raise_for_status()
            body = res.json()
            d = (body.get("result") or {}) if isinstance(body, dict) else {}
            if not d:
                return None, "satusehat"
            try:
                return Product(**d), "satusehat"
            except Exception:
                # map minimal supaya tidak pecah kalau schema API beda
                m = {
                    "nie": d.get("nie") or d.get("identifier"),
                    "name": d.get("name"),
                    "manufacturer": d.get("manufacturer") or d.get("company"),
                    "active": d.get("active", True),
                    "state": d.get("state", "valid"),
                    "updated_at": d.get("updated_at") or d.get("last_update"),
                }
                return Product(**m), "satusehat"
