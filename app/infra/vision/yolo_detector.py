# app/infra/vision/yolo_detector.py
import os, threading
from ultralytics import YOLO

weights = os.getenv("YOLO_WEIGHTS", "models/yolo/yolo11m.pt")


class YoloDetector:
    _lock = threading.Lock()
    _model = None

    def __init__(self):
        with YoloDetector._lock:
            if YoloDetector._model is None:
                weights = os.getenv("YOLO_WEIGHTS", "models/yolo/yolo11m.pt")
                YoloDetector._model = YOLO(weights)
        self.model = YoloDetector._model
        # ambil label dari model kalau ada
        self.names = getattr(self.model, "names", {}) or {}
        # kamu minta class=1 dianggap title (override via ENV kalau perlu)
        self.title_id = int(os.getenv("YOLO_TITLE_CLASS_ID", "1"))
        self.title_name = os.getenv("YOLO_TITLE_CLASS_NAME", "title")

    def detect(self, img):
        res = self.model(img, imgsz=int(os.getenv("YOLO_IMG_SIZE","640")), verbose=False)
        out = []
        for r in res:
            for b in r.boxes:
                cls_id = int(b.cls[0])
                cls_name = self.names.get(cls_id, str(cls_id))
                conf = float(b.conf[0])
                x1,y1,x2,y2 = map(int, b.xyxy[0])
                out.append({
                    "x1":x1,"y1":y1,"x2":x2,"y2":y2,
                    "conf":conf,"cls_id":cls_id,"cls":cls_name
                })
        return out