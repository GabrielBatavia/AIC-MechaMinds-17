# app/infra/search/router.py
from __future__ import annotations
import os, re
from typing import List, Dict, Any, Tuple, Optional

from app.infra.repo.mongo_repo import MongoVerificationRepo
from app.infra.llm.openai_embedder import OpenAIEmbedder
from app.infra.search.faiss_index import FaissVectorIndex

_ATLAS_INDEX = os.getenv("ATLAS_SEARCH_INDEX") if os.getenv("ATLAS_ENABLE", "0") == "1" else None
_DISABLE_FAISS = os.getenv("DISABLE_FAISS", "0") == "1"   # opsional untuk dev tanpa OpenAI key

NIE_PAT = re.compile(r"(NA|NB|NC|ND|NE|NR|TR|SD|ML|DBL|DKL|AKL)[A-Z0-9\-\.]{3,}", re.IGNORECASE)

def looks_like_nie(q: str) -> bool:
    return bool(NIE_PAT.search((q or "").strip()))

def is_noisy(q: str) -> bool:
    q = q or ""
    non_alnum = sum(1 for ch in q if not ch.isalnum() and not ch.isspace())
    return (non_alnum / max(1, len(q))) > 0.15 or len(q) < 3

class SearchRouter:
    """
    Blend: Exact NIE → Atlas BM25 (lex) → FAISS (semantic).
    Semua operasi repo bersifat async.
    """
    def __init__(self,
                 repo: Optional[MongoVerificationRepo] = None,
                 embedder: Optional[OpenAIEmbedder] = None,
                 faiss_index: Optional[FaissVectorIndex] = None):
        self.repo = repo or MongoVerificationRepo()
        self.embedder = embedder or OpenAIEmbedder()
        self.faiss = faiss_index or FaissVectorIndex()
        self._faiss_loaded = False

    async def search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []

        # 1) Exact by NIE
        if looks_like_nie(q):
            doc = await self.repo.find_by_nie(q)
            if doc:
                doc["_score"] = 0.99
                doc["_src"] = "exact"
                return [doc]

        # 2) Lexical (Atlas → fallback)
        lex_hits = await self.repo.search_lexical(q, limit=25, atlas_index=_ATLAS_INDEX)
        best_lex = (lex_hits[0]["_score"] if lex_hits else 0.0)
        use_faiss = (not _DISABLE_FAISS) and (is_noisy(q) or best_lex < 0.35)


        # 3) Semantic (FAISS) jika perlu
        faiss_hits: List[Dict[str, Any]] = []
        if use_faiss:
            if not self._faiss_loaded:
                self.faiss.load()
                self._faiss_loaded = True
            vec = self.embedder.embed_query(q)
            import numpy as np
            res = self.faiss.search(np.array(vec, dtype=np.float32), k=25)
            if res:
                ids = [h[0] for h in res]
                by_ids = await self.repo.get_by_int_ids(ids)  # expects faiss_id mapping
                id2doc = {int(d.get("faiss_id") or 0): d for d in by_ids}
                for pid, dist in res:
                    doc = id2doc.get(int(pid))
                    if doc:
                        sim = 1.0 / (1.0 + float(dist))
                        faiss_hits.append({**doc, "_score": float(sim), "_src": "faiss"})

        # 4) Blend & light rerank
        blended: Dict[str, Dict[str, Any]] = {}
        for d in lex_hits:
            key = str(d.get("nie") or d.get("_id"))
            blended[key] = {**d, "_src": d.get("_src", "lex")}
        for d in faiss_hits:
            key = str(d.get("nie") or d.get("_id"))
            if key in blended:
                s = 0.6 * float(blended[key].get("_score", 0.0)) + 0.4 * float(d.get("_score", 0.0))
                blended[key]["_score"] = s
                blended[key]["_src"] = "hybrid"
            else:
                blended[key] = d

        out = sorted(blended.values(), key=lambda x: x.get("_score", 0.0), reverse=True)
        return out[:k]

    async def search_best(self, query: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], float]:
        hits = await self.search(query, k=1)
        if not hits:
            return None, None, 0.0
        d = hits[0]
        winner = d.get("_src") or "lex"
        conf = float(d.get("_score") or 0.0)
        if winner == "exact":
            conf = max(conf, 0.99)
        return d, winner, conf
