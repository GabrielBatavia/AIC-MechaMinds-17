from __future__ import annotations
from typing import Dict, Any, List
from app.infra.search.router import RetrievalRouter

def normalize_text(s: str) -> str:
    return (s or "").strip()

class RetrieveCandidatesUseCase:
    def __init__(self, router: RetrievalRouter):
        self.router = router

    def run(self, query: str, k: int = 5) -> Dict[str, Any]:
        q = normalize_text(query)
        items = self.router.search(q, k=k)

        # bentuk blok ringkas untuk system prompt
        prompt_items = []
        for i, d in enumerate(items, 1):
            prompt_items.append(
                f"{i}) NAMA: {d.get('name','?')} — NIE: {d.get('nie','?')}\n"
                f"   SEDIAAN: {d.get('dosage_form','?')}; KOMPOSISI: {d.get('composition','?')}\n"
                f"   PABRIK: {d.get('manufacturer','?')}; KATEGORI: {d.get('category','?')}; STATUS: {d.get('status','?')}\n"
                f"   SCORE: {round(float(d.get('_score', 0.0)), 3)}\n"
            )
        system_block = (
            "[VERIF KANDIDAT]\n" + "".join(prompt_items) + 
            "\n[TUGAS AI]\n"
            "- Pilih kecocokan terbaik dengan input user.\n"
            "- Jelaskan alasan (nama/komposisi/dosis/pabrik).\n"
            "- Jika meragukan, minta konfirmasi user.\n"
        )
        return {"items": items, "system_prompt": system_block}
