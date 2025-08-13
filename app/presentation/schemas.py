from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, List, Optional


# ── VERIFY (existing) ─────────────────────────────────────────────

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


# ── SEARCH (new) ─────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., description="Teks/OCR/NIE/judul produk")
    k: int = Field(5, ge=1, le=20, description="Jumlah kandidat yang dikembalikan")


class SearchItem(BaseModel):
    _id: Any
    name: Optional[str] = None
    nie: Optional[str] = None
    dosage_form: Optional[str] = None
    composition: Optional[str] = None
    manufacturer: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    _score: Optional[float] = None
    _src: Optional[str] = None


class SearchResponse(BaseModel):
    items: List[SearchItem]
    system_prompt: str
