# app/services/verification_service.py
from typing import Tuple, Optional
from .types import VerificationResult
from app.infra.search.mongo_client import MongoClientAdapter
from app.infra.search.faiss_client import FaissAdapter

class VerificationService:
    def __init__(self, mongo: MongoClientAdapter, faiss: FaissAdapter):
        self.mongo = mongo
        self.faiss = faiss

    async def verify(self, pq) -> VerificationResult:
        # 1) exact NIE
        if pq.nie:
            doc = await self.mongo.get_by_nie(pq.nie)
            if doc: return self._ok(doc, "mongo_exact", verified=True)

        # 2) structured exact (title+manufacturer)
        doc = await self.mongo.get_by_title_and_manu(pq.title, pq.manufacturer)
        if doc: return self._ok(doc, "mongo_exact", verified=True)

        # 3) lexical (Atlas BM25 → fallback regex)
        doc, alts = await self.mongo.search_lexical(pq.title, pq.manufacturer)
        if doc: return self._ok(doc, "mongo_lexical", verified=True, alts=alts)

        # 4) FAISS semantic
        sdoc, salts = await self.faiss.search(pq.title or pq.raw, topk=3)
        if sdoc: 
            # mark as "ambiguous" unless score high
            return self._partial(sdoc, "faiss", salts)

        # 5) nothing
        return self._none()

    def _ok(self, doc, origin, verified, alts=None):
        return {
          "status": "verified" if verified else "not_verified",
          "confidence": 0.95,
          "match_origin": origin,
          "canon": self._canon(doc),
          "alternatives": alts or []
        }

    def _partial(self, doc, origin, alts):
        return {
          "status": "ambiguous",
          "confidence": 0.55,
          "match_origin": origin,
          "canon": self._canon(doc),
          "alternatives": alts
        }

    def _none(self):
        return { "status": "not_found", "confidence": 0.1, "match_origin":"none", "canon": None, "alternatives":[] }

    def _canon(self, d):
        return {
          "nie": d.get("nie"),
          "name": d.get("name"),
          "manufacturer": d.get("manufacturer"),
          "dosage_form": d.get("dosage_form"),
          "composition": d.get("composition"),
          "published_at": d.get("published_at"),
          "status_label": d.get("status_label"),
          "source_url": d.get("e_label_public") or d.get("source_url")
        }
