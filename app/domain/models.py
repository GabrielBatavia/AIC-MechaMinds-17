# app/domain/models.py
from pydantic import BaseModel

class Product(BaseModel):
    nie: str
    name: str
    manufacturer: str
    dosage_form: str | None = None
    strength: str | None = None
    composition: str | None = None
    category: str | None = None
    status: str | None = None
    faiss_id: int | None = None
    active: bool = True
    state: str = "valid"
    _score: float | None = None
    source: str | None = None
    updated_at: str | None = None
