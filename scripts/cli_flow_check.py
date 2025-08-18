# /scripts/cli_flow_check.py
from __future__ import annotations
import argparse, sys, time, uuid, io, os
import requests

def print_step(title):
    print(f"\n=== {title} ===")

def pretty(o, indent=2):
    import json
    return json.dumps(o, indent=indent, ensure_ascii=False)

def make_synthetic_image(text: str, w=1200, h=400):
    """Buat PNG dengan teks besar (agar OCR mudah)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        print("[scan] Pillow belum terinstall. Skip generate gambar sintetis.")
        return None, None, None
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    try:
        # coba font umum; fallback default
        font = ImageFont.truetype("arial.ttf", size=140)
    except Exception:
        font = ImageFont.load_default()
    tw, th = d.textsize(text, font=font)
    d.text(((w - tw) / 2, (h - th) / 2), text, fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue(), "synthetic.png", "image/png"

def do_search(base, q, k):
    print_step("SEARCH /v1/search")
    t0 = time.perf_counter()
    r = requests.post(f"{base}/v1/search", json={"query": q, "k": k}, timeout=30)
    dt = (time.perf_counter() - t0) * 1000
    print(f"HTTP {r.status_code} in {dt:.0f} ms")
    if not r.ok:
        print(r.text); sys.exit(1)
    data = r.json()
    items = data.get("items", [])
    print(f"Top {len(items)} results:")
    for i, it in enumerate(items[:5], 1):
        name = it.get("name"); nie = it.get("nie"); src = it.get("_src"); score = it.get("_score")
        print(f"{i:2d}. {name} — NIE={nie}  [{src}|{score}]")
    return data

def do_verify(base, session_id, text, nie):
    print_step("VERIFY /v1/verify")
    payload = {"text": text, "nie": nie}
    t0 = time.perf_counter()
    r = requests.post(f"{base}/v1/verify", json=payload, timeout=60)
    dt = (time.perf_counter() - t0) * 1000
    print(f"HTTP {r.status_code} in {dt:.0f} ms")
    if not r.ok:
        print(r.text); sys.exit(1)
    data = r.json()
    print("status:", data.get("data", {}).get("status"))
    print("source:", data.get("data", {}).get("source"))
    prod = data.get("data", {}).get("product") or {}
    if prod:
        print("matched:", prod.get("name"), "| NIE:", prod.get("nie"))
    print("message:", (data.get("message") or "")[:160], "...")
    return data

def do_scan(base, nie, image_path=None, return_partial=True):
    print_step("SCAN /v1/scan/photo")
    if image_path:
        fn = os.path.basename(image_path)
        ct = "image/jpeg" if fn.lower().endswith((".jpg",".jpeg")) else "image/png"
        with open(image_path, "rb") as f:
            file_tuple = (fn, f.read(), ct)
    else:
        img_bytes, fn, ct = make_synthetic_image(nie)
        if not img_bytes:
            print("[scan] Tidak ada gambar. Skip.")
            return None
        file_tuple = (fn, img_bytes, ct)

    files = {"file": file_tuple}
    # NB: route kamu default return_partial=True, jadi tidak wajib kirim form/JSON extra
    t0 = time.perf_counter()
    r = requests.post(f"{base}/v1/scan/photo", files=files, timeout=90)
    dt = (time.perf_counter() - t0) * 1000
    print(f"HTTP {r.status_code} in {dt:.0f} ms")
    if not r.ok:
        print(r.text); return None
    data = r.json()
    print("stage:", data.get("stage"))
    print("title_text:", data.get("title_text"))
    print("bpom_number:", data.get("bpom_number"))
    m = data.get("match") or {}
    if m:
        prod = m.get("product") or {}
        print("match:", prod.get("name"), "| NIE:", prod.get("nie"), "| source:", m.get("source"), "| conf:", m.get("confidence"))
    t = data.get("timings") or {}
    if t:
        print("timings(ms):", t)
    return data

def main():
    ap = argparse.ArgumentParser(description="MedVerify flow checker (search/verify/scan).")
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="Base URL FastAPI server")
    ap.add_argument("--nie", required=True, help="Kode BPOM/NIE atau teks judul")
    ap.add_argument("--k", type=int, default=5, help="Top-K untuk /v1/search")
    ap.add_argument("--scan", action="store_true", help="Ikut tes /v1/scan/photo")
    ap.add_argument("--image", help="Path gambar untuk /v1/scan/photo (opsional)")
    args = ap.parse_args()

    session_id = str(uuid.uuid4())
    print(f"Session: {session_id}")
    print(f"Base   : {args.base}")

    # 1) SEARCH
    search_res = do_search(args.base, args.nie, args.k)

    # 2) VERIFY
    verify_res = do_verify(args.base, session_id, text=args.nie, nie=args.nie)

    # 3) SCAN (opsional)
    scan_res = None
    if args.scan:
        scan_res = do_scan(args.base, args.nie, image_path=args.image)

    print_step("SUMMARY")
    ok = True
    if verify_res.get("data", {}).get("status") in ("verified", "inactive", "registered"):
        print("✅ verify: OK")
    else:
        print("⚠️  verify: status =", verify_res.get("data", {}).get("status"))
        ok = False

    if search_res.get("items"):
        print("✅ search: OK (items:", len(search_res["items"]), ")")
    else:
        print("⚠️  search: no items")
        ok = False

    if args.scan:
        if scan_res and scan_res.get("stage") in ("partial","final"):
            print("✅ scan: OK (stage:", scan_res.get("stage"), ")")
        else:
            print("⚠️  scan: no response or error")
            ok = False

    print("\nRESULT:", "PASS ✅" if ok else "CHECK NEEDED ⚠️")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
