# app/application/use_cases.py
from __future__ import annotations

import json
from app.domain.ports import (
    OcrPort, SatusehatPort, RepoPort, CachePort, LlmPort
)
from .commands import VerifyLabelCommand
from app.domain.detectors import interpret, extract_info
from app.domain.models import Product
from app.infra.search.router import SearchRouter  # fallback jika perlu


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

    async def execute(self, payload, image):
        cmd = VerifyLabelCommand(
            raw_nie=getattr(payload, "nie", None),
            raw_text=getattr(payload, "text", None),
            image_path=image.file if image else None,
        )

        nie, text = await extract_info(cmd, self.ocr)

        product, source = await self._lookup(nie, text)
        # interpret() versi kamu menerima hanya product (tanpa source)
        verdict = interpret(product)

        await self.repo.save_lookup(nie or (product.nie if product else "-"), verdict.status)
        expl = await self.llm.explain(verdict)

        return {"data": verdict.model_dump(), "message": expl}

    async def _lookup(self, nie: str | None, text: str | None):
        """
        SSOT: selalu lewat SearchRouter.
        - Jika NIE ada → query = NIE (exact → lex → faiss)
        - Jika tidak ada NIE → pakai text (judul OCR/user)
        Cache NIE disimpan sebagai dict (model_dump), bukan object.
        """
        # 0) cache-by-NIE (robust atas legacy string)
        if nie:
            hit = await self.cache.get(nie)
            if hit is not None:
                prod_obj = None
                if isinstance(hit, dict):
                    prod_obj = self._to_product(hit)
                elif isinstance(hit, str):
                    # kemungkinan lama tersimpan sebagai string → coba parse JSON
                    try:
                        d = json.loads(hit)
                        if isinstance(d, dict):
                            prod_obj = self._to_product(d)
                    except Exception:
                        # stale value; opsional hapus agar tidak mengganggu
                        if hasattr(self.cache, "delete"):
                            try:
                                await self.cache.delete(nie)
                            except Exception:
                                pass
                if prod_obj:
                    return prod_obj, "cache"

        # 1) Search (SSOT)
        q = (nie or text or "").strip()
        if not q:
            return None, "none"

        hits = await self.search.search(q, k=1)
        if hits:
            d = hits[0]
            prod = self._to_product(d)
            if prod.nie:
                # simpan ke cache sebagai dict supaya aman saat dibaca kembali
                await self.cache.set(prod.nie, prod.model_dump())
            return prod, (d.get("_src") or "search")

        return None, "none"

    def _to_product(self, d) -> Product:
        """
        Map dokumen Mongo → Product minimal.
        Tandai aktif/valid agar interpret() → 'registered'.
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
