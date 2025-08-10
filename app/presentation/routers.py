# app/presentation/routers.py
from fastapi import APIRouter, Depends, UploadFile, File, Body
from .schemas import VerifyRequest, VerifyResponse
from app.application.use_cases import get_verify_uc

router = APIRouter(prefix="/v1")

@router.post("/verify", response_model=VerifyResponse)
async def verify_label(
    req: VerifyRequest = Body(None),
    img: UploadFile | None = File(None),
    uc = Depends(get_verify_uc),
):
    return await uc.execute(payload=req, image=img)
