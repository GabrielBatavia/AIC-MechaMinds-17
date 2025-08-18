# app/services/tools/fetch_tool.py
from __future__ import annotations
from typing import Dict, Any, List
import re
import httpx

try:
    # pip install trafilatura
    import trafilatura
except Exception:
    trafilatura = None  # type: ignore


def _sentences(txt: str) -> List[str]:
    # pembagi kalimat sederhana; cukup buat ekstraksi fakta ringkas
    parts = re.split(r'(?<=[\.\!\?])\s+', txt)
    return [p.strip() for p in parts if p and len(p.strip()) >= 8]


def _keyword_score(sent: str, terms: List[str]) -> int:
    s = sent.lower()
    return sum(1 for t in terms if t and t in s)


def _extract_facts(page_text: str, query: str, max_facts: int = 6) -> List[str]:
    if not page_text:
        return []
    # ambil kata kunci (buang kata terlalu pendek)
    terms = [w for w in re.split(r'[^a-z0-9]+', (query or "").lower()) if len(w) >= 3]
    sents = _sentences(page_text)
    scored = [(_keyword_score(s, terms), s) for s in sents]
    # ambil yang relevan (score>=1), panjang wajar
    scored = [(sc, s) for sc, s in scored if sc >= 1 and 20 <= len(s) <= 320]
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    facts = [s for _, s in scored[:max_facts]]
    # fallback: kalau kosong, ambil 2–3 kalimat pertama yang jelas
    if not facts:
        facts = [s for s in sents if 20 <= len(s) <= 220][:3]
    return facts


class FetchSummarizeTool:
    """
    Ambil halaman → ekstrak teks utama (trafilatura) → pilih kalimat paling relevan.
    Tidak bergantung LLM supaya hemat token.
    Return: {"facts": [string, ...]}
    """
    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    async def run(self, url: str, query: str) -> Dict[str, Any]:
        if not url:
            return {"facts": []}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={
                "User-Agent": "MedVerifyAI/1.0 (+https://github.com/yourorg/medverify)"
            }) as client:
                r = await client.get(url)
                r.raise_for_status()
                html = r.text
        except Exception:
            return {"facts": []}

        text = ""
        if trafilatura is not None:
            try:
                text = trafilatura.extract(html) or ""
            except Exception:
                text = ""
        else:
            # fallback sangat sederhana: buang tag HTML
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text)

        facts = _extract_facts(text, query)
        return {"facts": facts}
