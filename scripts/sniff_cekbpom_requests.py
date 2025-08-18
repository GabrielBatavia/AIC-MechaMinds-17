# scripts/sniff_cekbpom_requests.py
import asyncio
from playwright.async_api import async_playwright

URL = "https://cekbpom.pom.go.id/all-produk?query=paracetamol"

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context()
        page = await ctx.new_page()

        def on_request(req):
            if "produk-dt/all" in req.url:
                print("REQ:", req.method, req.url)
                print("HEADERS:", req.headers)
                print("POSTDATA:", req.post_data)

        def on_response(resp):
            if "produk-dt/all" in resp.url:
                print("RESP:", resp.status, resp.url, "CT=", resp.headers.get("content-type"))
        page.on("request", on_request)
        page.on("response", on_response)

        await page.goto(URL, wait_until="networkidle")
        await b.close()

if __name__ == "__main__":
    asyncio.run(main())
