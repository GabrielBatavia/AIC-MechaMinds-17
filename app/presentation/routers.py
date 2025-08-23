# app/presentation/routers.py
from __future__ import annotations

from datetime import datetime
from bson import ObjectId
from typing import Union


from fastapi import (
    APIRouter, Depends, UploadFile, File, HTTPException, Form, Body, Header
)
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from app.infra.api.security import require_api_key

from app.presentation.schemas import (
    VerifyRequest,
    SearchRequest, SearchResponse,
    VerificationResponse,
    VerificationPartial
)

from app.container import (
    get_verify_uc, get_retrieve_use_case,
    get_session_state, get_prompt_service, get_agent_orchestrator,
    get_scan_use_case,
)

from app.services.agent_orchestrator import AgentOrchestrator
from app.services.session_state import SessionStateService
from app.services.prompt_service import PromptService

from app.application.scan_use_case import ScanUseCase
from app.services.medical_classifier import classify


import os, json, time, logging
from fastapi import Request


# ──────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
agent_logger = logging.getLogger("medverify.agent")

def _preview(s: str | None, n: int = 200) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"

def _resolve_session_id(body: dict | None, x_session_id: str | None) -> str | None:
    """
    Resolusi session id. Prioritaskan header X-Session-Id, lalu body session_id.
    Tetap kompatibel dengan 'user-session' / 'user_session'.
    """
    body = body or {}
    b = body.get("session_id") 
    h = x_session_id
    if b and h and b != h:
        logger.warning("session_id mismatch: header=%s body=%s (using header)", h, b)
    sid = h or b
    if sid and isinstance(sid, str) and len(sid) > 256:
        logger.warning("session_id looks too long; check client payload")
    return sid


# Semua endpoint di bawah /v1 dan terlindungi API key
router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])

# ── VERIFY: JSON ONLY ─────────────────────────────────────────────
@router.post("/verify", response_model=VerificationResponse)
async def verify_label(
    req: VerifyRequest,
    request: Request,
    uc = Depends(get_verify_uc),
    sess: SessionStateService = Depends(get_session_state),
    session_id_hdr: str | None = Header(None, alias="X-Session-Id"),
):
    try:
        out = await uc.execute(payload=req, image=None)


        sid_body = req.session_id
        sid = _resolve_session_id(req.model_dump(), session_id_hdr)
        logger.info("[verify] sid header=%s body=%s used=%s ua=%s",
            session_id_hdr, sid_body, sid, request.headers.get("user-agent"))

        if sid:
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
            await sess.save_verification(sid, tosave)
            logger.info("[verify] saved verification to session=%s canon=%s nie=%s",
                sid, prod.get("name"), prod.get("nie"))
        else:
            logger.info("[verify] no session_id provided; skip saving session")

        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── VERIFY: MULTIPART (dengan foto) ───────────────────────────────
@router.post(
    "/verify-photo",
    response_model=Union[VerificationResponse, VerificationPartial]  # ⬅️ NEW
)
async def verify_label_photo(
    img: UploadFile = File(...),
    nie: str | None = Form(None),
    text: str | None = Form(None),
    uc = Depends(get_verify_uc),
    session_id_form: str | None = Form(None),
    scan_uc: ScanUseCase = Depends(get_scan_use_case),
    sess: SessionStateService = Depends(get_session_state),
    session_id_hdr: str | None = Header(None, alias="X-Session-Id")
):
    """
    Alur:
      1) Baca bytes → ScanUseCase (YOLO/OCR/regex) untuk ekstraksi title/NIE
      2) Reset pointer UploadFile (karena sudah dibaca)
      3) Verify use-case dengan payload gabungan hasil OCR + form
      4) (Jika ada X-Session-Id) simpan hasil verifikasi ke session
      5) Jika tidak ada sinyal yang cukup (tidak ada NIE & title kosong) → kembalikan scan_incomplete (200)
    """
    try:
        # 1) Baca bytes untuk OCR/YOLO
        image_bytes = await img.read()

        # 2) Jalankan scan (OCR/regex)
        scan = await scan_uc.run_single_shot(image_bytes, return_partial=False)

        title_text    = (scan or {}).get("title_text") or (scan or {}).get("title")
        bpom_number   = (scan or {}).get("bpom_number") or (scan or {}).get("nie")
        yolo_conf     = float((scan or {}).get("yolo_title_conf") or 0.0)
        regex_skipped = bool((scan or {}).get("regex_skipped") or False)
        timings       = (scan or {}).get("timings", {}) or {}
        title_box     = (scan or {}).get("title_box")

        logger.info(
            "[verify-photo] yolo_conf=%.3f regex_skipped=%s timings=%s title='%s' nie='%s' title_box=%s",
            yolo_conf, regex_skipped, json.dumps(timings),
            title_text, bpom_number, json.dumps(title_box) if title_box else None
        )

        # 3) Tentukan effective inputs
        eff_nie  = bpom_number or nie
        eff_text = title_text or text

        # 3b) Jika tidak ada sinyal cukup → JANGAN 400, balas 200 dengan payload partial
        if not eff_nie and (not eff_text or not str(eff_text).strip()):
            reason = "Tidak ada NIE yang terdeteksi dan teks judul terlalu lemah/kosong."
            suggestions = [
                "Ambil foto lebih dekat & fokus ke area judul produk.",
                "Pastikan pencahayaan cukup dan label tidak blur/pantul.",
                "Pastikan nomor BPOM terlihat utuh (jika ada pada kemasan).",
                "Coba foto sisi kemasan lain yang memuat nomor registrasi."
            ]
            payload = {
                "reply_kind": "scan_incomplete",
                "need_more_input": True,
                "reason": reason,
                "suggestions": suggestions,
                "scan": {
                    "yolo_title_conf": yolo_conf,
                    "regex_skipped": regex_skipped,
                    "timings": timings,
                    "title_text": title_text,
                    "bpom_number": bpom_number,
                },
            }
            # Kembalikan 200 agar klien bisa menampilkan UI “butuh foto lebih jelas”
            return JSONResponse(status_code=200, content=jsonable_encoder(payload))

        # Penting: reset pointer UploadFile sebelum dipakai downstream (uc.execute)
        try:
            await img.seek(0)
        except Exception:
            try:
                img.file.seek(0)
            except Exception:
                pass

        # 4) Lanjut verifikasi normal
        req = VerifyRequest(nie=eff_nie, text=eff_text)
        result = await uc.execute(payload=req, image=img)

        sid = _resolve_session_id({"session_id": session_id_form}, session_id_hdr)

        # 5) Simpan ke session bila tersedia
        if sid:
            data = result.get("data", {}) or {}
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
                "confidence": result.get("confidence"),
                "explanation": result.get("explanation"),
            }
            await sess.save_verification(sid, tosave)

        return result

    except HTTPException:
        # Pertahankan error eksplisit lain (misal auth, dsb) apa adanya
        raise
    except Exception as e:
        logger.exception("verify-photo failed")
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
from app.presentation.routes import scan as scan_routes
router.include_router(scan_routes.router, prefix="/scan")

