# app/domain/models/confidence.py
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime

class EvidenceSource(str, Enum):
    MONGO = "mongo"
    FAISS = "faiss"
    WEB   = "web"

class MatchStrength(str, Enum):
    EXACT = "exact"
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"
    NONE = "none"

@dataclass
class Evidence:
    source: EvidenceSource
    product_id: Optional[str]         # e.g., NIE
    name: Optional[str]
    payload: Dict[str, Any]           # raw fields from provider
    match_strength: MatchStrength     # mapping dari skor provider
    quality: float                    # 0..1 kelengkapan/keandalan data
    recency_factor: float             # 0..1 makin baru makin tinggi
    name_confidence: float            # 0..1 (OCR/regex dsb)
    provider_score: float             # skor asli provider jika ada (e.g., FAISS sim)
    reasons: List[str]                # alasan kenapa evidence dianggap valid
    debug: Dict[str, Any] = None

@dataclass
class VerificationResult:
    decision: str                    # "valid" | "invalid" | "unknown"
    confidence: float                # 0..1
    top_source: EvidenceSource
    explanation: str
    winner: Evidence
    all_evidence: List[Evidence]
