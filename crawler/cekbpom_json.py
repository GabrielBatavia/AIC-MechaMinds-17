# crawler/cekbpom_json.py
import os, re, httpx, urllib.parse
from typing import Dict, Any, List, Tuple, Optional
from bs4 import BeautifulSoup

from crawler.cekbpom_detail import map_type_code  # <— untuk terjemahkan OB -> "05"

BASE = os.getenv("CEKBPOM_BASE", "https://cekbpom.pom.go.id")
UA   = os.getenv("SCRAPER_USER_AGENT", "MedVerifyAI/0.1 (+contact)")

COMMON_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/javascript, */*; q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}


def _textify(html: str) -> str:
    """Ambil text dari potongan HTML, ganti <br> -> newline."""
    soup = BeautifulSoup(html or "", "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return soup.get_text("\n", strip=True)


def _bold(html: str) -> str:
    """Ambil isi <span class='font-weight-bold'>...</span> jika ada."""
    soup = BeautifulSoup(html or "", "lxml")
    b = soup.select_one("span.font-weight-bold")
    return b.get_text(strip=True) if b else ""


def _pick(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _normalize_rows(dt_json: Dict[str, Any]) -> List[Dict[str, str]]:
    from bs4 import BeautifulSoup
    import re

    def textify(html: str) -> str:
        soup = BeautifulSoup(html or "", "lxml")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        return soup.get_text("\n", strip=True)

    def bold(html: str) -> str:
        soup = BeautifulSoup(html or "", "lxml")
        b = soup.select_one("span.font-weight-bold")
        return b.get_text(strip=True) if b else ""

    def pick(d, *keys):
        for k in keys:
            v = d.get(k)
            if v not in (None, ""):
                return v
        return None

    data = dt_json.get("data") or dt_json.get("rows") or []
    rows: List[Dict[str, str]] = []

    for row in data:
        # defaults
        tipe = ""
        type_code = None
        nie = name = ""
        published_at = None
        brand = None
        packaging = None
        manufacturer_name = ""
        manufacturer_city = None
        manufacturer_country = None
        product_id = None

        if isinstance(row, list):
            # format: [tipe, nomor_html, nama_html, pendaftar_html]
            tipe = (row[0] or "").strip() if len(row) > 0 else ""
            nomor_html = row[1] if len(row) > 1 else ""
            nama_html  = row[2] if len(row) > 2 else ""
            pend_html  = row[3] if len(row) > 3 else ""

            # type code dari badge tipe (OB/OT/OK/SK → 05/…)
            try:
                type_code = map_type_code(tipe)
            except Exception:
                type_code = None

            # NIE & Terbit
            nie = bold(nomor_html) or ""
            nomor_txt = textify(nomor_html)
            m_pub = re.search(r"Terbit:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", nomor_txt)
            published_at = m_pub.group(1) if m_pub else None

            # Nama + Merk + Kemasan
            name = bold(nama_html) or ""
            nama_txt = textify(nama_html)
            for line in nama_txt.splitlines()[1:]:
                low = line.lower()
                if low.startswith("merk"):
                    v = line.split(":", 1)[-1].strip()
                    brand = None if v == "-" else v
                elif low.startswith("kemasan"):
                    v = line.split(":", 1)[-1].strip()
                    packaging = v or None

            # Pendaftar + (negara) + kota
            pend_txt = textify(pend_html)
            pend_lines = [l for l in pend_txt.splitlines() if l]
            if pend_lines:
                parts = [s.strip() for s in pend_lines[0].split(" - ", 1)]
                manufacturer_name = parts[0] if parts else ""
                manufacturer_country = parts[1] if len(parts) > 1 else None
            if len(pend_lines) > 1:
                manufacturer_city = pend_lines[1].strip() or None

        elif isinstance(row, dict):
            # dict mode dari DataTables JSON (bisa berisi HTML kecil)
            tipe = (pick(row, "tipe", "type") or "").strip()

            nomor_raw = pick(row, "PRODUCT_REGISTER", "NIE", "REGISTER", "product_register") or ""
            nama_raw  = pick(row, "PRODUCT_NAME", "NAME", "product_name", "nama") or ""
            pend_raw  = pick(row, "MANUFACTURER_NAME", "PENDAFTAR", "manufacturer_name") or ""

            # NIE
            nie = bold(nomor_raw) or str(nomor_raw).strip()

            # published_at: dari teks "Terbit:" ATAU field tanggal JSON
            nomor_txt = textify(nomor_raw)
            m_pub = re.search(r"Terbit:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", nomor_txt)
            published_at = (
                m_pub.group(1) if m_pub else
                pick(row, "RELEASE_DATE", "PRODUCT_DATE", "SUBMIT_DATE", "published_at")
            )

            # Nama + (brand/packaging jika ada di blok nama) ATAU dari kolom JSON
            name = bold(nama_raw) or str(nama_raw).strip()
            nama_txt = textify(nama_raw)
            if "Kemasan:" in nama_txt or "Merk:" in nama_txt:
                for line in nama_txt.splitlines()[1:]:
                    low = line.lower()
                    if low.startswith("merk"):
                        v = line.split(":", 1)[-1].strip()
                        brand = None if v == "-" else v
                    elif low.startswith("kemasan"):
                        v = line.split(":", 1)[-1].strip()
                        packaging = v or None
            # fallback dari kolom JSON bila belum terisi
            if brand is None:
                brand = pick(row, "PRODUCT_BRAND", "product_brand", "brand")
            if packaging is None:
                packaging = pick(row, "PRODUCT_PACKAGE", "product_package", "packaging")

            # Pendaftar + kota/negara (bisa dari HTML kecil atau kolom terpisah)
            pend_txt = textify(pend_raw)
            pend_lines = [l for l in pend_txt.splitlines() if l]
            if pend_lines:
                parts = [s.strip() for s in pend_lines[0].split(" - ", 1)]
                manufacturer_name = parts[0] if parts else ""
                manufacturer_country = parts[1] if len(parts) > 1 else None
            if len(pend_lines) > 1:
                manufacturer_city = pend_lines[1].strip() or None

            # ambil dari kolom terpisah jika tersedia
            manufacturer_city = manufacturer_city or pick(row, "MANUFACTURER_CITY", "manufacturer_city")
            manufacturer_country = manufacturer_country or pick(row, "MANUFACTURER_COUNTRY", "manufacturer_country")

            # id & type code (kode numerik/teks yang dibutuhkan enrichment)
            product_id = pick(row, "PRODUCT_ID", "ID", "product_id")
            type_code  = pick(row, "PRODUCT_TYPE", "TYPE", "type_code")

        rows.append({
            "type": tipe,
            "type_code": type_code,  # <- penting untuk _enrich_one()
            "nie": nie,
            "name": name,
            "published_at": published_at,
            "brand": brand,
            "packaging": packaging,
            "manufacturer_name": manufacturer_name,
            "manufacturer_city": manufacturer_city,
            "manufacturer_country": manufacturer_country,
            "product_id": product_id,
        })

    return rows




async def _get_csrf(client: httpx.AsyncClient, term: str) -> Tuple[str, str]:
    """Fetch referer page, return (referer_url, csrf_token)."""
    referer = f"{BASE}/all-produk?query={urllib.parse.quote(term)}"
    r = await client.get(referer, headers={"User-Agent": UA, "Accept": "text/html"})
    r.raise_for_status()

    token = ""
    try:
        soup = BeautifulSoup(r.text, "lxml")
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        if meta and meta.get("content"):
            token = meta["content"].strip()
    except Exception:
        pass

    # cadangan via cookie
    if not token:
        token = client.cookies.get("XSRF-TOKEN") or client.cookies.get("csrf_token") or ""

    return referer, token


def _dt_payload(term: str, start: int, length: int) -> Dict[str, Any]:
    # Payload sesuai sniffing (boleh disesuaikan bila server berubah)
    p = {
        "draw": 1,

        "columns[0][data]": "PRODUCT_ID",
        "columns[0][name]": "",
        "columns[0][searchable]": "false",
        "columns[0][orderable]": "false",
        "columns[0][search][value]": "",
        "columns[0][search][regex]": "false",

        "columns[1][data]": "PRODUCT_REGISTER",
        "columns[1][name]": "",
        "columns[1][searchable]": "false",
        "columns[1][orderable]": "false",
        "columns[1][search][value]": "",
        "columns[1][search][regex]": "false",

        "columns[2][data]": "PRODUCT_NAME",
        "columns[2][name]": "",
        "columns[2][searchable]": "false",
        "columns[2][orderable]": "false",
        "columns[2][search][value]": "",
        "columns[2][search][regex]": "false",

        "columns[3][data]": "MANUFACTURER_NAME",
        "columns[3][name]": "",
        "columns[3][searchable]": "false",
        "columns[3][orderable]": "false",
        "columns[3][search][value]": "",
        "columns[3][search][regex]": "false",

        "order[0][column]": "0",
        "order[0][dir]": "asc",
        "start": str(start),
        "length": str(length),

        "search[value]": "",
        "search[regex]": "false",

        # filter fields (kosong sesuai sniff)
        "product_register": "",
        "product_name": "",
        "product_brand": "",
        "product_package": "",
        "product_form": "",
        "ingredients": "",
        "submit_date": "",
        "product_date": "",
        "expire_date": "",
        "manufacturer_name": "",
        "status": "",
        "release_date": "",

        # penting: query term
        "query": term,
        "manufacturer": "",
        "registrar": "",
    }
    return p


async def search_dt(term: str, start: int = 0, length: int = 10) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Query endpoint DataTables dan kembalikan (rows_normalized, raw_json).
    """
    url = f"{BASE}/produk-dt/all"
    async with httpx.AsyncClient(headers=COMMON_HEADERS, timeout=30, follow_redirects=True) as c:
        referer, token = await _get_csrf(c, term)

        headers = {**COMMON_HEADERS, "Referer": referer, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if token:
            headers["x-csrf-token"] = token
            headers["X-CSRF-TOKEN"] = token

        payload = _dt_payload(term, start=start, length=length)
        r = await c.post(url, data=payload, headers=headers)
        r.raise_for_status()
        dt = r.json()
        return _normalize_rows(dt), dt



_DT_CACHE: dict[str, str] = {}  # referer_url -> dt_endpoint

async def _get_csrf_for_referer(client: httpx.AsyncClient, referer_url: str) -> Tuple[str, str]:
    r = await client.get(referer_url, headers={"User-Agent": UA, "Accept": "text/html"})
    r.raise_for_status()
    token = ""
    try:
        soup = BeautifulSoup(r.text, "lxml")
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        if meta and meta.get("content"):
            token = meta["content"].strip()
    except Exception:
        pass
    if not token:
        token = client.cookies.get("XSRF-TOKEN") or client.cookies.get("csrf_token") or ""
    return referer_url, token

async def _discover_dt_endpoint(referer_url: str) -> Optional[str]:
    # pakai Playwright sniff yang sudah ada
    try:
        from crawler.browser_fetcher import sniff_xhr
        hits = await sniff_xhr(referer_url, filter_kw="produk-dt")
        # ambil kandidat pertama yang terlihat seperti endpoint DT
        for u, _body in hits:
            if "produk-dt" in u:
                return u
    except Exception:
        return None
    return None

def _dt_payload_category(start: int, length: int) -> Dict[str, Any]:
    # payload minimal DataTables (tanpa "query")
    return {
        "draw": 1,
        "columns[0][data]": "PRODUCT_ID",
        "columns[0][name]": "",
        "columns[0][searchable]": "false",
        "columns[0][orderable]": "false",
        "columns[0][search][value]": "",
        "columns[0][search][regex]": "false",

        "columns[1][data]": "PRODUCT_REGISTER",
        "columns[1][name]": "",
        "columns[1][searchable]": "false",
        "columns[1][orderable]": "false",
        "columns[1][search][value]": "",
        "columns[1][search][regex]": "false",

        "columns[2][data]": "PRODUCT_NAME",
        "columns[2][name]": "",
        "columns[2][searchable]": "false",
        "columns[2][orderable]": "false",
        "columns[2][search][value]": "",
        "columns[2][search][regex]": "false",

        "columns[3][data]": "MANUFACTURER_NAME",
        "columns[3][name]": "",
        "columns[3][searchable]": "false",
        "columns[3][orderable]": "false",
        "columns[3][search][value]": "",
        "columns[3][search][regex]": "false",

        "order[0][column]": "0",
        "order[0][dir]": "asc",
        "start": str(start),
        "length": str(length),

        "search[value]": "",
        "search[regex]": "false",
    }

async def search_dt_category(referer_path: str, start: int = 0, length: int = 100) -> Tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    """
    Ambil satu halaman DataTables untuk sebuah halaman kategori.
    Param:
      - referer_path: path absolut/relatif, contoh: '/produk-obat'
    Return:
      (rows_normalized, raw_json, dt_url_yang_dipakai)
    """
    # bangun referer absolute
    referer_url = referer_path if referer_path.startswith("http") else (BASE + referer_path)

    # cache endpoint per-referer
    dt_url = _DT_CACHE.get(referer_url)

    async with httpx.AsyncClient(headers=COMMON_HEADERS, timeout=30, follow_redirects=True) as c:
        _, token = await _get_csrf_for_referer(c, referer_url)

        # temukan endpoint kalau belum ada
        if not dt_url:
            dt_url = await _discover_dt_endpoint(referer_url)
            if not dt_url:
                # fallback konservatif ke /produk-dt/all (beberapa deployment pakai satu endpoint untuk banyak halaman)
                dt_url = f"{BASE}/produk-dt/all"
            _DT_CACHE[referer_url] = dt_url

        headers = {**COMMON_HEADERS, "Referer": referer_url, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if token:
            headers["x-csrf-token"] = token
            headers["X-CSRF-TOKEN"] = token

        payload = _dt_payload_category(start=start, length=length)
        r = await c.post(dt_url, data=payload, headers=headers)
        r.raise_for_status()

        dt = r.json()
        from .cekbpom_json import _normalize_rows as _norm  # reuse normalizer yang sudah ada
        rows = _norm(dt)  # normalisasi kolom jadi seragam
        return rows, dt, dt_url