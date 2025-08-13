from __future__ import annotations

import asyncio
from functools import lru_cache

# ── Existing deps for VERIFY ──────────────────────────────────────
from app.presentation.cache.redis_cache import RedisCache
from app.presentation.ocr.tesseract_adapter import TesseractAdapter
from app.presentation.api.satusehat_adapter import SatusehatAdapter
from app.presentation.llm.openai_adapter import OpenAILlm
from app.presentation.repo.mongo_repo import MongoVerificationRepo
from app.application.use_cases import VerifyLabelUseCase

# ── New deps for SEARCH / Retrieval ───────────────────────────────
from app.infra.llm.openai_embedder import OpenAIEmbedder
from app.infra.search.faiss_index import FaissVectorIndex
from app.infra.search.router import RetrievalRouter
from app.application.retrieve_use_case import RetrieveCandidatesUseCase


# ──────────────────────────────────────────────────────────────────
# Helpers to ensure async index setup on startup of first use
# ──────────────────────────────────────────────────────────────────

@lru_cache
def _redis() -> RedisCache:
    return RedisCache()

@lru_cache
def _ocr() -> TesseractAdapter:
    return TesseractAdapter()

@lru_cache
def _satusehat() -> SatusehatAdapter:
    return SatusehatAdapter(_redis())

@lru_cache
def _llm_chat() -> OpenAILlm:
    return OpenAILlm()

@lru_cache
def _repo_async() -> MongoVerificationRepo:
    # Motor (async) repo
    return MongoVerificationRepo()

async def _ensure_indexes_once():
    """Pastikan index Mongo siap (dipanggil sekali saat dependency pertama kali diakses)."""
    repo = _repo_async()
    try:
        await repo.ensure_indexes()
    except AttributeError:
        # Kalau versi repo lama belum punya ensure_indexes, abaikan
        pass


# ── VERIFY use-case dependency (async) ────────────────────────────
_verify_uc_singleton: VerifyLabelUseCase | None = None
_verify_uc_lock = asyncio.Lock()

async def get_verify_uc() -> VerifyLabelUseCase:
    global _verify_uc_singleton
    if _verify_uc_singleton is None:
        async with _verify_uc_lock:
            if _verify_uc_singleton is None:
                await _ensure_indexes_once()
                _verify_uc_singleton = VerifyLabelUseCase(
                    ocr=_ocr(),
                    satusehat=_satusehat(),
                    repo=_repo_async(),
                    cache=_redis(),
                    llm=_llm_chat(),
                )
    return _verify_uc_singleton


# ── SEARCH / Retrieval dependencies ───────────────────────────────
@lru_cache
def _embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder()  # uses OPENAI_API_KEY + EMBED_MODEL

@lru_cache
def _faiss() -> FaissVectorIndex:
    idx = FaissVectorIndex()
    idx.load()
    return idx

@lru_cache
def _router() -> RetrievalRouter:
    # NOTE: RetrievalRouter saat ini memakai repo sync version di rekomendasi awal.
    # Di sini kita memanfaatkan repo async (Motor) untuk operasi read via .search_lexical / .find_by_nie / .get_by_int_ids
    # Jika router kamu versi sync, buat adaptor kecil atau ubah call menjadi sync via asyncio.get_event_loop().run_until_complete.
    #
    # Untuk kesederhanaan dan unifikasi, kita sediakan adaptor kecil synchronous di use-case.
    return RetrievalRouter(repo=None, embedder=_embedder(), faiss_index=_faiss())  # repo di-inject on-demand

# ── SEARCH use-case dependency (sync wrapper) ─────────────────────
class _SyncRepoAdapter:
    """Adaptor sync untuk memanggil repo Motor (async) dari use-case sync."""
    def __init__(self, arepo: MongoVerificationRepo):
        self._r = arepo

    def find_by_nie(self, nie: str):
        return asyncio.get_event_loop().run_until_complete(self._r.find_by_nie(nie))

    def search_lexical(self, q: str, limit: int = 25, atlas_index: str | None = None):
        return asyncio.get_event_loop().run_until_complete(self._r.search_lexical(q, limit=limit, atlas_index=atlas_index))

    def get_by_int_ids(self, ids):
        return asyncio.get_event_loop().run_until_complete(self._r.get_by_int_ids(ids))


_retrieve_uc_singleton: RetrieveCandidatesUseCase | None = None
_retrieve_uc_lock = asyncio.Lock()

async def _build_retrieve_uc() -> RetrieveCandidatesUseCase:
    await _ensure_indexes_once()
    # inject repo sync adaptor supaya router (sync) bisa pakai
    repo_sync = _SyncRepoAdapter(_repo_async())
    router = _router()
    router.repo = repo_sync  # late-bind repo ke router
    return RetrieveCandidatesUseCase(router)

def get_retrieve_use_case() -> RetrieveCandidatesUseCase:
    """
    FastAPI boleh memanggil dependency sync; di dalamnya kita init sekali (blocking ringan).
    """
    global _retrieve_uc_singleton
    if _retrieve_uc_singleton is None:
        # jalankan builder async sekali
        asyncio.get_event_loop().run_until_complete(
            _init_retrieve_uc_singleton()
        )
    return _retrieve_uc_singleton

async def _init_retrieve_uc_singleton():
    global _retrieve_uc_singleton
    if _retrieve_uc_singleton is None:
        async with _retrieve_uc_lock:
            if _retrieve_uc_singleton is None:
                _retrieve_uc_singleton = await _build_retrieve_uc()
