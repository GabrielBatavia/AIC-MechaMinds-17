# app/presentation/health.py
from fastapi import APIRouter, Depends
import os
from app.container import get_verify_uc

router = APIRouter()

@router.get("/healthz")
async def healthz():
    return {"ok": True}

@router.get("/readyz")
async def readyz(uc = Depends(get_verify_uc)):
    checks = {}; ok = True
    # Mongo
    try:
        await uc.repo.ensure_indexes()
        checks["mongo"] = True
    except Exception as e:
        checks["mongo"] = False; checks["mongo_error"] = str(e); ok = False
    # Redis
    try:
        pong = await uc.cache.ping() if hasattr(uc.cache, "ping") else True
        checks["redis"] = bool(pong); ok = ok and bool(pong)
    except Exception as e:
        checks["redis"] = False; checks["redis_error"] = str(e); ok = False
    # Search router
    try:
        _ = await uc.search.search("paracetamol", k=1)
        checks["search_router"] = True
    except Exception as e:
        checks["search_router"] = False; checks["search_router_error"] = str(e); ok = False
    # LLM configured
    checks["openai_configured"] = bool(os.getenv("OPENAI_API_KEY"))
    return {"ok": ok, **checks}
