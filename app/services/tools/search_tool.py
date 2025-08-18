# app/services/tools/search_tool.py
from __future__ import annotations
from typing import List, Dict, Any
import asyncio

try:
    # pip install duckduckgo_search>=6
    from duckduckgo_search import AsyncDDGS
except Exception:
    AsyncDDGS = None  # type: ignore


class WebSearchTool:
    """
    Web search ringan berbasis DuckDuckGo. Tidak butuh API key.
    Return: List[{title, url, snippet}]
    """
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    async def run(self, query: str, topk: int = 5) -> List[Dict[str, Any]]:
        if not query or not query.strip():
            return []
        if AsyncDDGS is None:
            # library belum terpasang → fail gracefully
            return []

        results: List[Dict[str, Any]] = []
        try:
            async with AsyncDDGS(timeout=self.timeout) as ddgs:
                async for r in ddgs.text(query, max_results=topk):
                    # r: {'title','href','body', ...}
                    results.append({
                        "title": r.get("title"),
                        "url": r.get("href") or r.get("url"),
                        "snippet": r.get("body"),
                    })
                    if len(results) >= topk:
                        break
        except asyncio.CancelledError:
            raise
        except Exception:
            # abaikan error jaringan
            return []
        return results
