# app/infra/repo/mongo_repo.py
from __future__ import annotations

import os
import re
import datetime as dt
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo import ASCENDING, TEXT

from app.domain.ports import RepoPort

MONGO_URI   = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME     = os.getenv("MONGO_DB", "medverify")
COLL_NAME   = os.getenv("MONGO_COLL", "products")
ATLAS_INDEX = os.getenv("ATLAS_SEARCH_INDEX")  # contoh: "products_bm25" ; jika None → fallback regex


class MongoVerificationRepo(RepoPort):
    """
    Async repository untuk koleksi `products` + log `lookups`.

    Catatan FAISS:
      - Untuk bridging hasil FAISS (berbasis integer) ke Mongo, gunakan field numerik `faiss_id`
        pada dokumen. Saat build index, isi `faiss_id = int(_id_mirror)` atau ID numerik lain
        yang konsisten.
    """

    def __init__(self) -> None:
        self.client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.client[DB_NAME]
        self.coll: AsyncIOMotorCollection = self.db[COLL_NAME]

    # ──────────────────────────────────────────────────────────────
    #  Indexing
    # ──────────────────────────────────────────────────────────────
    async def ensure_indexes(self) -> None:
        """
        Buat index dasar agar query cepat & deterministik.
        - nie: unique/sparse
        - category: single
        - text index fallback (name, composition, manufacturer) untuk pencarian sederhana
          bila tidak memakai Atlas Search.
        """
        try:
            await self.coll.create_index([("nie", ASCENDING)], unique=True, sparse=True)
        except Exception:
            # jika sudah ada unique index, abaikan
            pass

        try:
            await self.coll.create_index([("category", ASCENDING)])
        except Exception:
            pass

        # Fallback text index untuk lingkungan yang tidak punya Atlas Search
        # (jika sudah ada text index lain, ini bisa raise → kita abaikan)
        try:
            await self.coll.create_index(
                [("name", TEXT), ("composition", TEXT), ("manufacturer", TEXT)]
            )
        except Exception:
            pass

        # Opsional: index untuk pemetaan FAISS
        try:
            await self.coll.create_index([("faiss_id", ASCENDING)], sparse=True)
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────
    #  Exact lookups
    # ──────────────────────────────────────────────────────────────
    async def find_by_nie(self, nie: str) -> Optional[Dict[str, Any]]:
        """
        Exact lookup berdasarkan NIE.
        Normalisasi ringan: buang non-alnum kecuali '-', '.', upper-case.
        """
        if not nie:
            return None
        q = re.sub(r"[^A-Za-z0-9\-.]", "", nie).upper()
        doc = await self.coll.find_one({"nie": q})
        if doc:
            doc["_score"] = 1.0
            doc["_src"] = "exact"
        return doc

    # ──────────────────────────────────────────────────────────────
    #  Lexical search (Atlas Search → fallback regex)
    # ──────────────────────────────────────────────────────────────
    async def search_lexical(self, q: str, limit: int = 25, atlas_index: Optional[str] = ATLAS_INDEX) -> List[Dict[str, Any]]:
        """
        Jika ATLAS_SEARCH_INDEX diset → gunakan $search (BM25).
        Jika tidak → fallback: $regex pada name/composition/manufacturer + skor heuristik.
        """
        q = (q or "").strip()
        if not q:
            return []

        if atlas_index:
            pipeline = [
                {
                    "$search": {
                        "index": atlas_index,
                        "compound": {
                            "must": [
                                {
                                    "text": {
                                        "path": "name",
                                        "query": q,
                                        "score": {"boost": {"value": 3}},
                                    }
                                }
                            ],
                            "should": [
                                {"text": {"path": "composition", "query": q}},
                                {"text": {"path": "manufacturer", "query": q}},
                            ],
                        },
                    }
                },
                {"$limit": limit},
                {"$addFields": {"_score": {"$meta": "searchScore"}, "_src": {"$literal": "lex"}}},
                # Proyeksi ringan agar respons konsisten
                {
                    "$project": {
                        "name": 1,
                        "nie": 1,
                        "dosage_form": 1,
                        "composition": 1,
                        "manufacturer": 1,
                        "category": 1,
                        "status": 1,
                        "_score": 1,
                        "_src": 1,
                    }
                },
            ]
            cursor = self.coll.aggregate(pipeline)
            return [doc async for doc in cursor]

        # --- Fallback sederhana tanpa Atlas ---
        rx = re.compile(re.escape(q), re.IGNORECASE)
        cursor = self.coll.find(
            {
                "$or": [
                    {"name": {"$regex": rx}},
                    {"composition": {"$regex": rx}},
                    {"manufacturer": {"$regex": rx}},
                ]
            },
            {
                "name": 1,
                "nie": 1,
                "dosage_form": 1,
                "composition": 1,
                "manufacturer": 1,
                "category": 1,
                "status": 1,
            },
        ).limit(limit)

        docs = [doc async for doc in cursor]

        # Skor heuristik ringkas: rasio panjang query vs panjang name (semakin dekat → makin tinggi)
        for d in docs:
            name = d.get("name", "") or ""
            d["_score"] = min(1.0, len(q) / max(1, len(name)))
            d["_src"] = "lex"
        return docs

    # ──────────────────────────────────────────────────────────────
    #  Bulk get by FAISS integer IDs
    # ──────────────────────────────────────────────────────────────
    async def get_by_int_ids(self, ids: List[int]) -> List[Dict[str, Any]]:
        """
        Ambil dokumen berdasarkan daftar ID numerik untuk mapping hasil FAISS.
        Gunakan field `faiss_id` (numerik) pada koleksi products.
        """
        if not ids:
            return []
        cursor = self.coll.find(
            {"faiss_id": {"$in": ids}},
            {
                "name": 1,
                "nie": 1,
                "dosage_form": 1,
                "composition": 1,
                "manufacturer": 1,
                "category": 1,
                "status": 1,
                "faiss_id": 1,
            },
        )
        return [doc async for doc in cursor]

    # ──────────────────────────────────────────────────────────────
    #  Logging (tetap dari versi sebelumnya)
    # ──────────────────────────────────────────────────────────────
    async def save_lookup(self, nie: str, status: str) -> None:
        await self.db.lookups.insert_one(
            {
                "nie": nie,
                "status": status,
                "ts": dt.datetime.utcnow(),
            }
        )
