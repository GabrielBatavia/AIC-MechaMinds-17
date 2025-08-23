# app/application/use_cases.py
from __future__ import annotations

import json
import datetime as dt
from typing import Any, Dict, List, Optional
from pathlib import Path
import tempfile, shutil, os
from typing import Union
from fastapi import UploadFile
from PIL import Image
import numpy as np

from app.domain.ports import (
    OcrPort, SatusehatPort, RepoPort, CachePort, LlmPort
)
from .commands import VerifyLabelCommand
from app.domain.detectors import extract_info  # interpret() no longer used for final decision
from app.domain.models import Product

from app.infra.search.router import SearchRouter  # fallback jika perlu

# ⬇️ NEW: confidence aggregation
from app.domain.confidence import (
    Evidence, EvidenceSource, MatchStrength, VerificationResult
)
from app.domain.services.verification_aggregator import aggregate

import logging
logger = logging.getLogger("medverify.verify")


def _dt_parse(x: Any) -> Optional[dt.datetime]:
    if not x:
        return None
    try:
        s = str(x).replace("Z", "")
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def _recency_factor_from_doc(doc: Dict[str, Any]) -> float:
    now = dt.datetime.utcnow()
    ts = _dt_parse(doc.get("updated_at") or doc.get("last_seen") or doc.get("published_at"))
    if not ts:
        return 0.6
    days = (now - ts).days
    if days <= 365:
        return 0.9
    if days <= 365 * 3:
        return 0.75
    return 0.5


def _quality_from_doc(doc: Dict[str, Any], base: float = 0.3) -> float:
    keys = ["name", "manufacturer", "category", "composition", "state", "updated_at"]
    filled = sum(1 for k in keys if doc.get(k))
    return min(1.0, base + 0.12 * filled)


def _match_strength_exact(name_or_nie_in: str, doc: Dict[str, Any]) -> MatchStrength:
    q = (name_or_nie_in or "").strip().lower()
    if not q:
        return MatchStrength.STRONG
    nie = (doc.get("nie") or doc.get("_id") or "").strip().lower()
    name = (doc.get("name") or doc.get("brand") or "").strip().lower()
    if q and (q == nie or q == name):
        return MatchStrength.EXACT
    if q and (q in name or q in nie):
        return MatchStrength.STRONG
    return MatchStrength.MEDIUM


def _match_strength_from_score(score: float, src_hint: str) -> MatchStrength:
    # Heuristik untuk dokumen dari router (lex/faiss)
    if src_hint == "lex":
        if score >= 0.85:
            return MatchStrength.STRONG
        if score >= 0.7:
            return MatchStrength.MEDIUM
        return MatchStrength.WEAK
    # faiss or unknown
    if score >= 0.85:
        return MatchStrength.STRONG
    if score >= 0.7:
        return MatchStrength.MEDIUM
    return MatchStrength.WEAK


