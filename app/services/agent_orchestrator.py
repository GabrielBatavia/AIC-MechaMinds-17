# app/services/agent_orchestrator.py
from __future__ import annotations
import os, json, re
from typing import Any, Dict, List, Tuple

from .medical_classifier import classify
from .prompt_service import PromptService
from .guards import Guardrails  # jika dipakai di tempat lain
from app.infra.llm.openai_adapter import OpenAILlm
from typing import Any, Dict, List, Tuple

MAX_TURNS = 8 

def _shorten(s: str | None, n: int = 1200) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"

def _dedupe_sources(sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out = []
    for s in sources or []:
        url = (s.get("url") or "").strip()
        if not url:
            continue
        key = url.split("#")[0]
        if key not in seen:
            seen.add(key)
            out.append({"url": url, "title": (s.get("title") or "").strip()})
    return out

def _rank_sources(sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Utamakan domain resmi/tepercaya; sisanya diurutkan stabil."""
    def score(u: str) -> Tuple[int, str]:
        u = u.lower()
        if "pom.go.id" in u:         # BPOM resmi
            return (0, u)
        if "who.int" in u or "ema.europa.eu" in u or "fda.gov" in u:
            return (1, u)
        if "bpom" in u or "gov" in u or "ac.id" in u:
            return (2, u)
        return (3, u)
    src = _dedupe_sources(sources or [])
    return sorted(src, key=lambda s: score(s.get("url", "")))


def _extract_turns(ctx: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Ambil riwayat percakapan dari context Redis.
    Dukung key 'last_turns' dari SessionStateService dan map field 'text'->'content'.
    """
    if not isinstance(ctx, dict):
        return []
    for key in ("turns", "messages", "conversation", "last_turns"):
        val = ctx.get(key)
        if isinstance(val, list):
            out = []
            for it in val:
                role = (it.get("role") or "").strip()
                # SessionStateService menyimpan 'text', bukan 'content'
                content = (it.get("content") or it.get("text") or "").strip()
                if role in ("user", "assistant", "system") and content:
                    out.append({"role": role, "content": content})
            if out:
                return out
    return []

def _verification_hint(vr: Dict[str, Any]) -> Dict[str, str] | None:
    """
    Bentuk 1 system-hint singkat dari hasil verify agar writer paham konteks,
    tanpa menambah turn baru ke Redis.
    """
    if not isinstance(vr, dict):
        return None
    canon = (vr.get("canon") or {})
    if not (canon.get("name") or canon.get("nie")):
        return None
    parts = []
    if canon.get("name"): parts.append(f"Nama: {canon.get('name')}")
    if canon.get("nie"): parts.append(f"NIE: {canon.get('nie')}")
    if canon.get("manufacturer"): parts.append(f"Pabrikan: {canon.get('manufacturer')}")
    if vr.get("status_label"): parts.append(f"Status: {vr.get('status_label')}")
    hint = "Konteks verifikasi aktif — " + "; ".join(parts)
    return {"role": "system", "content": hint}

class AgentOrchestrator:
    def __init__(self, llm: OpenAILlm, prompts: PromptService | None = None):
        self.llm = llm
        self.prompts = prompts or PromptService()

    def _out_of_scope(self) -> Dict[str, Any]:
        return {
            "reply_kind": "agent",
            "answer": (
                "Aku fokus pada topik obat/produk kesehatan (BPOM, komposisi, dosis, interaksi, dsb.). "
                "Sebutkan nama/NIE produk atau pertanyaan medisnya ya—biar bisa kubantu lebih tepat."
            ),
            "key_facts": [],
            "sources": [],
            "confidence": "n/a",
            "facts": [],
            "_debug": {"label": "out_of_scope"}
        }

    async def handle(self, convo: Dict[str, Any], user_msg: str, context: Dict[str, Any]) -> Dict[str, Any]:
        # 0) Intent gating
        label = classify(user_msg or "", context)
        if label in ("non_medical", "out_of_scope"):
            return self._out_of_scope()

        # 1) Kumpulkan konteks verifikasi + riwayat
        vr = (context or {}).get("verification") or {}
        canon = vr.get("canon") or {}
        known = {
            "name": canon.get("name"),
            "nie": canon.get("nie"),
            "manufacturer": canon.get("manufacturer"),
            "status_label": vr.get("status_label"),
            "source_url": canon.get("source_url"),
        }

        # Ambil turn terakhir dari Redis
        all_turns = _extract_turns(context)
        recent_turns = all_turns[-MAX_TURNS:] if all_turns else []

        # Tambahkan 1 system-hint verifikasi (jika ada)
        vhint = _verification_hint(vr)
        if vhint:
            # letakkan sebelum recent_turns agar dekat dengan system
            history_for_writer = [vhint] + recent_turns
        else:
            history_for_writer = recent_turns

        # Seatbelt: bila terlalu umum & tanpa hint medis & tanpa canon → out_of_scope
        MEDICAL_HINTS = r"\b(obat|bpom|nie|komposisi|kandungan|dosis|aturan pakai|efek samping|kontraindikasi|interaksi|kehamilan|menyusui|penyimpanan|peringatan)\b"
        if label == "general_drug_info" and not (known.get("name") or known.get("nie")) and not re.search(MEDICAL_HINTS, user_msg, flags=re.I):
            return self._out_of_scope()

        # 2) SCOUT PASS — web search (opsional: bawa sedikit history)
        scout_system = (
            "Anda adalah Research Scout untuk MedVerify-Agent. "
            "Tugas Anda menelusuri web dan merangkum temuan relevan secara netral, singkat, dan faktual. "
            "Jangan beropini; cukup ringkas poin penting dan kumpulkan sumber (URL + judul)."
        )
        scout_payload = {
            "question": user_msg,
            "known_verification": known,
            "policy": [
                "Cari sumber resmi/tepercaya terlebih dahulu (BPOM/pom.go.id, WHO, EMA, FDA).",
                "JANGAN membuat kesimpulan klinis; cukup ringkas temuan dan catat sumber."
            ],
        }
        web_opts = {"search_context_size": os.getenv("LLM_SEARCH_CTX", "medium")}

        # Untuk scout kita bawa history singkat (2 turn terakhir) agar query lebih kontekstual
        scout_history = history_for_writer[-2:]

        scout_out = await self.llm.complete(
            system=scout_system,
            user=scout_payload,
            use_web_search=True,
            web_opts=web_opts,
            history=scout_history,    # ⬅️ NEW
        )
        scout_summary = _shorten((scout_out.get("answer") if isinstance(scout_out, dict) else str(scout_out)) or "")
        raw_sources = (scout_out.get("sources") if isinstance(scout_out, dict) else []) or []
        sources = _rank_sources(raw_sources)[:8]

        # 3) WRITER PASS — AI utama interaksi, web hanya referensi
        writer_system = self.prompts.system_prompt() + " Nada: profesional-ramah, empatik, tidak kaku."
        writer_payload = {
            "question": user_msg,
            "intent": label,
            "known_verification": known,
            "web_findings": {"summary": scout_summary, "sources": sources},
            "style": [
                "Berinteraksilah secara natural (boleh satu follow-up singkat bila perlu).",
                "Utamakan konteks sesi (produk/NIE) bila tersedia.",
                "Gunakan temuan web SEBAGAI REFERENSI TAMBAHAN saja.",
            ],
            "requirements": [
                "Jawab ringkas (≈80–120 kata) dan jelas.",
                "Jika mengambil fakta dari temuan, beri sitasi minimal [1] [2] yang merujuk daftar sumber.",
                "Jika data tidak jelas/tidak ada, katakan tidak tersedia dengan sopan.",
            ],
        }

        writer_out = await self.llm.complete(
            system=writer_system,
            user=writer_payload,
            use_web_search=False,         # AI utama menulis, TANPA browsing
            history=history_for_writer,   # ⬅️ NEW: bawa history penuh + hint verify
        )

        answer = (writer_out.get("answer") if isinstance(writer_out, dict) else str(writer_out) or "").strip()
        confidence = "high" if sources else "medium"

        return {
            "reply_kind": "agent",
            "answer": answer,
            "key_facts": [],
            "sources": sources,
            "confidence": confidence,
            "facts": [],
            "_debug": {
                "label": label,
                "used_search": True,
                "has_known": bool(known.get("name") or known.get("nie")),
                "history_len": len(history_for_writer),
            }
        }