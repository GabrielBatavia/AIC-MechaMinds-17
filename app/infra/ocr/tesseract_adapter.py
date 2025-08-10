# app/infra/ocr/tesseract_adapter.py
import pytesseract, asyncio
from app.domain.ports import OcrPort
from pathlib import Path

class TesseractAdapter(OcrPort):
    async def extract(self, img: Path) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, pytesseract.image_to_string, img)
