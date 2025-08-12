# crawler/jobs/search_terms.py
import asyncio, os, json, urllib.parse, traceback, time
from types import SimpleNamespace

from crawler.cekbpom_client import fetch, BASE
from crawler.cekbpom_parsers import parse_list_html, parse_detail_html, normalize_product
from crawler.ingest import save_raw, upsert_product
from crawler.cekbpom_json import search_dt
from crawler.cekbpom_detail import fetch_detail_modal, parse_detail_modal, map_type_code

import os

def env_flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


USE_RENDER        = env_flag("SCRAPER_RENDERED", False)
ENRICH_DETAIL     = env_flag("ENRICH_DETAIL", True)  # default ON
ENRICH_LIMIT      = int(os.getenv("ENRICH_LIMIT", "50"))
ENRICH_CONCURRENCY= int(os.getenv("ENRICH_CONCURRENCY", "6"))
ENRICH_TIMEOUT    = int(os.getenv("ENRICH_TIMEOUT", "25"))


async def crawl_detail(detail_url: str):
    try:
        r = await fetch(detail_url)
        raw_id = await save_raw(r.url, r)
        prod = parse_detail_html(r.text, str(r.url))
    except Exception:
        from crawler.browser_fetcher import fetch_rendered
        html = await fetch_rendered(detail_url, wait_selector="#table tbody tr, table tbody tr, body")
        fake = SimpleNamespace(status_code=200, text=html, headers={}, url=detail_url)
        raw_id = await save_raw(detail_url, fake)
        prod = parse_detail_html(html, str(detail_url))

    prod["raw_ref"] = raw_id
    await upsert_product(prod)
    return prod


async def enrich_by_click(term: str, nie: str | None) -> str | None:
    # Hanya dipakai jika PRODUCT_ID/TYPE_CODE tidak tersedia (harusnya jarang)
    from playwright.async_api import async_playwright
    q = urllib.parse.quote(nie or term or "")
    url = f"{BASE}/all-produk?query={q}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector("#table tbody tr", timeout=30000)
            pred = lambda r: ("/produk/" in r.url and "/detail" in r.url and "text/html" in (r.headers.get("content-type") or ""))
            try:
                row = page.locator("#table tbody tr").first
                async with page.expect_response(pred, timeout=30000) as resp_info:
                    await row.click()
                resp = await resp_info.value
                if resp and resp.ok:
                    return await resp.text()
            except Exception:
                await page.locator("#table tbody tr").first.click()
                await page.wait_for_selector("#modalDetail .modal-content, form#productDetail", timeout=30000)
                if await page.locator("#modalDetail .modal-content").count() > 0:
                    html = await page.locator("#modalDetail .modal-content").evaluate("el => el.outerHTML")
                else:
                    html = await page.locator("form#productDetail").evaluate("el => el.outerHTML")
                return html
        finally:
            await context.close()
            await browser.close()
    return None


async def _enrich_one(row, term, idx, total):
    pid = row.get("product_id")
    tcode = row.get("type_code") or map_type_code(row.get("type"))
    try:
        if pid and tcode:
            # panggil endpoint detail langsung (tanpa render)
            coro = fetch_detail_modal(product_id=pid, type_code=tcode, referer=f"{BASE}/all-produk?query={term}")
            html = await asyncio.wait_for(coro, timeout=ENRICH_TIMEOUT)
            fake_d = SimpleNamespace(status_code=200, text=html, headers={}, url=f"{BASE}/produk/{pid}/{tcode}/detail")
            d_raw_id = await save_raw(fake_d.url, fake_d)
            detail = parse_detail_modal(html)
            if not detail.get("nie"):
                detail["nie"] = row.get("nie")
            detail["raw_ref"] = d_raw_id
            enriched = normalize_product(detail, fake_d.url)
            if not enriched.get("type"):
                enriched["type"] = row.get("type")
            if not enriched.get("published_at"):
                enriched["published_at"] = row.get("published_at")
            await upsert_product(enriched)
        else:
            # fallback klik modal berbasis NIE (jarang kepakai)
            html = await enrich_by_click(term, row.get("nie"))
            if html:
                fake_d = SimpleNamespace(status_code=200, text=html, headers={}, url=f"{BASE}/all-produk?query={row.get('nie')}")
                d_raw_id = await save_raw(fake_d.url, fake_d)
                detail = parse_detail_modal(html)
                if not detail.get("nie"):
                    detail["nie"] = row.get("nie")
                detail["raw_ref"] = d_raw_id
                enriched = normalize_product(detail, fake_d.url)
                if not enriched.get("type"):
                    enriched["type"] = row.get("type")
                if not enriched.get("published_at"):
                    enriched["published_at"] = row.get("published_at")
                await upsert_product(enriched)
    except Exception as e:
        print(f"[detail {idx}/{total}] skip {row.get('nie')}: {e}", flush=True)


