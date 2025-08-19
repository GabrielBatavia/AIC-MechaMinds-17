# scripts/webcam_scan.py
# Simple webcam → POST frame to /v1/scan/photo
# Controls:
#   q = quit, s = send single frame, a = toggle auto mode, r = resume after lock

import argparse, time, json, threading
import cv2, requests
from copy import deepcopy

def post_frame(url, frame, return_partial=True, quality=90, timeout=10):
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Failed to encode JPEG")
    files = {"img": ("frame.jpg", buf.tobytes(), "image/jpeg")}
    data = {"return_partial": "true" if return_partial else "false"}
    resp = requests.post(url, files=files, data=data, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def post_verify(verify_url, *, nie=None, text=None, timeout=20):
    payload = {}
    if nie: payload["nie"] = nie
    if text: payload["text"] = text
    resp = requests.post(verify_url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def draw_hud(frame, last_result: dict | None, auto: bool, locked: bool, verif: dict | None):
    h, w = frame.shape[:2]; y = 24
    def put(s):
        nonlocal y
        cv2.putText(frame, s, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2, cv2.LINE_AA)
        y += 22

    put(f"[MedVerify Cam] auto={'ON' if auto else 'OFF'} | lock={'ON' if locked else 'OFF'}  (s=send, a=auto, r=resume, q=quit)")

    if last_result:
        stage   = last_result.get("stage")
        timings = last_result.get("timings", {})
        total   = timings.get("total_ms")
        yolo_c  = last_result.get("yolo_title_conf")
        tconf   = last_result.get("title_conf")
        put(f"stage={stage} total={total}ms  yolo_title_conf={yolo_c if yolo_c is not None else '-'}  ocr_conf={tconf if tconf is not None else '-'}")

        match = last_result.get("match") or {}
        prod = match.get("product") or {}
        cand = prod.get("name") or prod.get("brand")
        if cand:
            put(f"candidate: {cand}")

    if verif:
        data = verif.get("data", {}) or {}
        prod = data.get("product", {}) or {}
        put(f"VERIFIED → {prod.get('name') or '-'}  [{prod.get('nie') or '-'}]")
        put(f"status={data.get('status') or '-'}  source={data.get('source') or '-'}")

def draw_boxes(frame, result):
    if not result: return
    boxes = result.get("boxes") or []
    for b in boxes:
        x1,y1,x2,y2 = b["x1"],b["y1"],b["x2"],b["y2"]
        cls, conf = b.get("cls"), b.get("conf", 0.0)
        cv2.rectangle(frame, (x1,y1), (x2,y2), (0,255,0), 3)
        cv2.putText(frame, f'{cls}:{conf:.2f}', (x1, max(16,y1-8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,0), 2, cv2.LINE_AA)
    tb = result.get("title_box")
    if tb:
        x1,y1,x2,y2 = tb["x1"],tb["y1"],tb["x2"],tb["y2"]
        cv2.rectangle(frame, (x1,y1), (x2,y2), (0,0,255), 3)  # highlight title

def main():
    ap = argparse.ArgumentParser(description="Webcam → /v1/scan/photo")
    ap.add_argument("--url", default="http://127.0.0.1:8000/v1/scan/photo")
    ap.add_argument("--verify-url", default="http://127.0.0.1:8000/v1/verify")
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--interval", type=int, default=700)
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--partial", action="store_true")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--lock-thresh", type=float, default=0.70, help="OCR title confidence threshold [0-1]")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.device, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError("Cannot open camera")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    last_result = None
    last_sent_ms = 0
    auto = args.auto
    sending = False
    send_lock = threading.Lock()
    locked = False
    verif_result = None

    def try_send(frame):
        nonlocal last_result, sending
        with send_lock:
            if sending:
                return
            sending = True
        try:
            res = post_frame(args.url, frame, return_partial=args.partial, quality=args.quality, timeout=args.timeout)
            last_result = res
            print(json.dumps({
                "stage": res.get("stage"),
                "title_text": res.get("title_text"),
                "bpom_number": res.get("bpom_number"),
                "title_conf": res.get("title_conf"),
                "yolo_title_conf": res.get("yolo_title_conf"),
            }, ensure_ascii=False))
            print("boxes:", len(res.get("boxes") or []), " title_box:", bool(res.get("title_box")))
        except Exception as e:
            print("Send error:", e)
        finally:
            sending = False

    def try_verify_async(scan_res):
        nonlocal verif_result
        # Prioritas: NIE → title_text → fallback candidate dari match
        nie = scan_res.get("bpom_number")
        text = scan_res.get("title_text")
        if not text:
            match = scan_res.get("match") or {}
            prod = match.get("product") or {}
            text = prod.get("name") or prod.get("brand")

        if not nie and (not text or not str(text).strip()):
            print("[verify] skip: no NIE or text available")
            return

        try:
            verif_result = post_verify(args.verify_url, nie=nie, text=text, timeout=max(20, args.timeout))
            print("[verify] ok:", (verif_result.get("data", {}) or {}).get("product"))
        except Exception as e:
            print("[verify] error:", e)

    print("Running... (q=quit, s=send single, a=auto, r=resume)")
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        # Auto send unless locked
        now_ms = time.time() * 1000
        if auto and not locked and (now_ms - last_sent_ms >= args.interval) and not sending:
            last_sent_ms = now_ms
            threading.Thread(target=try_send, args=(frame.copy(),), daemon=True).start()

        # Auto-lock: OCR title_conf ≥ threshold OR ada bpom_number
        if not locked and last_result:
            has_bpom = bool(last_result.get("bpom_number"))
            title_text = (last_result.get("title_text") or "").strip()
            title_conf = float(last_result.get("title_conf") or 0.0)
            if has_bpom or (title_text and title_conf >= args.lock_thresh):
                locked = True
                auto = False
                threading.Thread(target=try_verify_async, args=(deepcopy(last_result),), daemon=True).start()

        hud = frame.copy()
        draw_boxes(hud, last_result)
        draw_hud(hud, last_result, auto, locked, verif_result)

        if locked:
            cv2.putText(hud, "LOCKED - press 'r' to resume", (10, hud.shape[0]-16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,200,255), 2, cv2.LINE_AA)

        cv2.imshow("MedVerify Cam", hud)

        k = cv2.waitKey(1) & 0xFF
        if k == ord('q'):
            break
        elif k == ord('a'):
            auto = not auto
        elif k == ord('s'):
            last_sent_ms = now_ms
            threading.Thread(target=try_send, args=(frame.copy(),), daemon=True).start()
        elif k == ord('r'):
            locked = False
            verif_result = None
            last_sent_ms = 0  # kirim lagi segera

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
