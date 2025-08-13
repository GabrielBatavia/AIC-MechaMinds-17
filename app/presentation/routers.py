from __future__ import annotations
from fastapi import APIRouter, Depends, UploadFile, File, Body, HTTPException

# Schemas
from .schemas import (
    VerifyRequest, VerifyResponse,
    SearchRequest, SearchResponse
)

# Use cases (dependencies disediakan via container)
from app.container import get_verify_uc, get_retrieve_use_case

router = APIRouter(prefix="/v1")


# ── VERIFY (existing) ─────────────────────────────────────────────
@router.post("/verify", response_model=VerifyResponse)
async def verify_label(
    req: VerifyRequest = Body(None),
    img: UploadFile | None = File(None),
    uc = Depends(get_verify_uc),
):
    try:
        return await uc.execute(payload=req, image=img)
    except Exception as e:
        # biar tidak bocor stacktrace
        raise HTTPException(status_code=500, detail=str(e))


# ── SEARCH (new) ─────────────────────────────────────────────────
@router.post("/search", response_model=SearchResponse)
async def search_products(
    req: SearchRequest,
    uc = Depends(get_retrieve_use_case),
):
    """
    Tiered retrieval:
    1) Exact NIE (Mongo)
    2) Lexical (Atlas Search / regex fallback)
    3) Semantic FAISS + OpenAI Embeddings (fallback/augment)
    """
    try:
        res = uc.run(req.query, k=req.k)
        return SearchResponse(**res)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
