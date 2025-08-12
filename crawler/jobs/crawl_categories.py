import asyncio, os, json, time
from types import SimpleNamespace
from typing import Dict, Any, List, Tuple

from crawler.cekbpom_client import BASE
from crawler.cekbpom_json import search_dt_category
from crawler.cekbpom_parsers import normalize_product
from crawler.cekbpom_detail import fetch_detail_modal, parse_detail_modal, map_type_code
from crawler.ingest import save_raw, upsert_product

def env_flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")

PAGE_SIZE           = int(os.getenv("PAGE_SIZE", "120"))
ENRICH_DETAIL       = env_flag("ENRICH_DETAIL", True)
ENRICH_CONCURRENCY  = int(os.getenv("ENRICH_CONCURRENCY", "8"))
ENRICH_TIMEOUT      = int(os.getenv("ENRICH_TIMEOUT", "25"))
SLEEP_BETWEEN_PAGES = float(os.getenv("SLEEP_BETWEEN_PAGES", "0.2"))
EMPTY_PAGE_CUTOFF   = int(os.getenv("EMPTY_PAGE_CUTOFF", "3"))  # stop kalau N halaman kosong berturut-turut

CATEGORIES = [
    ("/produk-obat",               "obat"),
    ("/produk-obat-tradisional",   "obat-tradisional"),
    ("/produk-obat-kuasi",         "obat-kuasi"),
    ("/produk-suplemen-kesehatan", "suplemen-kesehatan"),
    ("/produk-kosmetika",          "kosmetika"),
    ("/produk-pangan-olahan",      "pangan-olahan"),
]

async def _enrich_one(row: Dict[str, Any], referer_url: str, idx: int, total: int, category: str):
    pid   = row.get("product_id")
    tcode = row.get("type_code") or map_type_code(row.get("type"))
    if not (pid and tcode):
        return
    try:
        html = await asyncio.wait_for(
            fetch_detail_modal(product_id=pid, type_code=tcode, referer=referer_url),
            timeout=ENRICH_TIMEOUT
        )
        fake_d = SimpleNamespace(status_code=200, text=html, headers={}, url=f"{BASE}/produk/{pid}/{tcode}/detail")
        d_raw_id = await save_raw(fake_d.url, fake_d)

        detail = parse_detail_modal(html)
        if not detail.get("nie"):
            detail["nie"] = row.get("nie")
        detail["raw_ref"] = d_raw_id

        enriched = normalize_product(detail, fake_d.url)
        # bawa field list bila kosong
        if not enriched.get("type"):          enriched["type"]          = row.get("type")
        if not enriched.get("published_at"):  enriched["published_at"]  = row.get("published_at")
        if not enriched.get("brand"):         enriched["brand"]         = row.get("brand")
        if not enriched.get("packaging"):     enriched["packaging"]     = row.get("packaging")
        if not enriched.get("manufacturer"):  enriched["manufacturer"]  = row.get("manufacturer_name")
        if not enriched.get("manufacturer_city"):     enriched["manufacturer_city"]    = row.get("manufacturer_city")
        if not enriched.get("manufacturer_country"):  enriched["manufacturer_country"] = row.get("manufacturer_country")

        # tambahkan kategori
        enriched["category"] = category

        await upsert_product(enriched)

        if (idx + 1) % 25 == 0 or (idx + 1) == total:
            print(f"[enrich] {category}: {idx+1}/{total}", flush=True)
    except Exception as e:
        print(f"[enrich] {category} skip {idx+1}/{total} NIE={row.get('nie')}: {e}", flush=True)

async def harvest_category(path: str, category: str, page_size: int, do_enrich: bool):
    print(f"[{category}] begin paging size={page_size}", flush=True)
    start = 0
    total_records = None
    collected = 0
    consecutive_empty = 0
    referer_url = BASE + path

    while True:
        rows, raw, dt_url = await search_dt_category(path, start=start, length=page_size)

        # simpan snapshot raw
        fake = SimpleNamespace(
            status_code=200,
            text=json.dumps(raw),
            headers={"content-type": "application/json"},
            url=f"{dt_url}?start={start}&length={page_size}"
        )
        raw_id = await save_raw(fake.url, fake)

        # tag kategori ke setiap row sebelum upsert
        if rows:
            for r in rows:
                r["_source_category"] = category

        # upsert list rows (cepat)
        for r in rows:
            prod = normalize_product(r, fake.url)
            prod["raw_ref"] = raw_id
            prod["category"] = category  # simpan kategori
            await upsert_product(prod)
        collected += len(rows)

        # total dari server (bisa 0/aneh; pakai guard empty pages)
        if total_records is None:
            total_records = int(raw.get("recordsFiltered") or raw.get("recordsTotal") or 0)
        print(f"[{category}] page start={start} got={len(rows)} / total≈{total_records}", flush=True)

        # enrichment per halaman
        if do_enrich and rows:
            sem = asyncio.Semaphore(ENRICH_CONCURRENCY)
            async def worker(i, r):
                async with sem:
                    await _enrich_one(r, referer_url, i, len(rows), category)
            await asyncio.gather(*(worker(i, r) for i, r in enumerate(rows)))

        # heuristic stop: kalau halaman kosong berturut-turut, berhenti
        if len(rows) == 0:
            consecutive_empty += 1
        else:
            consecutive_empty = 0
        if consecutive_empty >= EMPTY_PAGE_CUTOFF:
            print(f"[{category}] stop after {EMPTY_PAGE_CUTOFF} empty pages in a row.", flush=True)
            break

        # selesai jika mencapai total yang wajar
        start += page_size
        if total_records and start >= total_records:
            # beberapa deployment kirim total yang valid – kita hormati
            break

        if SLEEP_BETWEEN_PAGES > 0:
            await asyncio.sleep(SLEEP_BETWEEN_PAGES)

    print(f"[{category}] done, collected={collected}", flush=True)
    return collected

async def main():
    total = 0
    for path, cat in CATEGORIES:
        try:
            got = await harvest_category(path, cat, PAGE_SIZE, ENRICH_DETAIL)
            total += got
        except Exception as e:
            print(f"[runner] {cat} failed: {e}", flush=True)
    print(f"TOTAL rows inserted/updated (list): {total}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
