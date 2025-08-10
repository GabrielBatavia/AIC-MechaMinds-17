# app/application/use_cases.py
from app.domain.ports import (
    OcrPort, SatusehatPort, RepoPort, CachePort, LlmPort
)
from .commands import VerifyLabelCommand
from app.domain.detectors import interpret, extract_info

class VerifyLabelUseCase:
    def __init__(
        self,
        ocr: OcrPort,
        satusehat: SatusehatPort,
        repo: RepoPort,
        cache: CachePort,
        llm: LlmPort,
    ):
        self.ocr, self.satusehat, self.repo = ocr, satusehat, repo
        self.cache, self.llm = cache, llm

    async def execute(self, payload, image):
        cmd = VerifyLabelCommand(
            raw_nie=getattr(payload, "nie", None),
            raw_text=getattr(payload, "text", None),
            image_path=image.file if image else None,
        )

        nie, text = await extract_info(cmd, self.ocr)
        product, source = await self._lookup(nie, text)
        verdict = interpret(product)
        await self.repo.save_lookup(nie, verdict.status)
        expl = await self.llm.explain(verdict)

        return {"data": verdict.model_dump(), "message": expl}

    async def _lookup(self, nie, text):
        if nie and (hit := await self.cache.get(nie)):
            return hit, "cache"
        product, source = await self.satusehat.smart_lookup(nie, text)
        if nie :
            await self.cache.set(nie, product)
        return product, source

# wire-up helper for FastAPI Depends
def get_verify_uc():
    from app.infra import container
    return container.verify_uc

