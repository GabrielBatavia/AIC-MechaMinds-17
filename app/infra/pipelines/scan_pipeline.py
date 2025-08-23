# app/infra/pipelines/scan_pipeline.py
# app/infra/pipelines/scan_pipeline.py
import os, re
import asyncio, uuid, time
import cv2, numpy as np
from app.infra.vision.yolo_detector import YoloDetector
from app.infra.regex.bpom_validator import RegexBpomValidator

import logging
log = logging.getLogger("app.scan.pipeline")

# app/infra/pipelines/scan_pipeline.py
import re

# Precompile for speed & clarity
_NON_ALNUM = re.compile(r'[^A-Z0-9\s]+')
_FORMS = re.compile(
    r'\b(TAB(LET)?|KAPLET|KAPSUL(ES)?|SIRUP|SYRUP|SUSP(ENSI)?|INJEKSI|SAL(AP)?|KRIM|CREAM|OINTMENT|GEL|DROP|SPRAY)\b',
    flags=re.I
)
_UNITS = re.compile(r'\b(MG|ML|MCG|GRAM|G|KG)\b', flags=re.I)
_SPACES = re.compile(r'\s+')

def _norm_title(s: str) -> str:
    """
    Normalisasi judul produk agar lebih stabil untuk pencarian:
    - Uppercase
    - Hilangkan simbol non-alfanumerik
    - Hilangkan kata bentuk sediaan & satuan umum
    - Satu spasi
    """
    s = "" if s is None else str(s)
    s = s.upper()
    s = _NON_ALNUM.sub(' ', s)
    s = _FORMS.sub(' ', s)      # <-- includes string argument
    s = _UNITS.sub(' ', s)      # <-- includes string argument
    s = _SPACES.sub(' ', s).strip()
    return s


