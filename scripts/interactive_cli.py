# /scripts/interactive_cli.py
# Interactive CLI to exercise full MedVerify flow end-to-end:
# 1) Manual input (BPOM/NIE or product title) -> /v1/verify
# 2) OCR via webcam or image file -> /v1/scan/photo -> /v1/verify
# 3) (NEW) Post-verify chat: free-form Q&A to /v1/agent with Redis session memory
#
# Usage:
#   python scripts/interactive_cli.py
#   python scripts/interactive_cli.py --verify-url http://127.0.0.1:8000/v1/verify --scan-url http://127.0.0.1:8000/v1/scan/photo --agent-url http://127.0.0.1:8000/v1/agent
#
# Requires: requests, opencv-python (only for OCR)

from __future__ import annotations
import argparse, json, sys, uuid, time, os
from typing import Optional, Dict, Any

try:
    import cv2
except Exception:
    cv2 = None

import requests

# Reuse helpers from webcam_scan if available; else define minimal fallbacks
try:
    from scripts.webcam_scan import post_frame as _post_frame, post_verify as _post_verify
except Exception:
    _post_frame = None
    _post_verify = None


# -------------------------------
# HTTP helpers
# -------------------------------
def post_verify(verify_url: str, *, nie: Optional[str]=None, text: Optional[str]=None,
                headers: Optional[dict]=None, timeout:int=30) -> dict:
    payload = {}
    if nie: payload["nie"] = nie
    if text: payload["text"] = text
    resp = requests.post(verify_url, json=payload, headers=headers or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def post_scan_frame(scan_url: str, frame, return_partial: bool=True, quality:int=90,
                    headers: Optional[dict]=None, timeout:int=30) -> dict:
    if _post_frame and headers is None:
        # reuse webcam_scan helper (no headers support); else use local
        return _post_frame(scan_url, frame, return_partial=return_partial, quality=quality, timeout=timeout)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Failed to encode JPEG")
    files = {"img": ("frame.jpg", buf.tobytes(), "image/jpeg")}
    data = {"return_partial": "true" if return_partial else "false"}
    resp = requests.post(scan_url, files=files, data=data, headers=headers or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def post_agent(agent_url: str, *, session_id: str, text: str, timeout:int=60) -> dict:
    payload = {"session_id": session_id, "text": text}
    resp = requests.post(agent_url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# -------------------------------
# CLI utilities
# -------------------------------
def parse_args():
    ap = argparse.ArgumentParser(description="Interactive MedVerify CLI (verify + OCR + agent chat)")
    ap.add_argument("--verify-url", default="http://127.0.0.1:8000/v1/verify", help="Verify endpoint URL")
    ap.add_argument("--scan-url", default="http://127.0.0.1:8000/v1/scan/photo", help="Scan (OCR) endpoint URL")
    ap.add_argument("--agent-url", default="http://127.0.0.1:8000/v1/agent", help="Agent chat endpoint URL")
    ap.add_argument("--session-id", default=None, help="Use a fixed X-Session-Id (else auto-generate)")
    ap.add_argument("--device", type=int, default=0, help="Webcam device index")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--show-trace", action="store_true", help="Print evidence trace for verify response")
    ap.add_argument("--auto-agent-threshold", type=float, default=0.80,
                    help="If confidence < threshold OR status unknown, auto-ask agent to double-check sources")
    return ap.parse_args()

def header_with_session(session_id: str) -> dict:
    return {"X-Session-Id": session_id}

def print_div():
    print("-" * 64)

def color(s: str, c: str) -> str:
    # minimal ANSI color
    colors = {
        "green": "\033[92m", "red": "\033[91m", "yellow": "\033[93m",
        "cyan": "\033[96m", "blue": "\033[94m", "mag": "\033[95m", "end": "\033[0m"
    }
    return f"{colors.get(c,'')}{s}{colors['end']}"

def status_color(status: str) -> str:
    s = (status or "unknown").lower()
    if s in ("valid","registered","active","aktif"): return "green"
    if s in ("invalid","revoked","expired","unregistered","not_registered"): return "red"
    return "yellow"


# -------------------------------
# Rendering
# -------------------------------
def print_verify_summary(resp: dict, show_trace: bool=False):
    print_div()
    if not isinstance(resp, dict):
        print("Invalid response:", resp); return
    data = resp.get("data", {}) or {}
    msg  = resp.get("message", "")
    conf = resp.get("confidence")
    src  = resp.get("source")
    expl = resp.get("explanation", "")
    prod = data.get("product", {}) or {}

    st = (data.get("status") or "unknown")
    print(f"{color('RESULT', 'cyan')}: status={color(st, status_color(st))} | source={src} | confidence={conf}")
    print(f"{color('NAME', 'cyan')}: {prod.get('name') or '-'}")
    print(f"{color('NIE', 'cyan')}: {prod.get('nie') or '-'}")
    print(f"{color('MFR', 'cyan')}: {prod.get('manufacturer') or '-'}")
    print(f"{color('UPDATED', 'cyan')}: {prod.get('updated_at') or '-'}")
    if expl:
        print(f"{color('EXPLANATION', 'blue')}: {expl}")
    if msg:
        print(f"{color('MESSAGE', 'blue')}: {msg}")

    if show_trace:
        trace = resp.get("trace") or []
        if trace:
            print_div()
            print(color("TRACE (evidence):", "cyan"))
            for i, ev in enumerate(trace, 1):
                try:
                    ps = float(ev.get('provider_score') or 0.0)
                    q  = float(ev.get('quality') or 0.0)
                    r  = float(ev.get('recency_factor') or 0.0)
                    nc = float(ev.get('name_confidence') or 0.0)
                except Exception:
                    ps,q,r,nc = 0.0,0.0,0.0,0.0
                print(f"[{i}] src={ev.get('source')} match={ev.get('match_strength')} ps={ps:.2f} q={q:.2f} r={r:.2f} name_conf={nc:.2f}")
                reasons = ev.get("reasons") or []
                if reasons:
                    print("     reasons:", "; ".join(reasons))
        else:
            print("(no evidence trace)")

def print_agent_answer(resp: dict):
    # Expect: {"reply_kind":"agent","answer":str,"sources":[{"url","title"}], ...}
    print_div()
    ans = (resp or {}).get("answer") or ""
    print(color("AGENT", "mag") + ": " + ans)
    srcs = (resp or {}).get("sources") or []
    if srcs:
        print(color("SOURCES", "cyan") + ":")
        for i, s in enumerate(srcs, 1):
            title = (s.get("title") or "").strip()
            url   = (s.get("url") or "").strip()
            print(f"  [{i}] {title if title else url}  -> {url}")


# -------------------------------
# Post-verify Agent Flow
# -------------------------------
def maybe_auto_double_check(agent_url: str, session_id: str, verify_resp: dict, threshold: float, timeout: int):
    """Auto-ask agent to double-check if confidence low OR status unknown/invalid."""
    try:
        conf = float(verify_resp.get("confidence") or 0.0)
    except Exception:
        conf = 0.0
    status = ((verify_resp.get("data") or {}).get("status") or "unknown").lower()

    should = (conf < threshold) or (status in ("unknown", "invalid", "unregistered", "not_registered"))
    if not should:
        return

    prod = ((verify_resp.get("data") or {}).get("product") or {})
    name = prod.get("name") or ""
    nie  = prod.get("nie") or ""
    q = f"Tolong cek ulang validitas produk ini dari sumber resmi (BPOM). Nama: {name or '-'}, NIE: {nie or '-'}. Beri tautan/halaman rujukan jika ada."
    try:
        resp = post_agent(agent_url, session_id=session_id, text=q, timeout=max(60, timeout))
        print_agent_answer(resp)
    except Exception as e:
        print(color("Auto double-check error:", "red"), e)

def agent_chat_loop(agent_url: str, session_id: str, timeout: int):
    print_div()
    print(color("Mode tanya-jawab agent. Ketik apa saja (enter kosong untuk keluar).", "cyan"))
    while True:
        user = input(color("You:", "blue") + " ").strip()
        if not user:
            break
        try:
            resp = post_agent(agent_url, session_id=session_id, text=user, timeout=max(60, timeout))
            print_agent_answer(resp)
        except requests.HTTPError as e:
            body = getattr(e, "response", None)
            print(color("HTTP error:", "red"), e, body.text if body is not None else "")
        except Exception as e:
            print(color("Error:", "red"), e)


# -------------------------------
# Flows
# -------------------------------
def prompt_menu() -> str:
    print_div()
    print("MedVerify Interactive")
    print("1) Masukkan NIE / Judul produk (manual)")
    print("2) Gunakan OCR (webcam / file gambar)")
    print("q) Keluar")
    choice = input("Pilih [1/2/q]: ").strip().lower()
    return choice

def manual_flow(verify_url: str, agent_url: str, session_id: str, timeout: int,
                show_trace: bool, auto_agent_threshold: float):
    print_div()
    print("Manual verification")
    nie = input("Masukkan NIE (BPOM) [kosongkan jika tidak ada]: ").strip()
    name = ""
    if not nie:
        name = input("Masukkan judul/nama produk: ").strip()
        if not name:
            print("Tidak ada input. Batal.")
            return
    try:
        resp = post_verify(verify_url, nie=nie or None, text=name or None,
                           headers=header_with_session(session_id), timeout=timeout)
        print_verify_summary(resp, show_trace=show_trace)

        # NEW: auto double-check w/ agent if needed
        maybe_auto_double_check(agent_url, session_id, resp, auto_agent_threshold, timeout)

        # NEW: optionally continue chatting with agent
        cont = input("Lanjut bertanya lebih dalam ke agent? [y/N]: ").strip().lower()
        if cont == "y":
            agent_chat_loop(agent_url, session_id, timeout)

    except requests.HTTPError as e:
        print("HTTP error:", e, getattr(e, "response", None).text if getattr(e, "response", None) else "")
    except Exception as e:
        print("Error:", e)

def ocr_from_image(scan_url: str, verify_url: str, agent_url: str, img_path: str,
                   session_id: str, timeout: int, show_trace: bool, auto_agent_threshold: float):
    if cv2 is None:
        print("OpenCV belum terpasang. Install: pip install opencv-python")
        return
    if not os.path.exists(img_path):
        print(f"Gambar tidak ditemukan: {img_path}")
        return
    frame = cv2.imread(img_path)
    if frame is None:
        print("Gagal membaca gambar.")
        return

    try:
        scan = post_scan_frame(scan_url, frame, return_partial=True,
                               headers=header_with_session(session_id), timeout=timeout)
    except requests.HTTPError as e:
        print("Scan HTTP error:", e, getattr(e, "response", None).text if getattr(e, "response", None) else "")
        return
    except Exception as e:
        print("Scan error:", e); return

    print(color("SCAN RESULT:", "cyan"), json.dumps({
        "stage": scan.get("stage"),
        "title_text": scan.get("title_text"),
        "bpom_number": scan.get("bpom_number"),
        "title_conf": scan.get("title_conf"),
        "yolo_title_conf": scan.get("yolo_title_conf"),
    }, ensure_ascii=False))

    nie = scan.get("bpom_number")
    text = scan.get("title_text")
    if not text:
        match = scan.get("match") or {}
        prod = match.get("product") or {}
        text = prod.get("name") or prod.get("brand")

    if not nie and (not text or not str(text).strip()):
        print("Tidak ada NIE atau title hasil OCR. Tidak bisa verifikasi.")
        return

    try:
        vr = post_verify(verify_url, nie=nie, text=text,
                         headers=header_with_session(session_id), timeout=max(20, timeout))
        print_verify_summary(vr, show_trace=show_trace)

        # NEW: auto double-check w/ agent if needed
        maybe_auto_double_check(agent_url, session_id, vr, auto_agent_threshold, timeout)

        cont = input("Lanjut bertanya lebih dalam ke agent? [y/N]: ").strip().lower()
        if cont == "y":
            agent_chat_loop(agent_url, session_id, timeout)

    except requests.HTTPError as e:
        print("Verify HTTP error:", e, getattr(e, "response", None).text if getattr(e, "response", None) else "")
    except Exception as e:
        print("Verify error:", e)

def ocr_from_webcam(scan_url: str, verify_url: str, agent_url: str, device: int, w: int, h: int,
                    session_id: str, timeout: int, show_trace: bool, auto_agent_threshold: float):
    if cv2 is None:
        print("OpenCV belum terpasang. Install: pip install opencv-python")
        return
    cap = cv2.VideoCapture(device, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(device)
    if not cap.isOpened():
        print("Tidak bisa membuka kamera")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

    print("Tekan [SPACE] untuk ambil 1 frame, atau [q] untuk batal.")
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Gagal membaca frame.")
            break
        disp = frame.copy()
        cv2.putText(disp, "Press [SPACE] to capture, [q] to quit", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,255), 2, cv2.LINE_AA)
        cv2.imshow("MedVerify OCR Capture", disp)
        k = cv2.waitKey(1) & 0xFF
        if k == ord(' '):
            try:
                scan = post_scan_frame(scan_url, frame, return_partial=True,
                                       headers=header_with_session(session_id), timeout=timeout)
            except Exception as e:
                print("Scan error:", e)
                continue
            print(color("SCAN RESULT:", "cyan"), json.dumps({
                "stage": scan.get("stage"),
                "title_text": scan.get("title_text"),
                "bpom_number": scan.get("bpom_number"),
                "title_conf": scan.get("title_conf"),
                "yolo_title_conf": scan.get("yolo_title_conf"),
            }, ensure_ascii=False))

            nie = scan.get("bpom_number")
            text = scan.get("title_text")
            if not text:
                match = scan.get("match") or {}
                prod = match.get("product") or {}
                text = prod.get("name") or prod.get("brand")
            if not nie and (not text or not str(text).strip()):
                print("Tidak ada NIE/title dari OCR. Ambil lagi (SPACE) atau [q] untuk keluar.")
                continue

            try:
                vr = post_verify(verify_url, nie=nie, text=text,
                                 headers=header_with_session(session_id), timeout=max(20, timeout))
                print_verify_summary(vr, show_trace=show_trace)

                # NEW: auto double-check w/ agent if needed
                maybe_auto_double_check(agent_url, session_id, vr, auto_agent_threshold, timeout)

                cont = input("Lanjut bertanya lebih dalam ke agent? [y/N]: ").strip().lower()
                if cont == "y":
                    agent_chat_loop(agent_url, session_id, timeout)

            except Exception as e:
                print("Verify error:", e)
        elif k == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

def ocr_flow(scan_url: str, verify_url: str, agent_url: str, device: int, w: int, h: int,
             session_id: str, timeout: int, show_trace: bool, auto_agent_threshold: float):
    print_div()
    print("OCR Mode:")
    print("1) Webcam (ambil 1 frame)")
    print("2) File gambar")
    sub = input("Pilih [1/2]: ").strip()
    if sub == "1":
        ocr_from_webcam(scan_url, verify_url, agent_url, device, w, h, session_id, timeout, show_trace, auto_agent_threshold)
    elif sub == "2":
        path = input("Path file gambar: ").strip().strip('"').strip("'")
        ocr_from_image(scan_url, verify_url, agent_url, path, session_id, timeout, show_trace, auto_agent_threshold)
    else:
        print("Pilihan tidak dikenal.")

# -------------------------------
# Main
# -------------------------------
def main():
    args = parse_args()
    session_id = args.session_id or f"cli-{uuid.uuid4()}"
    print(color(f"Session: {session_id}", "cyan"))
    print("Server endpoints:")
    print(f"  verify: {args.verify_url}")
    print(f"  scan  : {args.scan_url}")
    print(f"  agent : {args.agent_url}")

    while True:
        choice = prompt_menu()
        if choice == "1":
            manual_flow(args.verify_url, args.agent_url, session_id, args.timeout, args.show_trace, args.auto_agent_threshold)
        elif choice == "2":
            ocr_flow(args.scan_url, args.verify_url, args.agent_url, args.device, args.width, args.height,
                     session_id, args.timeout, args.show_trace, args.auto_agent_threshold)
        elif choice == "q":
            print("Bye.")
            break
        else:
            print("Pilihan tidak dikenal.")

if __name__ == "__main__":
    main()
