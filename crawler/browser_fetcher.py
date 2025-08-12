# crawler/browser_fetcher.py
import asyncio, os
from typing import List, Tuple
from playwright.async_api import async_playwright

UA = os.getenv("SCRAPER_USER_AGENT", "MedVerifyAI/0.1 (+contact)")

async def fetch_rendered(url: str, wait_selector: str = "table", timeout_ms: int = 20000) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA)
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        # tunggu tabel/hasil muncul
        await page.wait_for_selector(wait_selector, timeout=timeout_ms)
        html = await page.content()
        await browser.close()
        return html

async def sniff_xhr(url: str, filter_kw: str = "produk") -> List[Tuple[str, str]]:
    """
    Buka halaman dan catat semua XHR/Fetch. Return [(url, body_json_or_text), ...]
    filter_kw: hanya kembalikan URL yang mengandung kata kunci.
    """
    records: List[Tuple[str, str]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA)
        page = await ctx.new_page()

        page.on("response", lambda resp: None)  # placeholder to attach if needed

        responses = []

        def _on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
                if "json" in ct or "javascript" in ct:
                    responses.append(resp)
            except Exception:
                pass

        page.on("response", _on_response)

        await page.goto(url, wait_until="networkidle")  # tunggu XHR settle

        for resp in responses:
            try:
                ru = resp.url
                if filter_kw.lower() in ru.lower():
                    try:
                        body = await resp.text()
                    except Exception:
                        body = ""
                    records.append((ru, body))
            except Exception:
                pass

        await browser.close()
    return records
