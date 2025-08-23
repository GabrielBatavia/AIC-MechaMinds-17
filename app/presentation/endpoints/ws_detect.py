# app/presentation/endpoints/ws_detect.py
from __future__ import annotations

import json
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.application.stream.rt_worker import RTWorker, FrameMsg
from app.infra.vision.yolo_detector import YoloDetector

# Router ini TIDAK pakai prefix "/v1" supaya ikut prefix dari parent router.
router = APIRouter(tags=["ws"])

# Shared detector untuk WS
_detector = YoloDetector()

def _token_valid(token: str | None) -> bool:
    return bool(token) and token == os.getenv("API_KEY")

@router.websocket("/ws/detect")
async def ws_detect(ws: WebSocket, token: str | None = Query(default=None)):
    """
    WebSocket real-time:
    - Client mengirim JSON: {"seq": int, "frame": "<base64_jpeg>"}
    - Server mengembalikan JSON: {"seq": int, "result": {...}}
    """
    if not _token_valid(token):
        # 4401 = Unauthorized (kode kustom umum untuk WS)
        await ws.close(code=4401)
        return

    await ws.accept()
    worker = RTWorker(_detector, process_every=int(os.getenv("WS_PROCESS_EVERY", "2")))
    await worker.start()

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            await worker.push(FrameMsg(seq=int(msg.get("seq", 0)), b64=msg["frame"]))

            # Kirim hasil terakhir (non-blocking). Bisa identical dengan req seq.
            if worker.last_result is not None:
                await ws.send_json({"seq": msg.get("seq"), "result": worker.last_result})
    except WebSocketDisconnect:
        pass
    finally:
        await worker.stop()
