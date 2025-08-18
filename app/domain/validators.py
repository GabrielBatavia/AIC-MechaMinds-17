from dataclasses import dataclass
from typing import Optional, Literal

@dataclass
class BpomValidation:
    number: Optional[str]
    confidence: float
    pattern_id: Optional[str] = None
    notes: Optional[str] = None

class BpomValidator:
    def validate(self, text: str) -> BpomValidation:
        raise NotImplementedError
