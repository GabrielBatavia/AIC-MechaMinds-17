# crawler/cekbpom_parsers.py
from bs4 import BeautifulSoup
import hashlib, datetime as dt
from urllib.parse import urljoin

def _now():
    return dt.datetime.utcnow().isoformat() + "Z"

def normalize_product(d: dict, url: str):
    # --- hash fallback untuk dokumen tanpa NIE ---
    try:
        blob = (url + "|" + str(sorted(d.items()))).encode("utf-8")
    except Exception:
        blob = (url + "|" + repr(d)).encode("utf-8")
    h = "sha256:" + hashlib.sha256(blob).hexdigest()

    nie   = (d.get("nie") or d.get("nomor") or d.get("registrasi") or "").strip()
    name  = (d.get("name") or d.get("nama") or "").strip()
    mfr   = (d.get("manufacturer") or d.get("manufacturer_name") or d.get("pabrikan") or d.get("pendaftar") or "").strip()
    status= (d.get("status") or "").strip().lower() or "unknown"

    return {
        "_id": nie or h,                     # <— sekarang h terdefinisi
        "nie": nie,
        "type": d.get("type") or d.get("type_label") or d.get("tipe"),
        "name": name,
        "brand": d.get("brand"),
        "packaging": d.get("packaging"),
        "manufacturer": mfr,
        "manufacturer_city": d.get("manufacturer_city"),
        "manufacturer_country": d.get("manufacturer_country"),
        "published_at": d.get("published_at"),
        "valid_until": d.get("valid_until"),
        "composition": d.get("composition"),
        "dosage_form": d.get("dosage_form"),
        "e_label_public": d.get("e_label_public"),
        "e_label_nakes": d.get("e_label_nakes"),
        "published_by": d.get("published_by"),
        "directorate": d.get("directorate"),
        "status": status,
        "source_url": url,
        "first_seen": _now(),
        "last_seen": _now(),
        "content_hash": h,
        "raw_ref": None,
    }



def parse_list_html(html: str, base_url: str):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    # DataTables sering punya 2 table (header clone + body). Kita ambil table utama dengan id="table"
    table = soup.select_one("table#table") or soup.find("table")
    if not table:
        return {"rows": [], "next_url": None}

    rows = []
    for tr in table.select("tbody tr"):
        tds = tr.select("td")
        if len(tds) < 4:
            continue

        # Tipe
        tipe = (tds[0].get_text(strip=True) if tds[0] else "").strip()

        # Kolom 2: NIE + Terbit
        col2_html = tds[1]
        nie_el = col2_html.select_one("span.font-weight-bold")
        nie = (nie_el.get_text(strip=True) if nie_el else "").strip()
        col2_txt = col2_html.get_text("\n", strip=True)
        m_pub = re.search(r"Terbit:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", col2_txt)
        published_at = m_pub.group(1) if m_pub else None

        # Kolom 3: Nama + Merk + Kemasan
        col3_html = tds[2]
        name_el = col3_html.select_one("span.font-weight-bold")
        name = (name_el.get_text(strip=True) if name_el else "").strip()
        col3_lines = [l.strip() for l in col3_html.get_text("\n", strip=True).splitlines()]
        brand = packaging = None
        for line in col3_lines[1:]:
            low = line.lower()
            if low.startswith("merk"):
                v = line.split(":", 1)[-1].strip()
                brand = None if v == "-" else v
            elif low.startswith("kemasan"):
                packaging = line.split(":", 1)[-1].strip() or None

        # Kolom 4: Pendaftar + kota
        col4_html = tds[3]
        # baris 1: "TRIFA RAYA LABORATORIES - Indonesia"
        # baris 2: "KOTA BANDUNG"
        col4_lines = [l.strip() for l in col4_html.get_text("\n", strip=True).splitlines() if l.strip()]
        manufacturer_name = manufacturer_country = manufacturer_city = None
        if col4_lines:
            parts = [p.strip() for p in col4_lines[0].split(" - ", 1)]
            manufacturer_name = parts[0] if parts else ""
            if len(parts) > 1:
                manufacturer_country = parts[1] or None
        if len(col4_lines) > 1:
            manufacturer_city = col4_lines[1] or None

        rows.append({
            "tipe": tipe,
            "type_code": map_type_code(tipe),  # supaya enrichement bisa langsung pakai
            "nie": nie,
            "name": name,
            "brand": brand,
            "packaging": packaging,
            "published_at": published_at,
            "manufacturer_name": manufacturer_name,
            "manufacturer_country": manufacturer_country,
            "manufacturer_city": manufacturer_city,
            "detail_url": None,
        })


    # pagination di DataTables pakai JS; abaikan untuk HTML-mode
    return {"rows": rows, "next_url": None}


def parse_detail_html(html: str, url: str):
    """
    Parse halaman detail produk: ambil field kunci (NIE, nama, pendaftar/pabrik, status).
    Selector disiapkan generik; sesuaikan setelah lihat DOM detail.
    """
    soup = BeautifulSoup(html, "lxml")
    def get_val(label_keywords):
        th = soup.find("th", string=lambda s: s and any(k.lower() in s.lower() for k in label_keywords))
        if not th: return ""
        td = th.find_next("td")
        return td.get_text(strip=True) if td else ""

    nie   = get_val(["Nomor Registrasi", "NIE", "No. Registrasi"])
    name  = get_val(["Nama Produk", "Nama Dagang"])
    mfr   = get_val(["Pendaftar", "Pabrikan", "Produsen"])
    stat  = get_val(["Status", "Berlaku", "Keaktifan"])
    return normalize_product({"nie": nie, "nama": name, "pendaftar": mfr, "status": stat}, url)
