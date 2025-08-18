# app/container.py  (potongan yang berubah di bawah)
from functools import lru_cache
from app.infra.cache.redis_cache import RedisCache
from app.infra.ocr.tesseract_adapter import TesseractAdapter
from app.infra.llm.openai_adapter import OpenAILlm
from app.infra.repo.mongo_repo import MongoVerificationRepo
from app.infra.llm.openai_embedder import OpenAIEmbedder
from app.infra.search.faiss_index import FaissVectorIndex
from app.infra.search.router import SearchRouter

from app.services.session_state import SessionStateService
from app.services.prompt_service import PromptService
from app.services.agent_orchestrator import AgentOrchestrator

from app.application.use_cases import VerifyLabelUseCase
from app.application.retrieve_use_case import RetrieveCandidatesUseCase
from app.application.scan_use_case import ScanUseCase

@lru_cache
def _cache() -> RedisCache: return RedisCache.from_env()

@lru_cache
def _repo() -> MongoVerificationRepo: return MongoVerificationRepo()

@lru_cache
def _llm_chat() -> OpenAILlm: return OpenAILlm()

@lru_cache
def _embedder() -> OpenAIEmbedder: return OpenAIEmbedder()

@lru_cache
def _faiss() -> FaissVectorIndex:
    idx = FaissVectorIndex(); idx.load(); return idx

@lru_cache
def _search_router() -> SearchRouter:
    return SearchRouter(repo=_repo(), embedder=_embedder(), faiss_index=_faiss())

def get_verify_uc() -> VerifyLabelUseCase:
    return VerifyLabelUseCase(
        ocr=TesseractAdapter(),
        satusehat=None,
        repo=_repo(),
        cache=_cache(),
        llm=_llm_chat(),
        search_router=_search_router(),
    )

async def get_retrieve_use_case() -> RetrieveCandidatesUseCase:
    return RetrieveCandidatesUseCase(_search_router())

async def get_scan_use_case() -> ScanUseCase:
    return ScanUseCase(search_router=_search_router())

@lru_cache
def _session() -> SessionStateService: return SessionStateService(_cache())

@lru_cache
def _prompts() -> PromptService: return PromptService()

@lru_cache
def _agent() -> AgentOrchestrator:
    return AgentOrchestrator(llm=_llm_chat(), prompts=_prompts())

def get_session_state(): return _session()
def get_prompt_service(): return _prompts()
def get_agent_orchestrator(): return _agent()
