# app/infra/search/faiss_index.py
from __future__ import annotations
import os
from pathlib import Path
from typing import List, Tuple
import numpy as np

try:
    import faiss  # type: ignore
except ImportError as e:
    raise RuntimeError("Install dulu: pip install faiss-cpu") from e

_EMBED_DIM = int(os.getenv("EMBED_DIM", "1536"))
_FAISS_PATH = os.getenv("FAISS_PATH", "data/faiss/products.index")
_IDS_PATH   = os.getenv("FAISS_IDS_PATH", "data/faiss/ids.npy")  # legacy optional

_NLIST_REQ  = int(os.getenv("FAISS_NLIST", "4096"))
_NPROBE     = int(os.getenv("FAISS_NPROBE", "16"))
_PQ_M       = int(os.getenv("FAISS_PQ_M", "16"))
_VERBOSE    = os.getenv("FAISS_VERBOSE", "0") == "1"
_FORCE_FLAT = os.getenv("FAISS_FORCE_FLAT", "0") == "1"

def _dbg(msg: str):
    if _VERBOSE:
        print(f"[faiss] {msg}")

def _adaptive_nlist(n_train: int) -> int:
    if n_train <= 0:
        return 16
    guess = int(2 * np.sqrt(n_train))
    return max(16, min(_NLIST_REQ, guess))

def _inner_index(obj: faiss.Index) -> faiss.Index:
    """Ambil index dalam (jika IDMap2) lalu downcast agar atribut spesifik (nlist) tersedia."""
    base = faiss.downcast_index(obj)
    if isinstance(base, faiss.IndexIDMap2):
        inner = faiss.downcast_index(base.index)
        return inner
    return base

class FaissVectorIndex:
    """
    Index dengan IDMap2:
      - IVFPQ bila sample cukup; FLAT jika kecil/FAISS_FORCE_FLAT=1.
      - add() memastikan trained dulu (auto-train atau fallback FLAT).
      - tidak pernah akses .nlist tanpa cek tipe.

    NOTE:
      Nilai D (distance) yang dikembalikan .search() perlu dipetakan ke skor kesamaan
      di layer atas (router) sebelum dipakai confidence aggregator.
    """
    def __init__(self):
        self.index: faiss.Index | None = None
        self.mode: str | None = None   # "ivfpq" | "flat"
        self.ids = None
        self._loaded = False

    def _make_ivfpq(self, nlist: int) -> faiss.Index:
        quantizer = faiss.IndexFlatL2(_EMBED_DIM)
        base = faiss.IndexIVFPQ(quantizer, _EMBED_DIM, nlist, _PQ_M, 8)
        return faiss.IndexIDMap2(base)

    def _make_flat(self) -> faiss.Index:
        return faiss.IndexIDMap2(faiss.IndexFlatL2(_EMBED_DIM))

    def load(self):
        p = Path(_FAISS_PATH)
        if p.exists():
            self.index = faiss.read_index(str(p))
            inner = _inner_index(self.index)
            if isinstance(inner, faiss.IndexIVFPQ):
                self.mode = "ivfpq"
                inner.nprobe = _NPROBE
            elif isinstance(inner, faiss.IndexFlatL2):
                self.mode = "flat"
            else:
                self.index = self._make_flat()
                self.mode = "flat"
            self._loaded = True
            _dbg(f"loaded mode={self.mode}, ntotal={self.index.ntotal}")
            try:
                self.ids = np.load(_IDS_PATH)
            except Exception:
                self.ids = np.empty((0,), dtype=np.int64)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            self.index = None
            self.mode = None
            self.ids = np.empty((0,), dtype=np.int64)
            self._loaded = False
            _dbg("no index on disk; will create on train/add")

    def is_trained(self) -> bool:
        return bool(self.index and self.index.is_trained)

    def train(self, vectors: np.ndarray):
        if vectors is None or vectors.size == 0:
            if self.index is None:
                self.index = self._make_flat(); self.mode = "flat"
            return
        if self.index is not None and self.index.is_trained:
            _dbg("train(): already trained")
            return

        if _FORCE_FLAT:
            self.index = self._make_flat(); self.mode = "flat"
            _dbg("train(): forced FLAT"); return

        n_train = int(vectors.shape[0])
        if n_train < 256:
            self.index = self._make_flat(); self.mode = "flat"
            _dbg(f"train(): n_train={n_train} < 256 → FLAT"); return

        nlist = _adaptive_nlist(n_train)
        self.index = self._make_ivfpq(nlist); self.mode = "ivfpq"
        inner = _inner_index(self.index)
        if isinstance(inner, faiss.IndexIVFPQ):
            _dbg(f"train(): IVFPQ nlist={inner.nlist}, n_train={n_train}")
            inner.train(vectors)
            inner.nprobe = _NPROBE
        else:
            _dbg("train(): inner not IVFPQ → switch to FLAT")
            self.index = self._make_flat(); self.mode = "flat"
        self._loaded = True

    def add(self, vectors: np.ndarray, ids: np.ndarray):
        assert vectors.shape[0] == ids.shape[0]
        if self.index is None:
            self.index = self._make_flat(); self.mode = "flat"
            _dbg("add(): created FLAT (lazy)")

        if not self.index.is_trained:
            _dbg("add(): index not trained → train with current batch")
            try:
                self.train(vectors)
            except Exception as e:
                _dbg(f"add(): train failed ({e}) → fallback FLAT")
                self.index = self._make_flat(); self.mode = "flat"

        self.index.add_with_ids(vectors, ids)
        if self.ids is not None and self.ids.size:
            self.ids = np.concatenate([self.ids, ids])
        else:
            self.ids = ids
        _dbg(f"add(): ntotal={self.index.ntotal}")

    def search(self, query_vec: np.ndarray, k: int = 25) -> List[Tuple[int, float]]:
        if self.index is None or self.index.ntotal == 0:
            return []
        D, I = self.index.search(query_vec.reshape(1, -1), k)
        return [(int(i), float(d)) for i, d in zip(I[0], D[0]) if int(i) != -1]

    def persist(self):
        if self.index is None:
            return
        faiss.write_index(self.index, _FAISS_PATH)
        try:
            if self.ids is not None:
                np.save(_IDS_PATH, self.ids)
        except Exception:
            pass
        _dbg(f"persist(): saved → {_FAISS_PATH}")


def build_or_update_index(*, products, embedder, batch_size: int = 1024):
    idx = FaissVectorIndex(); idx.load()

    ids_list: List[int] = []
    texts: List[str] = []
    for p in products:
        ids_list.append(int(p["_id"]) if not isinstance(p["_id"], int) else p["_id"])
        texts.append(p["text"])

    if not texts:
        return idx

    mats: List[np.ndarray] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        embs  = embedder.embed_batch(batch)
        mats.append(np.array(embs, dtype=np.float32))
    mat = np.vstack(mats)
    id_arr = np.array(ids_list, dtype=np.int64)

    if not idx.is_trained():
        idx.train(mat)
    idx.add(mat, id_arr)
    idx.persist()
    return idx
