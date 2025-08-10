# app/application/commands.py 
from pydantic import BaseModel, Field
from pathlib import Path

class VerifyLabelCommand(BaseModel):
    raw_nie: str | None = None
    raw_text: str | None = None
    image_path: Path | None = None

