# main.py
from dotenv import load_dotenv
load_dotenv()

import os
import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Router utama v1 (sudah dilindungi X-Api-Key via dependencies di routers.py)
from app.presentation.routers import router as v1_router

app = FastAPI(
    title="MedVerify-AI",
    version=os.getenv("APP_VERSION", "0.1.0"),
)

# ─────────────────────────────────────────────────────────────
# CORS (atur via env: CORS_ALLOW_ORIGINS="https://foo.com,https://bar.com")
# ─────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────
app.include_router(v1_router, tags=["api"])

@app.get("/")
async def root():
    return {
        "name": "MedVerify-AI",
        "version": os.getenv("APP_VERSION", "0.1.0"),
        "ok": True,
    }

@app.get("/healthz")
async def healthz():
    # Liveness: proses hidup
    return {"ok": True}

@app.get("/readyz")
async def readyz():
    """
    Readiness: komponen eksternal siap?
    - Mongo index/akses
    - Redis ping (jika ada)
    - SearchRouter basic call
    - OPENAI_API_KEY tersedia (untuk agent)
    """
    from app.container import get_verify_uc as _get_uc
    uc = _get_uc()

    checks = {}
    ok = True

    # Mongo
    try:
        await uc.repo.ensure_indexes()
        checks["mongo"] = True
    except Exception as e:
        checks["mongo"] = False
        checks["mongo_error"] = str(e)
        ok = False

    # Redis
    try:
        pong = await uc.cache.ping() if hasattr(uc.cache, "ping") else True
        checks["redis"] = bool(pong)
        ok = ok and bool(pong)
    except Exception as e:
        checks["redis"] = False
        checks["redis_error"] = str(e)
        ok = False

    # Search router (lex/faiss)
    try:
        _ = await uc.search.search("paracetamol", k=1)
        checks["search_router"] = True
    except Exception as e:
        checks["search_router"] = False
        checks["search_router_error"] = str(e)
        ok = False

    # LLM config (opsional)
    checks["openai_configured"] = bool(os.getenv("OPENAI_API_KEY"))

    return {"ok": ok, **checks}

# ─────────────────────────────────────────────────────────────
# Startup warm-up (YOLO & OCR) agar first-hit cepat
# ─────────────────────────────────────────────────────────────
@app.on_event("startup")
async def warmup():
    # Warm YOLO
    try:
        from app.infra.vision.yolo_detector import YoloDetector
        det = YoloDetector()
        det.detect(np.zeros((640, 640, 3), dtype="uint8"))
    except Exception:
        pass

    # Warm OCR (jika bukan tesseract)
    try:
        if os.getenv("OCR_ENGINE", "tesseract").lower() != "tesseract":
            from app.infra.ocr.paddle_adapter import PaddleOCRAdapter
            ocr = PaddleOCRAdapter()
            ocr.ocr_lines(np.zeros((64, 256, 3), dtype="uint8"))
    except Exception:
        pass
