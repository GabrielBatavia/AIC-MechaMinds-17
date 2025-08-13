from __future__ import annotations
import os
import asyncio
import hashlib
from typing import AsyncIterator, Dict, Any, List, Optional

import numpy as np

from app.infra.repo.mongo_repo import MongoVerificationRepo
from app.infra.llm.openai_embedder import OpenAIEmbedder
from app.infra.search.faiss_index import FaissVectorIndex

from dotenv import load_dotenv
load_dotenv()


# ── Konfigurasi lewat ENV (punya default aman) ─────────────────────
BATCH_SIZE          = int(os.getenv("FAISS_BATCH", "512"))
TRAIN_SAMPLES       = int(os.getenv("FAISS_TRAIN_SAMPLES", "20000"))  # ~20000 → ~120MB RAM (1536d fp32)
ATLAS_SEARCH_INDEX  = os.getenv("ATLAS_SEARCH_INDEX")  # tidak dipakai di job ini
FIELDS_PROJECTION   = {
    "_id": 1, "faiss_id": 1,
    "name": 1, "dosage_form": 1, "strength": 1,
    "composition": 1, "manufacturer": 1,
}

# ── Helper: bikin text gabungan utk embedding ──────────────────────
def make_text(d: Dict[str, Any]) -> str:
    parts = [
        d.get("name", "") or "",
        d.get("dosage_form", "") or "",
        d.get("strength", "") or "",
        d.get("composition", "") or "",
        d.get("manufacturer", "") or "",
    ]
    return " | ".join([p.strip() for p in parts if p and p.strip()])

# ── Helper: int64 stabil dari ObjectId/nie (tidak tabrakan praktis) ─
def stable_int64(key: str) -> int:
    h = hashlib.sha1(key.encode("utf-8")).digest()
    # ambil 8 byte pertama → positive int64
    return int.from_bytes(h[:8], "big", signed=False) & ((1 << 63) - 1)

# ── Async iterator dokumen products ────────────────────────────────
async def iter_products(repo: MongoVerificationRepo, limit: Optional[int] = None) -> AsyncIterator[Dict[str, Any]]:
    cursor = repo.coll.find({}, FIELDS_PROJECTION)
    if limit:
        cursor = cursor.limit(limit)
    async for doc in cursor:
        yield doc

# ── Job utama (async) ──────────────────────────────────────────────
async def _run_build(limit: Optional[int] = None):
    repo = MongoVerificationRepo()
    await repo.ensure_indexes()  # pastikan index, termasuk faiss_id

    embedder = OpenAIEmbedder()
    index = FaissVectorIndex()
    index.load()  # akan buat struktur folder kalau belum ada

    # Buffer untuk training (sebelum index dilatih, kita tahan embedding dulu)
    train_vecs: List[np.ndarray] = []
    train_ids:  List[int] = []
    trained = index.is_trained()

    pending_vecs: List[np.ndarray] = []
    pending_ids:  List[int] = []

    # Pass 1: stream dokumen, buat faiss_id kalau belum ada, embed per batch
    batch_texts: List[str] = []
    batch_ids:   List[int] = []

    count = 0
    async for doc in iter_products(repo, limit=limit):
        count += 1

        # siapkan faiss_id (stabil): pakai _id string sebagai key
        fid = doc.get("faiss_id")
        if fid is None:
            fid = stable_int64(str(doc["_id"]))
            # simpan ke Mongo agar retrieval balik dari FAISS → Mongo bisa work
            await repo.coll.update_one({"_id": doc["_id"]}, {"$set": {"faiss_id": int(fid)}})

        text = make_text(doc)
        if not text:
            continue

        batch_texts.append(text)
        batch_ids.append(int(fid))

        # embed bila batch penuh
        if len(batch_texts) >= BATCH_SIZE:
            embs = embedder.embed_batch(batch_texts)  # list[list[float]]
            mat = np.array(embs, dtype=np.float32)
            ids = np.array(batch_ids, dtype=np.int64)

            if not trained:
                # Tampung untuk training
                train_vecs.append(mat)
                train_ids.extend(ids.tolist())
                total_train = sum(x.shape[0] for x in train_vecs)
                if total_train >= TRAIN_SAMPLES:
                    # Latih index dengan gabungan sample (atau pakai subset)
                    train_mat = np.vstack(train_vecs)
                    sample = train_mat
                    if sample.shape[0] > TRAIN_SAMPLES:
                        # ambil subset acak TRAIN_SAMPLES
                        rng = np.random.default_rng(42)
                        sel = rng.choice(sample.shape[0], TRAIN_SAMPLES, replace=False)
                        sample = sample[sel]
                    index.train(mat)
                    # Setelah train, data yang sudah di-buffer juga ditambahkan
                    index.add(train_mat, np.array(train_ids, dtype=np.int64))
                    train_vecs.clear(); train_ids.clear()
                    trained = True
            else:
                # Index sudah terlatih → langsung add
                index.add(mat, ids)

            batch_texts.clear()
            batch_ids.clear()

    # Flush sisa batch kecil
    if batch_texts:
        embs = embedder.embed_batch(batch_texts)
        mat = np.array(embs, dtype=np.float32)
        ids = np.array(batch_ids, dtype=np.int64)
        if not trained:
            # kalau dataset kecil tak mencapai TRAIN_SAMPLES, latih dengan apa adanya
            index.train(mat if mat.shape[0] > 1024 else mat)
            index.add(mat, ids)
            trained = True
        else:
            index.add(mat, ids)

    # Jika masih ada buffer train yang belum di-add (kasus data < TRAIN_SAMPLES)
    if train_vecs:
        train_mat = np.vstack(train_vecs)
        if not trained:
            index.train(train_mat if train_mat.shape[0] > 1024 else train_mat)
        index.add(train_mat, np.array(train_ids, dtype=np.int64))

    index.persist()
    print(f"[build_index_job] Completed. Trained={trained}, total_docs_processed≈{count}")

# Entry point sync-friendly
def run_build(limit: Optional[int] = None):
    asyncio.run(_run_build(limit))
