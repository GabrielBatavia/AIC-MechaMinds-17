import asyncio, os, json, argparse, time
from types import SimpleNamespace
from typing import List, Dict, Any, Tuple

from crawler.cekbpom_json import search_dt
from crawler.cekbpom_parsers import normalize_product
from crawler.ingest import save_raw, upsert_product
from crawler.cekbpom_detail import fetch_detail_modal, parse_detail_modal, map_type_code
from crawler.cekbpom_client import BASE

# ─── Env flags ────────────────────────────────────────────────────────────
def env_flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")

ENRICH_DETAIL       = env_flag("ENRICH_DETAIL", True)
ENRICH_TIMEOUT      = int(os.getenv("ENRICH_TIMEOUT", "25"))
ENRICH_CONCURRENCY  = int(os.getenv("ENRICH_CONCURRENCY", "8"))
PAGE_SIZE           = int(os.getenv("PAGE_SIZE", "100"))
SEED_MODE           = os.getenv("SEEDS", "az09")  # az09 = a-z dan 0-9
SLEEP_BETWEEN_PAGES = float(os.getenv("SLEEP_BETWEEN_PAGES", "0.2"))

# ─── Helpers ──────────────────────────────────────────────────────────────
def make_seeds(mode: str) -> List[str]:
    mode = (mode or "az09").lower()
    seeds: List[str] = []
    if "az" in mode:
        seeds += [chr(c) for c in range(ord("a"), ord("z")+1)]
    if "09" in mode:
        seeds += [str(d) for d in range(0, 10)]
    # kamu bisa tambah bigram untuk coverage ketat:
    # if "bi" in mode: seeds += [a+b for a in "abcdefghijklmnopqrstuvwxyz" for b in "abcdefghijklmnopqrstuvwxyz"]
    return seeds

async def _enrich_one(row: Dict[str, Any], term: str, idx: int, total: int):
    """Ambil detail modal cepat via /produk/{PRODUCT_ID}/{TYPE_CODE}/detail."""
    from types import SimpleNamespace
    pid   = row.get("product_id")
    tcode = row.get("type_code") or map_type_code(row.get("type"))

    try:
        if not (pid and tcode):
            return  # tanpa id/kode, lewati (jarang terjadi kalau dari DT JSON)

        coro = fetch_detail_modal(product_id=pid, type_code=tcode, referer=f"{BASE}/all-produk?query={term}")
        html = await asyncio.wait_for(coro, timeout=ENRICH_TIMEOUT)

        fake_d = SimpleNamespace(status_code=200, text=html, headers={}, url=f"{BASE}/produk/{pid}/{tcode}/detail")
        d_raw_id = await save_raw(fake_d.url, fake_d)

        detail = parse_detail_modal(html)
        if not detail.get("nie"):
            detail["nie"] = row.get("nie")
        detail["raw_ref"] = d_raw_id

        enriched = normalize_product(detail, fake_d.url)
        # bawa beberapa kolom dari list bila kosong
        if not enriched.get("type"):          enriched["type"]          = row.get("type")
        if not enriched.get("published_at"):  enriched["published_at"]  = row.get("published_at")
        if not enriched.get("brand"):         enriched["brand"]         = row.get("brand")
        if not enriched.get("packaging"):     enriched["packaging"]     = row.get("packaging")
        if not enriched.get("manufacturer"):  enriched["manufacturer"]  = row.get("manufacturer_name")
        if not enriched.get("manufacturer_city"):     enriched["manufacturer_city"]    = row.get("manufacturer_city")
        if not enriched.get("manufacturer_country"):  enriched["manufacturer_country"] = row.get("manufacturer_country")

        await upsert_product(enriched)

        # progress tipis
        if (idx + 1) % 25 == 0 or (idx + 1) == total:
            print(f"[enrich] {term}: {idx+1}/{total}", flush=True)

    except asyncio.TimeoutError:
        print(f"[enrich] timeout {idx+1}/{total} NIE={row.get('nie')}", flush=True)
    except Exception as e:
        print(f"[enrich] skip {idx+1}/{total} NIE={row.get('nie')}: {e}", flush=True)

async def harvest_term(term: str, page_size: int, do_enrich: bool, enrich_conc: int):
    """
    Paging DataTables untuk satu term:
    - Simpan list rows (normalized)
    - Enrich paralel (opsional)
    """
    start = 0
    total_records = None
    collected = 0

    print(f"[{term}] begin paging with size={page_size}", flush=True)

    while True:
        rows, raw = await search_dt(term, start=start, length=page_size)

        # simpan raw snapshot (sekali per halaman)
        fake = SimpleNamespace(
            status_code=200,
            text=json.dumps(raw),
            headers={"content-type": "application/json"},
            url=f"{BASE}/produk-dt/all?query={term}&start={start}&length={page_size}",
        )
        raw_id = await save_raw(fake.url, fake)

        # upsert list rows cepat
        for r in rows:
            prod = normalize_product(r, fake.url)
            prod["raw_ref"] = raw_id
            await upsert_product(prod)
        collected += len(rows)

        # hitung total dari payload DT
        if total_records is None:
            total_records = int(raw.get("recordsFiltered") or raw.get("recordsTotal") or 0)
            if total_records == 0 and len(rows) == 0:
                print(f"[{term}] no results", flush=True)
                break

        print(f"[{term}] page start={start} got={len(rows)} / total≈{total_records}", flush=True)

        # enrichment paralel untuk halaman ini
        if do_enrich and rows:
            sem = asyncio.Semaphore(enrich_conc)
            async def worker(i, r):
                async with sem:
                    await _enrich_one(r, term, i, len(rows))
            await asyncio.gather(*(worker(i, r) for i, r in enumerate(rows)))

        # selesai jika terakhir
        start += page_size
        if start >= total_records:
            break

        # be nice ke server
        if SLEEP_BETWEEN_PAGES > 0:
            await asyncio.sleep(SLEEP_BETWEEN_PAGES)

    print(f"[{term}] done, collected={collected}", flush=True)
    return collected

async def main():
    parser = argparse.ArgumentParser(description="Mass crawl cekbpom obat via seed queries")
    parser.add_argument("--seeds", type=str, default=SEED_MODE,
                        help="Seed mode: 'az09' (default), 'az', '09', or custom comma list like 'para,acet,ibup,amox'")
    parser.add_argument("--pagesize", type=int, default=PAGE_SIZE, help="DataTables page size (50–200 is typical)")
    parser.add_argument("--enrich", type=int, default=1 if ENRICH_DETAIL else 0, help="1 to enrich via modal, 0 to skip")
    parser.add_argument("--enrich-conc", type=int, default=ENRICH_CONCURRENCY, help="Enrichment concurrency")
    args = parser.parse_args()

    # buat daftar seed
    if "," in args.seeds:
        seeds = [s.strip() for s in args.seeds.split(",") if s.strip()]
    else:
        seeds = make_seeds(args.seeds)

    print(f"[runner] seeds={seeds}", flush=True)

    total = 0
    for s in seeds:
        try:
            got = await harvest_term(
                term=s,
                page_size=args.pagesize,
                do_enrich=bool(args.enrich),
                enrich_conc=args.enrich_conc,
            )
            total += got
        except Exception as e:
            print(f"[runner] seed '{s}' failed: {e}", flush=True)

    print(f"TOTAL rows (list-upsert, may include duplicates by seed but dedup by NIE in DB): {total}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
