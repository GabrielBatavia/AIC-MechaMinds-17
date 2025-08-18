from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Literal, Dict

@dataclass
class Box:
    x1: float; y1: float; x2: float; y2: float
    conf: float
    cls: str  # "title" | "package" | ...

@dataclass
class OCRLine:
    text: str
    conf: float
    box: List[Tuple[int, int]]

@dataclass
class ScanResult:
    request_id: str
    stage: Literal["partial", "final"]
    title_text: Optional[str] = None
    title_conf: Optional[float] = None
    bpom_number: Optional[str] = None
    match: Optional[dict] = None          # pastikan ada {_score, source, ...}
    winner: Optional[str] = None          # "mongo" | "atlas" | "faiss"
    timings: Dict[str, float] = field(default_factory=dict)  # yolo_ms, ocr_title_ms, ...

class MergePolicy:
    @staticmethod
    def merge(first: ScanResult, second: ScanResult) -> ScanResult:
        out = ScanResult(**{**first.__dict__})  # copy safe
        if not out.title_text and second.title_text:
            out.title_text = second.title_text
            out.title_conf = second.title_conf or out.title_conf
        if not out.bpom_number and second.bpom_number:
            out.bpom_number = second.bpom_number
        if not out.match and second.match:
            out.match = second.match
            out.winner = second.winner or out.winner
        out.stage = "final"
        out.timings = {**first.timings, **second.timings}
        return out
