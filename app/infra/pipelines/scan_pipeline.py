# app/infra/pipelines/scan_pipeline.py
import os, re
import asyncio, uuid, time
import cv2, numpy as np
from app.infra.vision.yolo_detector import YoloDetector
from app.infra.regex.bpom_validator import RegexBpomValidator

def _norm_title(s: str) -> str:
    s = (s or "").upper()
    s = re.sub(r'[^A-Z0-9\s]+', ' ', s)
    s = re.sub(r'\b(TAB(LET)?|KAPLET|KAPSUL(ES)?|SIRUP|SYRUP|SUSP(ENSI)?|INJEKSI|SAL(AP)?|KRIM|CREAM|OINTMENT|GEL|DROP|SPRAY)\b', ' ', s)
    s = re.sub(r'\b(MG|ML|MCG|GRAM|G|KG)\b', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

class ScanPipeline:
    """
    T1: YOLO → crop title → OCR(title) → search (k=1)
        (client akan lock & verify jika OCR title_conf ≥ threshold)

    T2: (gated) OCR(full) → regex BPOM
        dijalankan hanya bila YOLO title_conf ≥ YOLO_REGEX_THRESH (ENV, default 0.70)
    """
    def __init__(self, query_service):
        self.det = YoloDetector()

        engine = os.getenv("OCR_ENGINE", "tesseract").lower()
        if engine == "tesseract":
            from app.infra.ocr.tesseract_title_adapter import TesseractTitleAdapter
            self.ocr = TesseractTitleAdapter()
        else:
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

        title_candidates = [
            b for b in boxes
            if b.get("cls_id") == self.det.title_id or b.get("cls") == self.det.title_name
        ]
        title_box = max(title_candidates, key=lambda b: b["conf"], default=None)
        yolo_title_conf = float(title_box["conf"]) if title_box else 0.0

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
                text, conf, ms = self.ocr.ocr_title_text(title_crop)
                timings["ocr_title_ms"] = ms
                clean = _norm_title(text) if text else None

                top = None
                if clean:
                    s0 = time.time()
                    hits = await self.query.search(clean, k=1)
                    timings["search_ms"] = int((time.time() - s0) * 1000)
                    if hits:
                        d = hits[0]
                        top = {"product": d, "source": d.get("_src"), "confidence": d.get("_score")}

                return {
                    "request_id": req_id, "stage": "partial",
                    "title_text": clean, "title_conf": conf, "match": top,
                    "boxes": boxes, "title_box": title_box
                }
            except Exception:
                return {
                    "request_id": req_id, "stage": "partial",
                    "title_text": None, "title_conf": None, "match": None,
                    "boxes": boxes, "title_box": title_box
                }

        async def t2_task():
            try:
                if yolo_title_conf < self.yolo_regex_thresh:
                    return {
                        "request_id": req_id, "stage": "final",
                        "bpom_number": None, "regex_skipped": True,
                        "boxes": boxes, "title_box": title_box
                    }
                t_start = time.time()
                lines, ms = self.ocr.ocr_lines(img)
                timings["ocr_full_ms"] = ms
                full = "\n".join(l["text"] for l in lines)
                v = self.regex.validate(full)
                timings["regex_ms"] = max(0, int((time.time() - t_start) * 1000) - ms)
                return {
                    "request_id": req_id, "stage": "final",
                    "bpom_number": v.number,
                    "boxes": boxes, "title_box": title_box
                }
            except Exception:
                return {
                    "request_id": req_id, "stage": "final",
                    "bpom_number": None,
                    "boxes": boxes, "title_box": title_box
                }

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

        # Jika 'final' menang duluan, tunggu T1 sejenak untuk merge title/match
        if first.get("stage") == "final" and pending:
            try:
                rest_task = next(iter(pending))
                rest = await asyncio.wait_for(rest_task, timeout=0.12)
                if isinstance(rest, dict):
                    for k in ("title_text", "title_conf", "match"):
                        if rest.get(k) is not None:
                            first[k] = rest[k]
            except asyncio.TimeoutError:
                pass
            finally:
                for p in pending:
                    p.cancel()

        if not return_partial and pending:
            remain = max(0.0, (t2_timeout_ms - t1_timeout_ms) / 1000)
            rest_done, rest_pending = await asyncio.wait(pending, timeout=remain)
            if rest_done:
                first.update(list(rest_done)[0].result() or {})
                first["stage"] = "final"
            for p in rest_pending:
                p.cancel()

        timings["total_ms"] = int((time.time() - t0) * 1000)
        first["timings"] = timings
        first["yolo_title_conf"] = yolo_title_conf  # info untuk client
        return first