class VerifyLabelUseCase:
    def __init__(
        self,
        ocr: OcrPort,
        satusehat: SatusehatPort | None,   # boleh None (tak dipakai)
        repo: RepoPort,
        cache: CachePort,
        llm: LlmPort,
        search_router: SearchRouter | None = None,  # opsional
    ):
        self.ocr, self.repo = ocr, repo
        self.cache, self.llm = cache, llm
        self.satusehat = satusehat  # tidak digunakan lagi
        self.search = search_router or SearchRouter(repo=self.repo)

    # async def execute(self, payload, image):
    #     cmd = VerifyLabelCommand(
    #         raw_nie=getattr(payload, "nie", None),
    #         raw_text=getattr(payload, "text", None),
    #         image_path=image.file if image else None,
    #     )

    #     nie, text = await extract_info(cmd, self.ocr)

    #     # NEW: kumpulkan evidence dan agregasi → hasil + confidence
    #     agg_result = await self._verify_with_confidence(nie, text)

    #     # simpan log (pakai NIE input atau NIE pemenang jika ada)
    #     key = nie or (agg_result.winner.product_id if agg_result.winner else "-")
    #     try:
    #         await self.repo.save_lookup(key, agg_result.decision)
    #     except Exception:
    #         pass

    #     # siapkan data payload untuk response
    #     winner_payload = (agg_result.winner.payload if agg_result.winner else {}) or {}
    #     data = {
    #         "status": winner_payload.get("state")
    #                   or winner_payload.get("status")
    #                   or ("unregistered" if (winner_payload.get("not_found") or winner_payload.get("unregistered")) else "unknown"),
    #         "source": agg_result.top_source.value if agg_result.top_source else "none",
    #         "product": {
    #             "nie": winner_payload.get("nie") or winner_payload.get("_id"),
    #             "name": winner_payload.get("name"),
    #             "manufacturer": winner_payload.get("manufacturer"),
    #             "category": winner_payload.get("category"),
    #             "composition": winner_payload.get("composition"),
    #             "updated_at": winner_payload.get("updated_at")
    #                            or winner_payload.get("published_at")
    #                            or winner_payload.get("last_seen"),
    #         },
    #     }

    #     # OPTIONAL: ringkasan natural dari LLM (aman jika offline → fallback)
    #     # kita berikan ringkasan atas result agregasi agar konsisten
    #     try:
    #         expl = await self.llm.explain({
    #             "decision": agg_result.decision,
    #             "confidence": agg_result.confidence,
    #             "source": agg_result.top_source.value if agg_result.top_source else "none",
    #             "product": data["product"],
    #             "explanation": agg_result.explanation,
    #         })
    #     except Exception:
    #         expl = agg_result.explanation

    #     # Response final mengikuti model baru (VerificationResponse)
    #     trace = []
    #     for ev in agg_result.all_evidence:
    #         trace.append({
    #             "source": ev.source.value,
    #             "product_id": ev.product_id,
    #             "name": ev.name,
    #             "match_strength": ev.match_strength.value,
    #             "quality": ev.quality,
    #             "recency_factor": ev.recency_factor,
    #             "name_confidence": ev.name_confidence,
    #             "provider_score": ev.provider_score,
    #             "reasons": ev.reasons,
    #             "payload": ev.payload or {},
    #             "debug": ev.debug or {},
    #         })

    #     return {
    #         "data": data,
    #         "message": expl,
    #         "confidence": round(float(agg_result.confidence or 0.0), 3),
    #         "source": data["source"],
    #         "explanation": agg_result.explanation,
    #         "trace": trace,
    #         "flags": [],
    #     }

    async def execute(self, payload, image: Union[UploadFile, Path, bytes, bytearray, np.ndarray, Image.Image, None]):
        tmp_path: Path | None = None
        image_path: Path | None = None

        try:
            # --- Normalize ke Path ---
            if isinstance(image, Path):
                image_path = image

            elif isinstance(image, UploadFile):
                suffix = Path(image.filename or "").suffix or ".jpg"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    shutil.copyfileobj(image.file, tmp)
                    tmp_path = Path(tmp.name)
                image_path = tmp_path

            elif isinstance(image, (bytes, bytearray)):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(bytes(image))
                    tmp_path = Path(tmp.name)
                image_path = tmp_path

            elif isinstance(image, Image.Image):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    image.save(tmp, format="PNG")
                    tmp_path = Path(tmp.name)
                image_path = tmp_path

            elif isinstance(image, np.ndarray):
                pil = Image.fromarray(image)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    pil.save(tmp, format="PNG")
                    tmp_path = Path(tmp.name)
                image_path = tmp_path

            else:
                image_path = None  # /v1/verify (tanpa foto)

            # --- Build command dengan Path (kontrak lama tetap) ---
            cmd = VerifyLabelCommand(
                raw_nie=getattr(payload, "nie", None),
                raw_text=getattr(payload, "text", None),
                image_path=image_path,
            )

            nie, text = await extract_info(cmd, self.ocr)

            # (lanjutan method kamu tetap sama di bawah ini)
            agg_result = await self._verify_with_confidence(nie, text)
            key = nie or (agg_result.winner.product_id if agg_result.winner else "-")
            try:
                await self.repo.save_lookup(key, agg_result.decision)
            except Exception:
                pass

            winner_payload = (agg_result.winner.payload if agg_result.winner else {}) or {}
            data = {
                "status": winner_payload.get("state")
                          or winner_payload.get("status")
                          or ("unregistered" if (winner_payload.get("not_found") or winner_payload.get("unregistered")) else "unknown"),
                "source": agg_result.top_source.value if agg_result.top_source else "none",
                "product": {
                    "nie": winner_payload.get("nie") or winner_payload.get("_id"),
                    "name": winner_payload.get("name"),
                    "manufacturer": winner_payload.get("manufacturer"),
                    "category": winner_payload.get("category"),
                    "composition": winner_payload.get("composition"),
                    "updated_at": winner_payload.get("updated_at")
                                   or winner_payload.get("published_at")
                                   or winner_payload.get("last_seen"),
                },
            }

            try:
                expl = await self.llm.explain({
                    "decision": agg_result.decision,
                    "confidence": agg_result.confidence,
                    "source": data["source"],
                    "product": data["product"],
                    "explanation": agg_result.explanation,
                })
            except Exception:
                expl = agg_result.explanation

            trace = []
            for ev in agg_result.all_evidence:
                trace.append({
                    "source": ev.source.value,
                    "product_id": ev.product_id,
                    "name": ev.name,
                    "match_strength": ev.match_strength.value,
                    "quality": ev.quality,
                    "recency_factor": ev.recency_factor,
                    "name_confidence": ev.name_confidence,
                    "provider_score": ev.provider_score,
                    "reasons": ev.reasons,
                    "payload": ev.payload or {},
                    "debug": ev.debug or {},
                })

            # ----- Logging ringkas, pakai variabel yang sudah dihitung di atas -----
            logger.info(
                "[verify] nie_in=%s text_in=%s -> nie_extracted=%s text_extracted=%s decision=%s conf=%.3f source=%s",
                getattr(payload, "nie", None),
                getattr(payload, "text", None),
                nie, text,
                agg_result.decision,
                float(agg_result.confidence or 0.0),
                data["source"],
            )
            if agg_result.winner:
                logger.info("[verify] winner id=%s name=%s", agg_result.winner.product_id, agg_result.winner.name)
            else:
                logger.info("[verify] no winner")


            return {
                "data": data,
                "message": expl,
                "confidence": round(float(agg_result.confidence or 0.0), 3),
                "source": data["source"],
                "explanation": agg_result.explanation,
                "trace": trace,
                "flags": [],
            }

        finally:
            # 4) Bersihkan file temp jika kita yang buat
            if tmp_path is not None:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    async def _verify_with_confidence(self, nie: str | None, text: str | None) -> VerificationResult:
        """
        Kumpulkan evidence dari:
          - Cache/Mongo (exact)
          - SearchRouter (lex/faiss)
        Kemudian agregasi → keputusan + confidence.
        """
        ocr_title_conf = 1.0  # jika kamu punya conf dari OCR title, masukkan di sini
        evs: List[Evidence] = []

        # 0) Cache-by-NIE (jika ada)
        if nie:
            hit = await self.cache.get(nie)
            if hit is not None:
                raw_doc = None
                if isinstance(hit, dict):
                    raw_doc = hit
                elif isinstance(hit, str):
                    try:
                        d = json.loads(hit)
                        if isinstance(d, dict):
                            raw_doc = d
                    except Exception:
                        if hasattr(self.cache, "delete"):
                            try:
                                await self.cache.delete(nie)
                            except Exception:
                                pass

                if raw_doc:
                    evs.append(
                        Evidence(
                            source=EvidenceSource.MONGO,
                            product_id=(raw_doc.get("_id") or raw_doc.get("nie")),
                            name=raw_doc.get("name"),
                            payload=raw_doc,
                            match_strength=_match_strength_exact(nie, raw_doc),
                            quality=_quality_from_doc(raw_doc, base=0.35),
                            recency_factor=_recency_factor_from_doc(raw_doc),
                            name_confidence=ocr_title_conf,
                            provider_score=1.0,
                            reasons=["Cache hit (Mongo-derived)."],
                        )
                    )

        # 1) Exact Mongo by NIE (paling kuat)
        if nie:
            try:
                doc = await self.repo.find_by_nie(nie)
            except Exception:
                doc = None

            if doc:
                evs.append(
                    Evidence(
                        source=EvidenceSource.MONGO,
                        product_id=(doc.get("_id") or doc.get("nie")),
                        name=doc.get("name"),
                        payload=doc,
                        match_strength=_match_strength_exact(nie, doc),
                        quality=_quality_from_doc(doc, base=0.4),
                        recency_factor=_recency_factor_from_doc(doc),
                        name_confidence=ocr_title_conf,
                        provider_score=1.0,
                        reasons=["Official record found by exact NIE."],
                    )
                )
            else:
                evs.append(
                    Evidence(
                        source=EvidenceSource.MONGO,
                        product_id=nie,
                        name=None,
                        payload={"not_found": True},
                        match_strength=MatchStrength.NONE,
                        quality=0.2,
                        recency_factor=0.5,
                        name_confidence=ocr_title_conf,
                        provider_score=0.0,
                        reasons=["No official record in Mongo for this NIE."],
                    )
                )

        # 2) Router search (lex/faiss) — pakai NIE atau text
        q = (nie or text or "").strip()
        if q:
            try:
                hits = await self.search.search(q, k=5)
            except Exception:
                hits = []

            if hits:
                for d in hits:
                    src_hint = (d.get("_src") or "").lower()
                    score = float(d.get("_score") or 0.0)
                    ms = _match_strength_from_score(score, src_hint)
                    evs.append(
                        Evidence(
                            source=EvidenceSource.FAISS if "faiss" in src_hint else EvidenceSource.MONGO if "exact" in src_hint else EvidenceSource.FAISS if "semantic" in src_hint else EvidenceSource.FAISS if "embed" in src_hint else EvidenceSource.MONGO if "lex" in src_hint and d.get("nie") else EvidenceSource.FAISS if "lex" in src_hint else EvidenceSource.FAISS,
                            product_id=(d.get("_id") or d.get("nie")),
                            name=d.get("name"),
                            payload=d,
                            match_strength=ms if src_hint != "exact" else _match_strength_exact(q, d),
                            quality=_quality_from_doc(d, base=0.3 if "faiss" in src_hint else 0.35),
                            recency_factor=_recency_factor_from_doc(d),
                            name_confidence=ocr_title_conf,
                            provider_score=score,
                            reasons=[f"SearchRouter hit ({src_hint or 'unknown'}) with score={score:.2f}."],
                        )
                    )
            else:
                evs.append(
                    Evidence(
                        source=EvidenceSource.FAISS,
                        product_id=None,
                        name=None,
                        payload={"not_found": True},
                        match_strength=MatchStrength.NONE,
                        quality=0.3,
                        recency_factor=0.5,
                        name_confidence=ocr_title_conf,
                        provider_score=0.0,
                        reasons=["No matches from SearchRouter (lex/faiss)."],
                    )
                )

        # 3) Agregasi
        return aggregate(evs)

    def _to_product(self, d) -> Product:
        """
        Map dokumen ke Product minimal (masih dipakai di debug routes).
        """
        return Product(
            nie=(d.get("nie") or "").strip(),
            name=(d.get("name") or d.get("brand") or "").strip(),
            manufacturer=(d.get("manufacturer") or "").strip(),
            active=bool(d.get("active", True)),
            state=str(d.get("state") or "valid"),
            updated_at=str(d.get("last_seen") or d.get("published_at") or d.get("updated_at") or ""),
        )


# wire-up helper for FastAPI Depends
def get_verify_uc():
    from app.container import get_verify_uc as _dep
    return _dep()
