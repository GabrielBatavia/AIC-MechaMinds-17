# scripts/debug_dt_sample.py
import asyncio, json
from crawler.cekbpom_json import search_dt

async def main():
    rows, raw = await search_dt("paracetamol", start=0, length=5)
    print("RAW keys:", list(raw.keys()))
    print("ROW[0]:", json.dumps(rows[0], indent=2, ensure_ascii=False))
    assert "brand" in rows[0], "brand tidak ada di row"
    assert "packaging" in rows[0], "packaging tidak ada di row"
    assert "published_at" in rows[0], "published_at tidak ada di row"

asyncio.run(main())
