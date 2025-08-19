# app/services/prompt_service.py
import os, yaml
from pathlib import Path
from types import SimpleNamespace
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

from app.services.medical_classifier import (
    VERIFY_BPOM, WHAT_IS, COMPOSITION, DOSAGE, USAGE, INTERACTIONS, CONTRAINDICATIONS,
    SIDE_EFFECTS, PREGNANCY, STORAGE, WARNINGS, COMPARE, PRICE_AVAILABILITY,
    CHEMICAL_QUERY, GENERAL_DRUG_INFO
)


PROMPT_DIR = Path(os.getenv("PROMPT_DIR", "config/prompts"))

def _ctxdict(ctx: Any) -> Dict[str, Any]:
    """Pastikan konteks selalu dict (hindari 'str has no attribute get')."""
    return ctx if isinstance(ctx, dict) else {}

@dataclass
class QueryBundle:
    search_query: List[str]
    fact_query: List[str]

class PromptService:
    def __init__(self):
        self.base_system = (PROMPT_DIR / "base_system.md").read_text(encoding="utf-8")
        self.intents = yaml.safe_load((PROMPT_DIR / "intents.yaml").read_text(encoding="utf-8"))

    def system_prompt(self) -> str:
        return (
            "Kamu MedVerify-Agent. Bahasa Indonesia. Jawab ringkas, akurat, dan aman. "
            "Fokus pada informasi obat/produk kesehatan: validitas BPOM, komposisi, dosis, cara pakai, "
            "interaksi, kontraindikasi, efek samping, kehamilan/menyusui, penyimpanan, peringatan, "
            "perbandingan produk, dan info umum obat. Jika perlu rujukan, utamakan sumber resmi (BPOM/pom.go.id) "
            "atau literatur tepercaya. Jika pertanyaan kurang spesifik, klarifikasi singkat lalu jawab semampu konteks."
            "Gunakan history percakapan untuk memahami konteks dan buat alur percakapan yang alami"
        )

    # ==== Task prompt per label (fallback ke general_drug_info) ====
    def task_prompt(self, label: str, *, user_text: str, product_or_nie: Optional[str]) -> str:
        base = f"Pertanyaan pengguna: {user_text}\n"
        ctx = f"Konteks produk/NIE (jika ada): {product_or_nie or '-'}\n"
        guide = ""

        if label == VERIFY_BPOM:
            guide = (
                "Tugas: Periksa validitas/pendaftaran di BPOM. Jelaskan singkat status dan beri rujukan bila ada."
            )
        elif label == WHAT_IS:
            guide = "Tugas: Jelaskan ringkas apa produk/obat ini dan kegunaan utamanya."
        elif label == COMPOSITION:
            guide = "Tugas: Uraikan komposisi/kandungan (bahan aktif & non-aktif jika relevan)."
        elif label == DOSAGE:
            guide = "Tugas: Berikan dosis/aturan pakai standar. Ingatkan konsultasi tenaga kesehatan."
        elif label == USAGE:
            guide = "Tugas: Jelaskan cara pakai/indikasi penggunaan."
        elif label == INTERACTIONS:
            guide = "Tugas: Ringkas interaksi penting dengan obat/makanan/alkohol."
        elif label == CONTRAINDICATIONS:
            guide = "Tugas: Sebutkan kontraindikasi & kondisi yang harus dihindari."
        elif label == SIDE_EFFECTS:
            guide = "Tugas: Daftar efek samping umum dan yang serius (peringatan)."
        elif label == PREGNANCY:
            guide = "Tugas: Bahas keamanan pada kehamilan & menyusui secara ringkas."
        elif label == STORAGE:
            guide = "Tugas: Anjurkan penyimpanan/stabilitas/kedaluwarsa."
        elif label == WARNINGS:
            guide = "Tugas: Sampaikan peringatan & kehati-hatian penting."
        elif label == COMPARE:
            guide = "Tugas: Bandingkan produk terkait secara faktual dan netral."
        elif label == PRICE_AVAILABILITY:
            guide = "Tugas: Jelaskan secara umum mengenai ketersediaan. Hindari spekulasi harga jika tak ada sumber."
        elif label == CHEMICAL_QUERY:
            guide = "Tugas: Jawab aspek kimia senyawa terkait (nama generik/struktur/kelas)."
        else:
            label = GENERAL_DRUG_INFO
            guide = "Tugas: Berikan informasi obat/produk secara umum dan aman."

        postfix = (
            "\nFormat: jawaban ≤120 kata bila memungkinkan. Tambahkan sumber jika mengutip web. "
            "Jangan menambahkan klaim tanpa rujukan. Jika data tidak pasti, katakan tidak tersedia."
        )
        return base + ctx + guide + postfix

    # ==== Query builder utk web search model ====
    def build_queries(self, label: str, ctx: Dict[str, Any]) -> QueryBundle:
        canon = ((ctx.get("verification") or {}).get("canon") or {})
        name = canon.get("name")
        nie  = canon.get("nie")
        user_text = (ctx.get("user_text") or "").strip()

        q: List[str] = []
        facts: List[str] = []

        # helper to push queries
        def add(*items):
            for it in items:
                if it and it not in q:
                    q.append(it)

        # Verify BPOM
        if label == VERIFY_BPOM:
            add(
                f"site:pom.go.id {nie or ''} {name or ''} izin edar",
                f"site:cekbpom.pom.go.id {nie or ''} {name or ''}",
                f"{name or user_text} BPOM nomor izin edar"
            )
            facts.append("Cari status pendaftaran di situs resmi BPOM (cekbpom.pom.go.id).")

        # What is / General info
        if label in (WHAT_IS, GENERAL_DRUG_INFO):
            add(
                f"{name or user_text} apa itu obat",
                f"{name or user_text} indication use",
                f"{name or user_text} monograph"
            )

        if label == COMPOSITION:
            add(
                f"{name or user_text} composition",
                f"{name or user_text} kandungan",
                f"{name or user_text} ingredients"
            )

        if label == DOSAGE:
            add(
                f"{name or user_text} dosage adult",
                f"{name or user_text} aturan pakai"
            )

        if label == USAGE:
            add(
                f"{name or user_text} indications",
                f"{name or user_text} how to use"
            )

        if label == INTERACTIONS:
            add(
                f"{name or user_text} drug interactions",
                f"{name or user_text} interaction alcohol food"
            )

        if label == CONTRAINDICATIONS:
            add(f"{name or user_text} contraindications")

        if label == SIDE_EFFECTS:
            add(f"{name or user_text} side effects", f"{name or user_text} adverse effects")

        if label == PREGNANCY:
            add(f"{name or user_text} pregnancy breastfeeding safety", f"{name or user_text} kategori hamil")

        if label == STORAGE:
            add(f"{name or user_text} storage", f"{name or user_text} stability", f"{name or user_text} expiry")

        if label == WARNINGS:
            add(f"{name or user_text} warnings precautions")

        if label == COMPARE:
            add(f"{name or user_text} vs", f"alternatif {name or user_text}")

        if label == PRICE_AVAILABILITY:
            add(f"{name or user_text} availability")

        if label == CHEMICAL_QUERY:
            add(f"{name or user_text} chemical structure", f"{name or user_text} IUPAC", f"{name or user_text} mechanism")

        # Jika tidak ada canon name dan user_text kosong, biarkan minimal
        if not q:
            add(f"{user_text} obat")

        return QueryBundle(search_query=q, fact_query=facts)


def build_system_prompt() -> str:
    """
    Back-compat wrapper so AgentOrchestrator can import this.
    """
    svc = PromptService()
    try:
        return svc.system_prompt()
    except Exception:
        # fallback aman jika file prompt belum ada
        return "You are MedVerifyAI. Answer concisely in Indonesian. Cite sources when using external facts."

def build_task_prompt(label: str, context: dict):
    """
    Back-compat wrapper that returns an object with:
      - text: the task prompt string
      - search_query: query string for web search tool
      - fact_query: focus instruction for fetch/summarize
      - user_text: original user text (if provided)
    AgentOrchestrator expects task_prompt.search_query etc.
    """
    from types import SimpleNamespace
    svc = PromptService()

    # task prompt (string)
    text_prompt = svc.task_prompt(label, **(context or {}))

    # search & fact queries
    q = svc.build_queries(label, context or {})

    return SimpleNamespace(
        text=text_prompt,
        search_query=q.search_query,
        fact_query=q.fact_query,
        user_text=(context or {}).get("user_text", "")
    )