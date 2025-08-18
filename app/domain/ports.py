# app/domain/ports.py
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ===== Ports lama (dipakai flow /verify, repo, cache, LLM) =====

class OcrPort(ABC):
    @abstractmethod
    async def extract(self, img: Path) -> str: ...

class SatusehatPort(ABC):
    @abstractmethod
    async def smart_lookup(self, nie: Optional[str], text: Optional[str]) -> Tuple[Optional[Any], str]: ...

class RepoPort(ABC):
    """Kontrak minimal yang dipakai MongoVerificationRepo."""
    @abstractmethod
    async def ensure_indexes(self) -> None: ...

    @abstractmethod
    async def find_by_nie(self, nie: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def search_lexical(self, q: str, limit: int = 25, atlas_index: Optional[str] = None) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def get_by_int_ids(self, ids: List[int]) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def save_lookup(self, nie: str, status: str) -> None: ...

class CachePort(ABC):
    @abstractmethod
    async def get(self, key: str): ...
    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int = 43200): ...

class LlmPort(ABC):
    @abstractmethod
    async def explain(self, verdict): ...

# ===== Ports baru (opsional; untuk pipeline /v1/scan) =====
# Catatan: adapter kita sekarang tidak subclass port2 ini, jadi ini hanya referensi kontrak.

class YoloPort(ABC):
    """Boleh sync karena YOLO kita dipanggil sinkron."""
    @abstractmethod
    def detect(self, image_np) -> List[Dict[str, Any]]: ...  # list of {x1,y1,x2,y2,conf,cls}

class OcrLinePort(ABC):
    """OCR baris singkat untuk title; kembalikan (text, ms) atau (lines, ms)."""
    @abstractmethod
    def ocr_title_text(self, image_np) -> Tuple[Optional[str], int]: ...
    @abstractmethod
    def ocr_lines(self, image_np) -> Tuple[List[Dict[str, Any]], int]: ...

class OcrFullPort(ABC):
    @abstractmethod
    def ocr_lines(self, image_np) -> Tuple[List[Dict[str, Any]], int]: ...

class SearchPort(ABC):
    @abstractmethod
    async def search(self, text: str, k: int = 5) -> List[Dict[str, Any]]: ...
    @abstractmethod
    async def search_best(self, text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], float]: ...

class RegexValidatorPort(ABC):
    @abstractmethod
    def validate(self, text: str) -> Any: ...  # e.g., BpomValidation
