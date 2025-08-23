# app/application/stream/rt_worker.py
from __future__ import annotations

import asyncio
import base64
import contextlib
import io
from dataclasses import dataclass
from PIL import Image


@dataclass
class FrameMsg:
    seq: int
    b64: str  # base64 encoded JPEG/WebP


class RTWorker:
    """
    Worker real-time dengan backpressure (queue size = 1).
    - Jika antrian penuh → drop frame lama (hindari penumpukan).
    - process_every: proses tiap-N frame untuk throttle.
    - last_result: hasil deteksi terakhir (untuk dikirim cepat ke klien).
    """
    def __init__(self, detector, process_every: int = 2):
        self.detector = detector
        self.process_every = max(1, int(process_every))
        self.q: asyncio.Queue[FrameMsg] = asyncio.Queue(maxsize=1)
        self._task: asyncio.Task | None = None
        self._seq_seen = 0
        self.last_result: dict | None = None

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def push(self, msg: FrameMsg):
        if self.q.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                _ = self.q.get_nowait()  # drop yang lama
        await self.q.put(msg)

    async def _loop(self):
        while True:
            msg = await self.q.get()
            self._seq_seen += 1
            if (self._seq_seen % self.process_every) != 0:
                continue

            try:
                img_bytes = base64.b64decode(msg.b64)
                img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                self.last_result = self.detector.detect_pil(img)
            except Exception as e:
                # Simpan error agar klien bisa melihat kegagalan
                self.last_result = {"error": f"detect failed: {e}"}
