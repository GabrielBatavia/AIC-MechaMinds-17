# scripts/sniff_click_detail.py
import asyncio
from playwright.async_api import async_playwright

URL = "https://cekbpom.pom.go.id/all-produk?query=paracetamol"

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context()
        page = await ctx.new_page()

        def on_request(req):
            if "produk" in req.url and "produk-dt/all" not in req.url:
                print("REQ:", req.method, req.url)
                if req.post_data:
                    print("POSTDATA:", req.post_data)

        def on_response(resp):
            if "produk" in resp.url and "produk-dt/all" not in resp.url:
                print("RESP:", resp.status, resp.url, "CT=", resp.headers.get("content-type"))

        page.on("request", on_request)
        page.on("response", on_response)

        await page.goto(URL, wait_until="networkidle")
        # klik baris pertama tabel
        await page.click("#table tbody tr >> nth=0")
        # beri waktu sedikit untuk XHR
        await page.wait_for_timeout(1500)
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
