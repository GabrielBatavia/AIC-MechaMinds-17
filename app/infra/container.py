# app/infra/container.py
from .cache.redis_cache import RedisCache
from .ocr.tesseract_adapter import TesseractAdapter
from .api.satusehat_adapter import SatusehatAdapter
from .llm.openai_adapter import OpenAILlm
from .repo.mongo_repo import MongoVerificationRepo
from app.application.use_cases import VerifyLabelUseCase

cache = RedisCache()
verify_uc = VerifyLabelUseCase(
    ocr=TesseractAdapter(),
    satusehat=SatusehatAdapter(cache),
    repo=MongoVerificationRepo(),
    cache=cache,
    llm=OpenAILlm(),
)
