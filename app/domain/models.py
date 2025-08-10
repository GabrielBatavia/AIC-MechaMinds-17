# app/domain/models.py
from pydantic import BaseModel

class Product(BaseModel):
    nie: str
    name: str
    manufacturer: str
    active: bool
    state: str
    updated_at: str
