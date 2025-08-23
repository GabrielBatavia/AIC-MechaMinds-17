# app/infra/ocr/tesseract_adapter.py
import pytesseract, asyncio, tempfile, os, io
from pathlib import Path
from typing import Union
from PIL import Image
import numpy as np
from app.domain.ports import OcrPort


class TesseractAdapter(OcrPort):
    async def extract(self, img: Union[Path, bytes, bytearray, np.ndarray, Image.Image]) -> str:
        """Terima Path/bytes/ndarray/PIL, pastikan jadi Path sementara untuk pytesseract."""
        tmp_path: Path | None = None
        try:
            if isinstance(img, Path):
                path = img
            elif isinstance(img, (bytes, bytearray)):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    tmp.write(bytes(img))
                    tmp_path = Path(tmp.name)
                path = tmp_path
            elif isinstance(img, Image.Image):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    img.save(tmp, format="PNG")
                    tmp_path = Path(tmp.name)
                path = tmp_path
            elif isinstance(img, np.ndarray):
                pil = Image.fromarray(img)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    pil.save(tmp, format="PNG")
                    tmp_path = Path(tmp.name)
                path = tmp_path
            else:
                raise TypeError(f"Unsupported image type: {type(img)}")

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, pytesseract.image_to_string, path)
        finally:
            if tmp_path is not None:
                try: os.remove(tmp_path)
                except Exception: pass
