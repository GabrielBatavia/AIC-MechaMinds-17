# app/infra/ocr/tesseract_title_adapter.py
import os, time
from typing import List, Tuple, Dict, Any
import cv2, pytesseract

def _maybe_set_tesseract_cmd():
    # Prioritas: ENV TESSERACT_CMD; fallback path umum di Windows
    cmd = os.getenv("TESSERACT_CMD")
    if cmd and os.path.exists(cmd):
        pytesseract.pytesseract.tesseract_cmd = cmd
        return
    for p in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            return

class TesseractTitleAdapter:
    """
    OCR adapter ringan untuk ekstrak teks (terutama judul) memakai Tesseract.
    Mengembalikan:
      - ocr_lines(img) -> (list[{text, conf, box}], ms)
      - ocr_title_text(img_crop) -> (text|None, conf|None, ms)
    """
    def __init__(self, lang: str = "eng", psm: int = 6):
        _maybe_set_tesseract_cmd()
        self.lang = lang
        # PSM 6 = Assume a single uniform block of text
        self.config = f"--psm {psm} -l {self.lang}"

    def _preproc(self, img):
        if img is None:
            return None
        if len(img.shape) == 3:
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            g = img
        # denoise ringan + adaptive threshold
        g = cv2.bilateralFilter(g, 5, 75, 75)
        try:
            g = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                      cv2.THRESH_BINARY, 31, 9)
        except Exception:
            pass
        return g

    def ocr_lines(self, img) -> Tuple[List[Dict[str, Any]], int]:
        t0 = time.time()
        lines: List[Dict[str, Any]] = []
        pp = self._preproc(img)
        if pp is None:
            return lines, 0

        data = pytesseract.image_to_data(pp, output_type=pytesseract.Output.DICT, config=self.config)
        n = len(data.get("text", []))
        for i in range(n):
            txt = (data["text"][i] or "").strip()
            if not txt:
                continue
            conf_raw = data["conf"][i]
            try:
                conf = float(conf_raw) / 100.0 if conf_raw not in ("-1", "", None) else 0.0
            except Exception:
                conf = 0.0
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            box = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
            lines.append({"text": txt, "conf": conf, "box": box})

        ms = int((time.time() - t0) * 1000)
        return lines, ms

    def ocr_title_text(self, img_crop) -> Tuple[str | None, float | None, int]:
        lines, ms = self.ocr_lines(img_crop)
        if not lines:
            return None, None, ms
        best = max(lines, key=lambda x: len(x["text"]) * x["conf"])
        return best["text"], float(best["conf"]), ms