# ── NEW: DETECT (snapshot & url) ──────────────────────────────────
from app.presentation.endpoints.detect import router as detect_router
router.include_router(detect_router)

# ── NEW: WebSocket real-time ──────────────────────────────────────
from app.presentation.endpoints.ws_detect import router as ws_router
router.include_router(ws_router)

# ── AGENT: Orchestrator ──────────────────────────────────────────
@router.post("/agent")
async def agent_endpoint(
    request: Request,
    req: dict = Body(...),
    sess: SessionStateService = Depends(get_session_state),
    prompts: PromptService = Depends(get_prompt_service),
    orchestrator: AgentOrchestrator = Depends(get_agent_orchestrator),
    session_id_hdr: str | None = Header(None, alias="X-Session-Id"),
):
    t0 = time.monotonic()
    try:
        # Prefer session_id; fallback ke user-session agar kompatibel
        sid_body = req.get("session_id")
        session_id = _resolve_session_id(req, session_id_hdr)
        user_text = req.get("text")


        if not session_id:
            raise HTTPException(400, "Missing session id. Provide body 'session_id' or header 'X-Session-Id'.")
        if not user_text or not str(user_text).strip():
            raise HTTPException(400, "Missing 'text' in body")

        ctx = await sess.get_agent_context(session_id)
        ctx = ctx or {}

        label = classify(user_text or "", ctx)
        try:
            await sess.set_last_intent(session_id, label)
        except Exception:
            pass


        out = await orchestrator.handle(convo=ctx, user_msg=user_text, context=ctx)

        # Normalisasi output agar aman
        if not isinstance(out, dict):
            out = {"answer": str(out) if out is not None else "", "sources": []}

        # Simpan turn
        await sess.append_turn(session_id, "user", user_text)
        await sess.append_turn(
            session_id, "assistant", out.get("answer", ""), {"sources": out.get("sources", [])}
        )

        # Tambah 1 system turn agar nama/NIE selalu muncul di history
        try:
            await sess.append_turn(
                sid, "system",
                f"Produk terverifikasi: {prod.get('name')} (NIE {prod.get('nie')}); "
                f"Produsen: {prod.get('manufacturer') or '-'}; Status: {data.get('status') or '-'}."
            )
        except Exception:
            pass


        # === LOG AGENT REPLY (structured) ===
        latency_ms = int((time.monotonic() - t0) * 1000)
        sources = out.get("sources") or []
        usage   = out.get("usage") or {}
        model   = out.get("model") or getattr(orchestrator, "model_name", None)

        # Truncate default; bisa override dengan AGENT_LOG_FULL=1
        if os.getenv("AGENT_LOG_FULL") == "1":
            log_user = user_text
            log_answer = out.get("answer", "")
        else:
            log_user = _preview(user_text, 300)
            log_answer = _preview(out.get("answer", ""), 600)

        payload = {
            "event": "agent.reply",
            "session_id": session_id,
            "latency_ms": latency_ms,
            "model": model,
            "usage": usage,  # ex: {"prompt_tokens":..., "completion_tokens":..., "total_tokens":...}
            "sources_count": len(sources),
            "source_types": sorted({(s.get("type") if isinstance(s, dict) else str(type(s))) for s in sources}),
            "user_text_preview": log_user,
            "answer_preview": log_answer,
        }
        agent_logger.info(json.dumps(payload, ensure_ascii=False))

        logger.info("[agent] sid header=%s body=%s used=%s ua=%s",
            session_id_hdr, sid_body, session_id, request.headers.get("user-agent"))

        return {"reply_kind": "agent", **out}

    except HTTPException:
        raise
    except Exception as e:
        # Log error dengan session_id & durasi supaya gampang tracing
        latency_ms = int((time.monotonic() - t0) * 1000)
        agent_logger.exception(
            "agent.reply_failed session_id=%s latency_ms=%s err=%s",
            session_id if 'session_id' in locals() else None, latency_ms, e
        )
        raise HTTPException(500, f"Agent failed: {e}")

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
