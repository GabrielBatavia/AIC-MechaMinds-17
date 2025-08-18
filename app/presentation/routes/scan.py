# app/presentation/routes/scan.py
from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, Body, Depends, HTTPException, Form
from app.presentation.schemas import ScanRequest, ScanResponse
from app.application.scan_use_case import ScanUseCase
from app.container import get_scan_use_case  # provider we'll add in container
from uuid import uuid4

router = APIRouter()

ALLOWED_CT = {"image/jpeg", "image/png", "image/webp"}

@router.post("/photo", response_model=ScanResponse)
async def scan_photo(
    img: UploadFile = File(...),
    return_partial: bool = Form(True),
    uc = Depends(get_scan_use_case),
):
    try:
        data = await img.read()
        out = await uc.run_single_shot(data, return_partial=return_partial)
        if out is None:
            raise RuntimeError("ScanPipeline returned None")
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"scan_photo failed: {e}")