# app/application/scan_use_case.py
from __future__ import annotations
import os
from typing import Optional, Any, Dict

from app.infra.pipelines.scan_pipeline import ScanPipeline
from app.infra.search.router import SearchRouter  # async blend: Mongo → Atlas → FAISS

# Default SLA (bisa dioverride via ENV):
#   T1 = 500 ms  (YOLO → crop title → OCR(line) → search_best)
#   T2 = 1200 ms (OCR(full) → regex BPOM → merge)
DEFAULT_T1_TIMEOUT_MS = int(os.getenv("T1_TIMEOUT_MS", "500"))
DEFAULT_T2_TIMEOUT_MS = int(os.getenv("T2_TIMEOUT_MS", "1200"))

class ScanUseCase:
    """
    Use case untuk endpoint:
      - POST /v1/scan/photo (single-shot)
      - (opsional) /v1/scan/live akan pakai pipeline.stream()

    Catatan:
    - Logika T1/T2 (early-return) TIDAK di sini, melainkan di ScanPipeline.run(...)
      supaya testable & terisolasi dari lapisan API.
    """

    def __init__(
        self,
        *,
        search_router: Optional[SearchRouter] = None,
        pipeline: Optional[ScanPipeline] = None,
        t1_timeout_ms: int = DEFAULT_T1_TIMEOUT_MS,
        t2_timeout_ms: int = DEFAULT_T2_TIMEOUT_MS,
    ) -> None:
        # Router pencarian (Mongo exact → Atlas BM25 → FAISS)
        self.query = search_router or SearchRouter()

        # Pipeline visi+OCR+regex yang mengimplementasikan T1/T2
        self.pipe = pipeline or ScanPipeline(query_service=self.query)

        # SLA timeouts (ms)
        self.t1_timeout_ms = t1_timeout_ms
        self.t2_timeout_ms = t2_timeout_ms

    async def run_single_shot(
        self,
        image_bytes: bytes,
        *,
        return_partial: bool = True,
        t1_timeout_ms: Optional[int] = None,
        t2_timeout_ms: Optional[int] = None,
        extra_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Jalankan scan single-shot.
        - return_partial=True → boleh early-return stage='partial' setelah T1.
        - t1/t2 timeout bisa override per-call.
        """
        t1 = self.t1_timeout_ms if t1_timeout_ms is None else int(t1_timeout_ms)
        t2 = self.t2_timeout_ms if t2_timeout_ms is None else int(t2_timeout_ms)

        # >>> T1/T2 di-implement di ScanPipeline.run <<<
        # Signature yang diharapkan:
        #   ScanPipeline.run(
        #       image_bytes: bytes,
        #       *,
        #       return_partial: bool,
        #       t1_timeout_ms: int,
        #       t2_timeout_ms: int,
        #       extra_ctx: Optional[dict] = None
        #   ) -> dict  # {stage: "partial"|"final", ...}
        return await self.pipe.run(
            image_bytes,
            return_partial=return_partial,
            t1_timeout_ms=t1,
            t2_timeout_ms=t2,
            extra_ctx=extra_ctx or {},
        )


# Helper untuk FastAPI Depends (opsional)
def get_scan_use_case() -> ScanUseCase:
    return ScanUseCase()
