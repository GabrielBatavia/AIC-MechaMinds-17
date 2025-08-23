# app/presentation/schemas.py
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal

# ── VERIFY (existing) ─────────────────────────────────────────────
class VerifyRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Session id (if not using header)")
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
    _id: Any | None = None
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

# ── SCAN (photo) ─────────────────────────────────────────────────
class ScanRequest(BaseModel):
    return_partial: bool = Field(default=True)

class MatchDoc(BaseModel):
    product: Dict[str, Any]
    source: str | None = None
    confidence: float | None = None

class Timings(BaseModel):
    yolo_ms: int = 0
    ocr_title_ms: int = 0
    search_ms: int = 0
    ocr_full_ms: int = 0
    regex_ms: int = 0
    total_ms: int = 0

class BoxItem(BaseModel):
    x1:int; y1:int; x2:int; y2:int
    conf: float
    cls_id: int
    cls: str

class ScanResponse(BaseModel):
    request_id: str
    stage: Literal["partial", "final"]
    title_text: Optional[str] = None
    title_conf: Optional[float] = None
    bpom_number: Optional[str] = None
    match: Optional[Dict[str, Any]] = None
    winner: Optional[str] = None
    timings: Dict[str, int]
    boxes: Optional[List[BoxItem]] = None
    title_box: Optional[BoxItem] = None


class EvidenceSchema(BaseModel):
    source: str
    product_id: Optional[str]
    name: Optional[str]
    match_strength: str
    quality: float
    recency_factor: float
    name_confidence: float
    provider_score: float
    reasons: List[str]
    payload: Dict[str, Any] = {}
    debug: Dict[str, Any] = {}

class VerificationResponse(BaseModel):
    data: Dict[str, Any]
    message: str
    confidence: float
    source: str
    explanation: str
    trace: List[EvidenceSchema] = []
    flags: List[str] = []


class VerificationPartial(BaseModel):
    reply_kind: Literal["scan_incomplete"] = "scan_incomplete"
    need_more_input: bool = True
    reason: str
    suggestions: List[str] = []
    # Info tambahan untuk UI/telemetri (opsional, struktur longgar)
    scan: dict = {}