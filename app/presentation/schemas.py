# app/presentation/schemas.py
from pydantic import BaseModel, Field

class VerifyRequest(BaseModel):
    nie: str | None = Field(None, description="Raw BPOM/NIE code")
    text: str | None = Field(None, description="OCR text (optional)")

class VerificationPayload(BaseModel):
    status: str
    source: str
    product: dict | None = None
    flags: list[str] = []

class VerifyResponse(BaseModel):
    data: VerificationPayload
    message: str

