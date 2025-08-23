# app/presentation/endpoints/detect.py
from __future__ import annotations

import io
from typing import Literal

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel, HttpUrl
from PIL import Image

from app.infra.vision.yolo_detector import YoloDetector

# Router ini TIDAK pakai prefix "/v1" supaya ikut prefix dari parent router.
router = APIRouter(tags=["detect"])

# Single, shared detector instance untuk REST
_detector = YoloDetector()

class DetectResult(BaseModel):
    ok: bool
    mode: Literal["snapshot", "url"]
    result: dict

class DetectURLReq(BaseModel):
    url: HttpUrl


@router.post("/detect", response_model=DetectResult)
async def detect_image(file: UploadFile = File(...)):
    """
    Upload satu gambar (JPEG/PNG/WebP) → deteksi YOLO → kembalikan JSON ringkas.
    """
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail=f"Unsupported image type: {file.content_type}")

    img_bytes = await file.read()
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"Invalid image: {e}")

    res = _detector.detect_pil(img)
    return DetectResult(ok=True, mode="snapshot", result=res)


@router.post("/detect-url", response_model=DetectResult)
async def detect_url(body: DetectURLReq):
    """
    Tarik gambar dari URL (mis. signed URL S3/GCS) → deteksi YOLO → JSON.
    """
    import requests
    try:
        r = requests.get(str(body.url), timeout=10)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"Failed to load image: {e}")

    res = _detector.detect_pil(img)
    return DetectResult(ok=True, mode="url", result=res)
