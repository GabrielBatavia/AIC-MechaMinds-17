# app/services/agent_orchestrator.py
from __future__ import annotations
import os, json
from typing import Any, Dict, List
import json
from .medical_classifier import classify
from .prompt_service import PromptService, build_system_prompt, build_task_prompt
from .guards import Guardrails
from app.infra.llm.openai_adapter import OpenAILlm


class AgentOrchestrator:
    def __init__(self, llm: OpenAILlm, prompts: PromptService | None = None):
        self.llm = llm
        self.prompts = prompts or PromptService()


    def _normalize_output(self, draft: Any, sources: List[str], facts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Terima string/dict dari LLM → pastikan keluar dict {answer, key_facts, sources, confidence}
        """
        data: Dict[str, Any] = {}
        if isinstance(draft, str):
            s = draft.strip()
            # kalau string tampak JSON, coba parse
            if s.startswith("{") and s.endswith("}"):
                try:
                    data = json.loads(s)
                except Exception:
                    data = {"answer": s}
            else:
                data = {"answer": s}
        elif isinstance(draft, dict):
            data = draft.copy()
        else:
            data = {"answer": str(draft)}

        # normalisasi bidang
        ans = data.get("answer") or data.get("message") or data.get("text") or ""
        kf  = data.get("key_facts") or data.get("facts") or []
        src = data.get("sources") or sources
        conf = data.get("confidence") or "unknown"

        # pastikan tipe list
        if not isinstance(kf, list): kf = [kf]
        if not isinstance(src, list): src = [src]

        return {
            "answer": ans,
            "key_facts": kf,
            "sources": src,
            "confidence": conf,
            "facts": facts,  # tetap kembalikan facts mentah dari fetch tool (jika ada)
        }

    async def handle(self, convo: Dict[str, Any], user_msg: str, context: Dict[str, Any]) -> Dict[str, Any]:
        label = classify(user_msg or "")
        if label == "non_medical":
            return {
                "reply_kind": "agent",
                "answer": "Pertanyaan ini di luar topik medis/obat. Tanyakan soal obat, komposisi, dosis, interaksi, atau verifikasi BPOM.",
                "key_facts": [], "sources": [], "confidence": "n/a", "facts": [],
                "_debug": {"label": label}
            }

        # ---- kumpulkan konteks verifikasi dari session ----
        vr = (context or {}).get("verification") or {}
        canon = vr.get("canon") or {}
        known = {
            "name": canon.get("name"),
            "nie": canon.get("nie"),
            "manufacturer": canon.get("manufacturer"),
            "status_label": canon.get("status_label"),
            "source_url": canon.get("source_url"),
        }

        system_prompt = self.prompts.system_prompt()
        # user payload: bawa konteks verif + pertanyaan
        user_payload = {
            "question": user_msg,
            "intent": label,
            "known_verification": known,
            "policy": [
                "Jawab ringkas, akurat, bahasa Indonesia.",
                "Gunakan web search bila perlu dan sertakan sitasi inline.",
                "Jika data tidak ditemukan, katakan tidak tersedia dengan sopan."
            ]
        }

        # jalankan model dengan web_search aktif
        web_opts = {"search_context_size": os.getenv("LLM_SEARCH_CTX", "medium")}
        out = await self.llm.complete(system=system_prompt, user=user_payload, use_web_search=True, web_opts=web_opts)

        answer = out["answer"] if isinstance(out, dict) else str(out)
        sources = (out.get("sources") if isinstance(out, dict) else []) or []
        confidence = "medium" if sources else "low"

        return {
            "reply_kind": "agent",
            "answer": answer,
            "key_facts": [],
            "sources": sources,
            "confidence": confidence,
            "facts": [],
            "_debug": {"label": label, "used_search": True, "known": known}
        }

    def _out_of_scope(self) -> Dict[str, Any]:
        return {
            "reply_kind": "agent",
            "answer": "Pertanyaan ini di luar topik medis/obat. Coba ajukan pertanyaan terkait obat, komposisi, dosis, interaksi, atau verifikasi BPOM.",
            "key_facts": [],
            "sources": [],
            "confidence": "n/a",
            "facts": [],
            "_debug": {"label": "non_medical"}
        }