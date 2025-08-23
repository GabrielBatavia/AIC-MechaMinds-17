# app/infra/vision/yolo_detector.py
from __future__ import annotations

import os
import threading
from typing import Any, Dict, List

import numpy as np
from PIL import Image
from ultralytics import YOLO

_WEIGHTS_DEFAULT = "models/yolo/yolo11m.pt"


class YoloDetector:
    """
    Thread-safe singleton loader untuk YOLO.
    Menyediakan:
      - detect(np.ndarray | PIL.Image)
      - detect_pil(PIL.Image)
      - warmup()
    Output schema:
    {
      "boxes": [[x1,y1,x2,y2], ...],
      "classes": [int, ...],
      "scores": [float, ...],
      "names": {cls_id: name, ...}
    }
    """
    _lock = threading.Lock()
    _model = None

    def __init__(self):
        with YoloDetector._lock:
            if YoloDetector._model is None:
                weights = os.getenv("YOLO_WEIGHTS", _WEIGHTS_DEFAULT)
                YoloDetector._model = YOLO(weights)
        self.model = YoloDetector._model
        self.names = getattr(self.model, "names", {}) or {}
        self.imgsz = int(os.getenv("YOLO_IMG_SIZE", "640"))
        # Opsional: mapping class "title"
        self.title_id = int(os.getenv("YOLO_TITLE_CLASS_ID", "1"))
        self.title_name = os.getenv("YOLO_TITLE_CLASS_NAME", "title")

    # --- Public API -------------------------------------------------

    def warmup(self):
        """Jalankan sekali untuk menghindari cold start."""
        dummy = Image.new("RGB", (320, 240), (0, 0, 0))
        _ = self.detect_pil(dummy)

    def detect(self, img: np.ndarray | Image.Image) -> List[dict]:
        """
        Versi lama (dipertahankan untuk kompatibilitas).
        Mengembalikan list dict per box.
        """
        res = self.model(img, imgsz=self.imgsz, verbose=False)
        out = []
        for r in res:
            for b in r.boxes:
                cls_id = int(b.cls[0])
                cls_name = self.names.get(cls_id, str(cls_id))
                conf = float(b.conf[0])
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                out.append(
                    {"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                     "conf": conf, "cls_id": cls_id, "cls": cls_name}
                )
        return out

    def detect_pil(self, img: Image.Image) -> Dict[str, Any]:
        """
        Versi baru yang mengembalikan schema ringkas (lebih mudah untuk Web).
        """
        res = self.model(img, imgsz=self.imgsz, verbose=False)
        boxes, classes, scores = [], [], []
        for r in res:
            if not hasattr(r, "boxes") or r.boxes is None:
                continue
            for b in r.boxes:
                classes.append(int(b.cls[0]))
                scores.append(float(b.conf[0]))
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                boxes.append([x1, y1, x2, y2])
        return {"boxes": boxes, "classes": classes, "scores": scores, "names": self.names}
