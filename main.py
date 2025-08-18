# main.py
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from app.presentation.routers import router
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()   # forces .env load

app = FastAPI(title="MedVerify-AI")
app.include_router(router)

@app.get("/healthz")
async def health():
    return {"ok": True}


@app.on_event("startup")
async def warmup():
    import numpy as np
    from app.infra.vision.yolo_detector import YoloDetector
    det = YoloDetector()
    det.detect(np.zeros((640,640,3), dtype='uint8'))  # warm YOLO

    import os
    if os.getenv("OCR_ENGINE","tesseract").lower() != "tesseract":
        try:
            from app.infra.ocr.paddle_adapter import PaddleOCRAdapter
            ocr = PaddleOCRAdapter()
            ocr.ocr_lines(np.zeros((64,256,3), dtype='uint8'))  # trigger model load
        except Exception:
            pass