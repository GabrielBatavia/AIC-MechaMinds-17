# main.py
from dotenv import load_dotenv
load_dotenv()

import os
import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pathlib import Path
from fastapi import UploadFile, File, HTTPException
from fastapi import Response
import io
import uuid
import logging
from fastapi import Request



# Router utama v1 (sudah dilindungi X-Api-Key via dependencies di routers.py)
from app.presentation.routers import router as v1_router

app = FastAPI(
    title="MedVerify-AI",
    version=os.getenv("APP_VERSION", "0.1.0"),
)

# --- logging config HARUS di atas ---
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# gunakan logger aplikasi sendiri, bukan 'uvicorn.access'
app_logger = logging.getLogger("medverify.request")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    app_logger.info(f"➡️ Incoming {request.method} {request.url.path}")
    try:
        response = await call_next(request)
        app_logger.info(f"⬅️ Completed {request.method} {request.url.path} -> {response.status_code}")
        return response
    except Exception:
        app_logger.exception(f"❌ Unhandled error on {request.method} {request.url.path}")
        raise

# ─────────────────────────────────────────────────────────────
# CORS (atur via env: CORS_ALLOW_ORIGINS="https://foo.com,https://bar.com")
# ─────────────────────────────────────────────────────────────
raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
allow_origins = [o.strip().rstrip("/") for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://quail-enormous-cobra.ngrok-free.app",
        "https://pulseprotect.vercel.app",    # buat production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Files / Uploads directory
# ─────────────────────────────────────────────────────────────
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads")).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


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


@app.get("/ping")
def ping():
    return {"message": "Server YOLO aktif"}


ALLOWED_CT = {"image/jpeg", "image/png", "image/webp"}

@app.post("/receive-image")
async def receive_image(file: UploadFile = File(...)):
    try:
        # Baca file bytes
        contents = await file.read()

        # Buka pakai PIL buat dapetin info gambar
        image = Image.open(io.BytesIO(contents))
        image_size = image.size  # (width, height)
        image_format = image.format

        # Generate nama unik biar gak ketimpa
        unique_filename = f"{uuid.uuid4()}.{image_format.lower() if image_format else 'jpg'}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)

        # Simpan ke folder
        with open(file_path, "wb") as f:
            f.write(contents)

        return {
            "status": "success",
            "message": "Gambar berhasil diterima dan disimpan",
            "image_details": {
                "original_filename": file.filename,
                "saved_filename": unique_filename,
                "save_path": file_path,
                "size": image_size,
                "format": image_format,
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.options("/{rest_of_path:path}")
async def any_options(rest_of_path: str):
    return Response(status_code=204)