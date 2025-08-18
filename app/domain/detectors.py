# app/domain/detectors.py
import re
from pathlib import Path
from .models import Product
from pydantic import BaseModel


def clean_nie(raw: str) -> str:
    return re.sub(r'[^A-Za-z0-9]', '', raw).upper()

async def extract_info(cmd, ocr):
    """
    Return (nie, raw_text).
    OCR is awaited only when an image is present.
    """
    text = cmd.raw_text
    if cmd.image_path:                       # ← image supplied
        text = await ocr.extract(Path(cmd.image_path))

    nie = cmd.raw_nie
    if not nie:
        m = re.search(r'[A-Z]{1,3}[0-9]{8,11}[A-Z0-9]{0,2}', text or "")
        nie = m.group(0) if m else None
    return nie, text

class VerificationResult(BaseModel):
    status: str
    source: str
    product: Product | None = None
    flags: list[str] = []

def interpret(prod: Product | None) -> VerificationResult:
    if prod is None:
        return VerificationResult(status="not_found", source="none")
    if not prod.active or prod.state != "valid":
        return VerificationResult(status="inactive", source="satusehat", product=prod)
    return VerificationResult(status="registered", source="satusehat", product=prod)
