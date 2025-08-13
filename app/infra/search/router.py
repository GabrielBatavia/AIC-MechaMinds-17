from __future__ import annotations
import os, re
from typing import List, Dict, Any, Tuple

from app.infra.repo.mongo_repo import MongoProductRepo
from app.infra.llm.openai_embedder import OpenAIEmbedder
from app.infra.search.faiss_index import FaissVectorIndex

_ATLAS_INDEX = os.getenv("ATLAS_SEARCH_INDEX")  # kalau None → fallback

NIE_PAT = re.compile(r"(NA|NB|NC|ND|NE|NR|TR|SD|ML|DBL|DKL|AKL)[A-Z0-9\-\.]{3,}", re.IGNORECASE)

def looks_like_nie(q: str) -> bool:
    return bool(NIE_PAT.search((q or "").strip()))

def is_noisy(q: str) -> bool:
    q = q or ""
    non_alnum = sum(1 for ch in q if not ch.isalnum() and not ch.isspace())
    return (non_alnum / max(1, len(q))) > 0.15 or len(q) < 3

class RetrievalRouter:
    def __init__(self, repo: MongoProductRepo, embedder: OpenAIEmbedder, faiss_index: FaissVectorIndex):
        self.repo = repo
        self.embedder = embedder
        self.faiss = faiss_index

    def search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        # 1) exact by NIE
        if looks_like_nie(q):
            doc = self.repo.find_by_nie(q)
            if doc:
                doc["_score"] = 1.0
                return [doc]

        # 2) lexical first
        lex_hits = self.repo.search_lexical(q, limit=25, atlas_index=_ATLAS_INDEX)
        best_lex = (lex_hits[0]["_score"] if lex_hits else 0.0)
        use_faiss = is_noisy(q) or best_lex < 0.35

        # 3) semantic (FAISS) jika perlu
        faiss_hits: List[Dict[str, Any]] = []
        if use_faiss:
            vec = self.embedder.embed_query(q)
            from numpy import array, float32
            res = self.faiss.search(array(vec, dtype=float32), k=25)
            if res:
                ids = [h[0] for h in res]
                by_ids = self.repo.get_by_int_ids(ids)
                id2doc = {int(d["_id"]): d for d in by_ids}
                # convert faiss dist → sim
                faiss_hits = []
                for pid, dist in res:
                    doc = id2doc.get(int(pid))
                    if doc:
                        sim = 1.0 / (1.0 + float(dist))
                        faiss_hits.append({**doc, "_score": float(sim), "_src": "faiss"})

        # 4) blend & rerank ringan
        blended: Dict[str, Dict[str, Any]] = {}
        for d in lex_hits:
            key = str(d["_id"])
            blended[key] = {**d, "_src": "lex"}
        for d in faiss_hits:
            key = str(d["_id"])
            if key in blended:
                # gabung skor
                s = 0.6 * blended[key]["_score"] + 0.4 * d["_score"]
                blended[key]["_score"] = s
                blended[key]["_src"] = "hybrid"
            else:
                blended[key] = d

        out = sorted(blended.values(), key=lambda x: x.get("_score", 0.0), reverse=True)
        return out[:k]