class ScanPipeline:
    """
    Pipeline ekstraksi dari foto label:

    T1: YOLO → crop title → OCR(title) → search(k=1)
        (client bisa segera pakai match bila conf-ok)

    T2: (gated) OCR(full) → regex BPOM untuk ambil nomor registrasi
        * Secara default T2 hanya jalan bila yolo_title_conf >= YOLO_REGEX_THRESH
        * Bisa dipaksa selalu jalan dengan env ALWAYS_RUN_REGEX=1

    ENV:
      - OCR_ENGINE = "tesseract" (default) | "paddle"
      - YOLO_REGEX_THRESH = float, default "0.70"
      - ALWAYS_RUN_REGEX = "0|1|true|false|yes|no" (default "0")
    """

    def __init__(self, query_service):
        self.det = YoloDetector()

        engine = os.getenv("OCR_ENGINE", "tesseract").lower()
        if engine == "tesseract":
            from app.infra.ocr.tesseract_title_adapter import TesseractTitleAdapter
            self.ocr = TesseractTitleAdapter()
        else:
            # fallback aman
            try:
                from app.infra.ocr.paddle_adapter import PaddleOCRAdapter
                self.ocr = PaddleOCRAdapter()
            except Exception:
                from app.infra.ocr.tesseract_title_adapter import TesseractTitleAdapter
                self.ocr = TesseractTitleAdapter()

        self.regex = RegexBpomValidator()
        self.query = query_service

        # Gate untuk menjalankan OCR(full)+regex
        self.yolo_regex_thresh = float(os.getenv("YOLO_REGEX_THRESH", "0.70"))

        # NEW: flag untuk memaksa T2 selalu jalan walau YOLO conf rendah
        self.always_run_regex = str(os.getenv("ALWAYS_RUN_REGEX", "0")).strip().lower() in {"1", "true", "yes"}

    def _decode(self, data: bytes):
        arr = np.frombuffer(data, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Invalid image")
        h, w = img.shape[:2]
        longest = max(h, w)
        if longest > 1600:
            scale = 1600 / longest
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        return img

    async def run(
        self,
        data: bytes,
        *,
        return_partial: bool = True,
        t1_timeout_ms: int = 500,
        t2_timeout_ms: int = 1200,
        extra_ctx: dict | None = None,
    ):
        req_id = str(uuid.uuid4())
        t0 = time.time()
        timings = {
            "yolo_ms": 0, "ocr_title_ms": 0, "search_ms": 0,
            "ocr_full_ms": 0, "regex_ms": 0, "total_ms": 0
        }

        img = self._decode(data)

        # === YOLO detect ===
        y0 = time.time()
        boxes = self.det.detect(img)
        timings["yolo_ms"] = int((time.time() - y0) * 1000)

        seen_ids = sorted({b["cls_id"] for b in boxes}) if boxes else []
        log.info(
            "[scan] YOLO ms=%d boxes=%d seen_ids=%s title_id=%d name=%s",
            timings["yolo_ms"], len(boxes), seen_ids, self.det.title_id, self.det.title_name
        )

        # Pilih box title dengan confidence tertinggi
        title_candidates = [
            b for b in (boxes or [])
            if b.get("cls_id") == self.det.title_id or b.get("cls") == self.det.title_name
        ]
        title_box = max(title_candidates, key=lambda b: b["conf"], default=None)
        yolo_title_conf = float(title_box["conf"]) if title_box else 0.0
        log.info("[scan] title_candidates=%d yolo_title_conf=%.3f", len(title_candidates), yolo_title_conf)

        # Crop untuk OCR title (pakai padding kecil); fallback ke full image bila tidak ada box
        if title_box is not None:
            x1, y1, x2, y2 = title_box["x1"], title_box["y1"], title_box["x2"], title_box["y2"]
            pad = 6
            x1 = max(0, x1 - pad); y1 = max(0, y1 - pad)
            x2 = min(img.shape[1] - 1, x2 + pad); y2 = min(img.shape[0] - 1, y2 + pad)
            title_crop = img[y1:y2, x1:x2]
        else:
            title_crop = img

        async def t1_task():
            try:
                # OCR judul
                text, conf, ms = self.ocr.ocr_title_text(title_crop)
                timings["ocr_title_ms"] = ms
                clean = _norm_title(text) if text else None
                log.info(
                    "[scan] OCR(title) ms=%d conf=%.3f raw='%s' clean='%s'",
                    ms, float(conf or 0.0), text, clean
                )

                top = None
                if clean:
                    s0 = time.time()
                    hits = await self.query.search(clean, k=1)
                    timings["search_ms"] = int((time.time() - s0) * 1000)
                    log.info("[scan] search(title) q='%s' hits=%d ms=%d", clean, len(hits), timings["search_ms"])
                    if hits:
                        d = hits[0]
                        top = {"product": d, "source": d.get("_src"), "confidence": d.get("_score")}

                return {
                    "request_id": req_id, "stage": "partial",
                    "title_text": clean, "title_conf": conf, "match": top,
                    "boxes": boxes, "title_box": title_box
                }
            except Exception as e:
                log.exception("[scan] t1_task failed: %s", e)
                return {
                    "request_id": req_id, "stage": "partial",
                    "title_text": None, "title_conf": None, "match": None,
                    "boxes": boxes, "title_box": title_box
                }

        async def t2_task():
            try:
                # Gate eksekusi OCR(full)+regex kecuali dipaksa selalu jalan
                if not self.always_run_regex and yolo_title_conf < self.yolo_regex_thresh:
                    log.info(
                        "[scan] regex SKIPPED (yolo_conf=%.3f < %.3f)",
                        yolo_title_conf, self.yolo_regex_thresh
                    )
                    return {
                        "request_id": req_id, "stage": "final",
                        "bpom_number": None, "regex_skipped": True,
                        "boxes": boxes, "title_box": title_box
                    }

                t_start = time.time()
                lines, ms = self.ocr.ocr_lines(img)
                timings["ocr_full_ms"] = ms
                log.info("[scan] OCR(full) lines=%d ms=%d", len(lines), ms)

                full = "\n".join(l.get("text", "") for l in lines)
                v = self.regex.validate(full)

                # Kurangi waktu OCR dari total untuk estimasi murni regex
                timings["regex_ms"] = max(0, int((time.time() - t_start) * 1000) - ms)
                log.info(
                    "[scan] regex result number=%s conf=%.3f parse_ms=%d",
                    v.number, float(v.confidence or 0.0), timings["regex_ms"]
                )

                return {
                    "request_id": req_id, "stage": "final",
                    "bpom_number": v.number,
                    "regex_skipped": False,
                    "boxes": boxes, "title_box": title_box
                }
            except Exception as e:
                log.exception("[scan] t2_task failed: %s", e)
                return {
                    "request_id": req_id, "stage": "final",
                    "bpom_number": None,
                    "regex_skipped": False,
                    "boxes": boxes, "title_box": title_box
                }

        # Jalankan T1 & T2 paralel, ambil yang selesai duluan
        a = asyncio.create_task(t1_task())
        b = asyncio.create_task(t2_task())
        done, pending = await asyncio.wait(
            {a, b},
            timeout=max(0.01, t1_timeout_ms / 1000),
            return_when=asyncio.FIRST_COMPLETED
        )

        if done:
            first = list(done)[0].result()
        else:
            first = {
                "request_id": req_id, "stage": "partial",
                "title_text": None, "title_conf": None, "match": None,
                "boxes": boxes, "title_box": title_box
            }
        
        t1, t2 = a, b

        def _merge_title(dst: dict, src: dict | None):
            if isinstance(src, dict):
                for k in ("title_text", "title_conf", "match"):
                    if src.get(k) is not None:
                        dst[k] = src[k]

        def _merge_regex(dst: dict, src: dict | None):
            if isinstance(src, dict):
                for k in ("bpom_number", "regex_skipped"):
                    if k in src:
                        dst[k] = src[k]

        # --- NEW: if the other task is ALREADY done, merge immediately (no timeout) ---
        try:
            if first.get("stage") == "final":
                if t1.done():
                    _merge_title(first, t1.result())
            else:  # first == partial (T1)
                if t2.done():
                    _merge_regex(first, t2.result())
        except Exception:
            pass


        # Jika final menang duluan, tunggu sebentar hasil T1 untuk merge info title/match
        if first.get("stage") == "final" and pending:
            try:
                rest_task = next(iter(pending))
                rest = await asyncio.wait_for(rest_task, timeout=100)
                _merge_title(first, rest if isinstance(rest, dict) else None)
            except asyncio.TimeoutError:
                pass
            finally:
                for p in pending:
                    p.cancel()

        # Jika caller ingin final saja, tunggu sisa task sampai batas T2
        if not return_partial and pending:
            remain = max(0.0, (t2_timeout_ms - t1_timeout_ms) / 1000)
            rest_done, rest_pending = await asyncio.wait(pending, timeout=remain)
            if rest_done:
                try:
                    merged = list(rest_done)[0].result() or {}
                    first.update(merged)
                    first["stage"] = "final"
                finally:
                    pass
            for p in rest_pending:
                p.cancel()

        timings["total_ms"] = int((time.time() - t0) * 1000)
        first["timings"] = timings
        first["yolo_title_conf"] = yolo_title_conf  # info untuk client
        return first
