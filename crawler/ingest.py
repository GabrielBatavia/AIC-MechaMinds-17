import os, datetime as dt
from motor.motor_asyncio import AsyncIOMotorClient

DB = AsyncIOMotorClient(os.getenv("MONGO_URI", "mongodb://localhost:27017")).medverify

async def save_raw(url, resp):
    doc = {
        "url": str(url),
        "fetched_at": dt.datetime.utcnow(),
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "body": resp.text,
    }
    r = await DB.raw_pages.insert_one(doc)
    return r.inserted_id

async def upsert_product(prod: dict):
    key = {"_id": prod["_id"]}
    update = {
        "$set": {k: v for k, v in prod.items() if k != "first_seen"},
        "$setOnInsert": {"first_seen": dt.datetime.utcnow()},
    }
    await DB.products.update_one(key, update, upsert=True)
