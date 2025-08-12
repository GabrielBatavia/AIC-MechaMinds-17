#crawler/cekbpom_detail.py
import os, httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any

BASE = os.getenv("CEKBPOM_BASE", "https://cekbpom.pom.go.id")
UA   = os.getenv("SCRAPER_USER_AGENT", "MedVerifyAI/0.1 (+contact)")

def map_type_code(t: Optional[str]) -> Optional[str]:
    if not t: return None
    t = t.strip().upper()
    return {
        "OB": "05",   # Obat
        "OT": "02",   # Obat tradisional (perkiraan)
        "OK": "03",   # Kosmetika (perkiraan)
        "SK": "04",   # Suplemen (perkiraan)
    }.get(t, None)

async def fetch_detail_modal(product_id: str, type_code: str, referer: str) -> str:
    url = f"{BASE}/produk/{product_id}/{type_code}/detail"
    async with httpx.AsyncClient(
        headers={"User-Agent": UA, "Accept": "text/html", "Referer": referer},
        timeout=30, follow_redirects=True
    ) as c:
        r = await c.get(url); r.raise_for_status()
        return r.text

def parse_detail_modal(html: str) -> Dict[str, Any]:
    s = BeautifulSoup(html, "lxml")
    box = s.select_one(".modal-content") or s
    # Header produk
    badge = (box.select_one(".badge") or {}).get_text(strip=True) if box else None
    prod  = box.select_one(".product")
    name = brand = reg = None
    if prod:
        vals = [d.get_text(strip=True) for d in prod.select("div") if d.get_text(strip=True)]
        if len(vals) >= 2: name  = vals[1]
        if len(vals) >= 3: brand = None if vals[2] == "-" else vals[2]
        if len(vals) >= 4: reg   = vals[3]

    # Tanggal
    published_at = valid_until = None
    d = box.select_one(".product_date")
    if d:
        v = [x.get_text(strip=True) for x in d.select("div") if x.get_text(strip=True)]
        for i, t in enumerate(v):
            low = t.lower()
            if low.startswith("tanggal terbit") and i+1 < len(v): published_at = v[i+1]
            if low.startswith("masa berlaku") and i+1 < len(v):    valid_until  = v[i+1]

    # Komposisi
    composition = None
    ing = box.select_one(".product_ingredients")
    if ing:
        v = [x.get_text(strip=True) for x in ing.select("div") if x.get_text(strip=True)]
        if len(v) >= 2: composition = v[1]

    # Pendaftar + kota/negara
    manufacturer = manufacturer_city = manufacturer_country = None
    man = box.select_one(".manufacturer")
    if man:
        link = man.select_one("a")
        if link:
            txt = link.get_text(strip=True)
            parts = [p.strip() for p in txt.split(" - ", 1)]
            manufacturer = parts[0]
            if len(parts) > 1: manufacturer_country = parts[1]
        tail = [d.get_text(strip=True) for d in man.select("div") if d.get_text(strip=True)]
        if tail:
            v = tail[-1]
            if v and v != "-": manufacturer_city = v

    dosage_form = None
    pf = box.select_one(".product_forms")
    if pf:
        v = [x.get_text(strip=True) for x in pf.select("div") if x.get_text(strip=True)]
        if len(v) >= 2: dosage_form = v[1]

    packaging = None
    pk = box.select_one(".product_package")
    if pk:
        v = [x.get_text(strip=True) for x in pk.select("div") if x.get_text(strip=True)]
        if len(v) >= 2: packaging = v[1]

    # e-labelling (opsional)
    e_label_public = e_label_nakes = None
    el = box.select_one(".e-labelling-public, .e-labelling, .e-labelling-general")
    if el:
        v = [x.get_text(strip=True) for x in el.select("div") if x.get_text(strip=True)]
        for i, t in enumerate(v):
            if t.lower() == "masyarakat" and i+1 < len(v):
                e_label_public = None if v[i+1] == "-" else v[i+1]
            if t.lower() == "nakes" and i+1 < len(v):
                e_label_nakes  = None if v[i+1] == "-" else v[i+1]

    published_by = directorate = None
    app = box.select_one(".application")
    if app:
        v = [x.get_text(strip=True) for x in app.select("div") if x.get_text(strip=True)]
        if "Diterbitkan Oleh" in v:
            i = v.index("Diterbitkan Oleh")
            if i+1 < len(v): published_by = v[i+1]
        if v: directorate = v[-1]

    return {
        "type_label": badge,
        "nie": reg, "name": name, "brand": brand,
        "published_at": published_at, "valid_until": valid_until,
        "composition": composition, "packaging": packaging, "dosage_form": dosage_form,
        "manufacturer": manufacturer, "manufacturer_city": manufacturer_city, "manufacturer_country": manufacturer_country,
        "e_label_public": e_label_public, "e_label_nakes": e_label_nakes,
        "published_by": published_by, "directorate": directorate,
    }
