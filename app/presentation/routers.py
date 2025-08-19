# app/presentation/routers.py
from __future__ import annotations

from datetime import datetime
from bson import ObjectId

from fastapi import (
    APIRouter, Depends, UploadFile, File, HTTPException, Form, Body, Header
)
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from app.presentation.schemas import (
    VerifyRequest,
    SearchRequest, SearchResponse,
    VerificationResponse,  # ⬅️ use the richer response
)
from app.container import get_verify_uc, get_retrieve_use_case

# scan subrouter yang memang ada
from app.presentation.routes import scan as scan_routes

# deps opsional untuk agent
from app.container import get_session_state, get_prompt_service, get_agent_orchestrator
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.session_state import SessionStateService
from app.services.prompt_service import PromptService

router = APIRouter(prefix="/v1")

# ── VERIFY: JSON ONLY ─────────────────────────────────────────────
@router.post("/verify", response_model=VerificationResponse)
async def verify_label(
    req: VerifyRequest,
    uc = Depends(get_verify_uc),
    sess: SessionStateService = Depends(get_session_state),
    session_id: str | None = Header(None, alias="X-Session-Id"),
):
    try:
        out = await uc.execute(payload=req, image=None)  # dict sesuai VerificationResponse

        # ⬅️ simpan ringkasan verifikasi ke session (kalau header ada)
        if session_id:
            data = out.get("data", {}) or {}
            prod = data.get("product", {}) or {}
            tosave = {
                "canon": {
                    "name": prod.get("name"),
                    "nie": prod.get("nie"),
                    "manufacturer": prod.get("manufacturer"),
                    "source_url": None,
                },
                "status_label": data.get("status"),
                "source_label": data.get("source"),
                "confidence": out.get("confidence"),
                "explanation": out.get("explanation"),
            }
            await sess.save_verification(session_id, tosave)

        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── VERIFY: MULTIPART (dengan foto) ───────────────────────────────
@router.post("/verify-photo", response_model=VerificationResponse)
async def verify_label_photo(
    img: UploadFile = File(...),
    nie: str | None = Form(None),
    text: str | None = Form(None),
    uc = Depends(get_verify_uc),
):
    try:
        req = VerifyRequest(nie=nie, text=text)
        return await uc.execute(payload=req, image=img)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── SEARCH (use-case async) ───────────────────────────────────────
@router.post("/search", response_model=SearchResponse)
async def search_products(req: SearchRequest, uc = Depends(get_retrieve_use_case)):
    try:
        res = await uc.run(req.query, k=req.k)
        return SearchResponse(**res)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── SCAN routes mount ─────────────────────────────────────────────
router.include_router(scan_routes.router, prefix="/scan")

# ── AGENT: Orchestrator ──────────────────────────────────────────
@router.post("/agent")
async def agent_endpoint(
    req: dict = Body(...),
    sess: SessionStateService = Depends(get_session_state),
    prompts: PromptService = Depends(get_prompt_service),
    orchestrator: AgentOrchestrator = Depends(get_agent_orchestrator),
):
    try:
        session_id = req["session_id"]
        user_text = req["text"]
        ctx = await sess.get_agent_context(session_id)

        out = await orchestrator.handle(convo=ctx, user_msg=user_text, context=ctx)
        await sess.append_turn(session_id, "user", user_text)
        await sess.append_turn(session_id, "assistant", out.get("answer",""), {"sources": out.get("sources", [])})
        return {"reply_kind": "agent", **out}
    except Exception as e:
        raise HTTPException(500, str(e))

# ── DEBUG endpoints ───────────────────────────────────────────────
@router.get("/debug/nie/{nie}")
async def debug_nie(nie: str, uc = Depends(get_verify_uc)):
    doc = await uc.repo.find_by_nie(nie)
    hits = await uc.search.search(nie, k=1)
    payload = {
        "nie": nie,
        "repo_exact_found": bool(doc),
        "repo_exact_doc": doc,
        "search_hits_count": len(hits),
        "search_top": (hits[0] if hits else None),
    }
    content = jsonable_encoder(
        payload,
        custom_encoder={
            ObjectId: str,
            datetime: lambda d: d.isoformat(),
        },
    )
    return JSONResponse(content=content)

@router.get("/debug/verify/{nie}")
async def debug_verify(nie: str, uc = Depends(get_verify_uc)):
    # gunakan pipeline baru untuk konsistensi
    from app.domain.models.confidence import EvidenceSource
    result = await uc._verify_with_confidence(nie, None)

    payload = {
        "in_nie": nie,
        "decision": result.decision,
        "confidence": result.confidence,
        "top_source": result.top_source.value if result.top_source else None,
        "explanation": result.explanation,
        "winner": (result.winner.payload if result.winner else None),
        "all_evidence": [e.payload for e in result.all_evidence],
    }
    content = jsonable_encoder(
        payload,
        custom_encoder={ObjectId: str, datetime: lambda d: d.isoformat()},
    )
    return JSONResponse(content=content)
