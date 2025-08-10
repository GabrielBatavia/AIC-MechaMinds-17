# app/infra/repo/mongo_repo.py
from motor.motor_asyncio import AsyncIOMotorClient
import os, datetime as dt
from app.domain.ports import RepoPort

class MongoVerificationRepo(RepoPort):
    def __init__(self):
        self.db = AsyncIOMotorClient(os.getenv("MONGO_URI")).medverify

    async def save_lookup(self, nie, status):
        await self.db.lookups.insert_one({
            "nie": nie,
            "status": status,
            "ts": dt.datetime.utcnow(),
        })