async def crawl_query(term: str, max_pages: int = 3):
    print(f"[crawl] term={term}", flush=True)
    seen = 0

    # 1) DataTables JSON (cepat)
    try:
        rows, raw = await search_dt(term, start=0, length=50)
        print(f"[{term}] rows from DT: {len(rows)}", flush=True)
        if rows:
            fake = SimpleNamespace(
                status_code=200,
                text=json.dumps(raw),
                headers={"content-type": "application/json"},
                url=f"{BASE}/produk-dt/all",
            )
            raw_id = await save_raw(fake.url, fake)

            # simpan list rows dulu (supaya cepat kelihatan di DB)
            for row in rows:
                prod = normalize_product(row, fake.url)
                prod["raw_ref"] = raw_id
                await upsert_product(prod)
            seen += len(rows)
            print(f"[{term}] saved list rows: {seen}", flush=True)

            # enrichment optional & paralel
            if ENRICH_DETAIL:
                todo = rows[:ENRICH_LIMIT]
                print(f"[{term}] enrich {len(todo)} items with concurrency={ENRICH_CONCURRENCY}", flush=True)
                sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

                async def worker(i, r):
                    async with sem:
                        await _enrich_one(r, term, i + 1, len(todo))
                        # progress ringkas
                        if (i + 1) % 5 == 0 or (i + 1) == len(todo):
                            print(f"[{term}] enriched {i+1}/{len(todo)}", flush=True)

                await asyncio.gather(*(worker(i, r) for i, r in enumerate(todo)))

            return seen
    except Exception as e:
        print("[JSON] fallback because:", e, flush=True)

    # 2) Fallback HTML list (jarang kepakai sekarang)
    path = "/all-produk"
    page_url = f"{path}?query={term}"
    for _ in range(max_pages):
        try:
            r = await fetch(page_url)
            raw_id = await save_raw(r.url, r)
            parsed = parse_list_html(r.text, str(r.url))
        except Exception:
            from crawler.browser_fetcher import fetch_rendered
            html = await fetch_rendered(BASE + page_url, wait_selector="#table tbody tr")
            fake = SimpleNamespace(status_code=200, text=html, headers={}, url=BASE + page_url)
            raw_id = await save_raw(fake.url, fake)
            parsed = parse_list_html(html, str(fake.url))

        if not parsed["rows"]:
            try:
                from crawler.browser_fetcher import sniff_xhr
                hits = await sniff_xhr(BASE + page_url, filter_kw="produk-dt")
                if hits:
                    print("[XHR] candidates:")
                    for u, body in hits[:3]:
                        print("  ", u, "len=", len(body), flush=True)
            except Exception as e:
                print("[XHR] sniff failed:", e, flush=True)

        for row in parsed["rows"]:
            if row.get("detail_url"):
                await crawl_detail(row["detail_url"])
            else:
                prod = normalize_product(
                    {"nie": row["nie"], "nama": row["name"], "pabrikan": row["pendaftar"]},
                    BASE + page_url,
                )
                prod["raw_ref"] = raw_id
                await upsert_product(prod)
            seen += 1

        if not parsed["next_url"]:
            break
        page_url = parsed["next_url"].replace(BASE, "")
    return seen


async def main():
    import sys
    terms = [t for t in sys.argv[1:] if not t.startswith("-")] or ["paracetamol"]
    print(f"[runner] terms={terms}", flush=True)
    total = 0
    for t in terms:
        try:
            print(f"[{t}] start crawl...", flush=True)
            got = await crawl_query(t, max_pages=5)
            print(f"[{t}] collected rows: {got}", flush=True)
            total += got
        except Exception:
            traceback.print_exc()
    print("TOTAL rows:", total, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
