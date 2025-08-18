# app/infra/ocr/paddle_adapter.py
import time
from paddleocr import PaddleOCR

class PaddleOCRAdapter:
    _ocr = None

    def __init__(self):
        if PaddleOCRAdapter._ocr is None:
            # use_angle_cls only at init; panggilan .ocr() tanpa arg 'cls'
            PaddleOCRAdapter._ocr = PaddleOCR(use_angle_cls=True, lang='en')
        self.engine = PaddleOCRAdapter._ocr

    def _parse_result(self, res):
        """
        Normalisasi berbagai bentuk output PaddleOCR menjadi list[{"text","conf","box"}].
        Support:
        - Format lama: [[ [box, (text, conf)], ... ], ...]
        - Format baru: list[dict] atau dict dengan key 'data'
        """
        lines = []
        if not res:
            return lines

        # A) format lama (list of lists)
        if isinstance(res, list) and res and isinstance(res[0], list):
            for block in res:
                for tl in block:
                    try:
                        box = tl[0]
                        txt = (tl[1][0] or "").strip()
                        conf = float(tl[1][1]) if tl[1][1] is not None else 0.0
                        if txt:
                            lines.append({"text": txt, "conf": conf, "box": box})
                    except Exception:
                        continue
            return lines

        # B) format dict / list of dict (paddleocr>=3 kadang return demikian)
        def coerce_items(items):
            for it in items:
                txt = (it.get("text") or it.get("label") or "").strip()
                if not txt:
                    continue
                conf = it.get("confidence", it.get("score", 0.0)) or 0.0
                try:
                    conf = float(conf)
                except Exception:
                    conf = 0.0
                box = it.get("box") or it.get("bbox") or it.get("points") or it.get("poly")
                yield {"text": txt, "conf": conf, "box": box}

        if isinstance(res, dict):
            items = res.get("data") or res.get("boxes") or res.get("results") or []
            lines.extend(list(coerce_items(items)))
            return lines

        if isinstance(res, list) and res and isinstance(res[0], dict):
            lines.extend(list(coerce_items(res)))
            return lines

        return lines

    def ocr_lines(self, img):
        t0 = time.time()
        try:
            # API baru: cukup .ocr(img) — tanpa argumen 'cls'
            res = self.engine.ocr(img)
        except TypeError:
            # fallback lain (beberapa build lama menerima flags det/rec)
            try:
                res = self.engine.ocr(img, det=True, rec=True)
            except Exception:
                res = []
        except Exception:
            res = []

        lines = self._parse_result(res)
        return lines, int((time.time() - t0) * 1000)

    def ocr_title_text(self, img_crop):
        lines, ms = self.ocr_lines(img_crop)
        if not lines:
            return None, None, ms
        best = max(lines, key=lambda x: len(x["text"]) * x["conf"])
        return best["text"], float(best["conf"]), ms
