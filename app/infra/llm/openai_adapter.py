# app/infra/llm/openai_adapter.py
from __future__ import annotations
import os, json
from typing import Any, Dict, List, Optional

from app.domain.ports import LlmPort

try:
    from openai import AsyncOpenAI
except Exception:
    AsyncOpenAI = None  # type: ignore

SYSTEM_PROMPT = (
    "Kamu MedVerifyAI. Jawab ringkas, akurat, dan aman (≤120 kata, Bahasa Indonesia). "
    "Sertakan sitasi bila jawaban bersumber dari web search. Jika data tidak jelas, katakan tidak tersedia."
)

class OpenAILlm(LlmPort):
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.dev_mode = os.getenv("DEV_MODE", "0") == "1"
        self.chat_model = os.getenv("LLM_MODEL", "gpt-4o-mini")  # untuk jawaban biasa
        self.search_model = os.getenv("LLM_SEARCH_MODEL", "gpt-4o-mini-search-preview")  # web search
        self._client = None

    def _client_ok(self) -> bool:
        return bool(self.api_key) and (AsyncOpenAI is not None) and not self.dev_mode

    def _ensure_client(self):
        if self._client is None and self._client_ok():
            self._client = AsyncOpenAI(api_key=self.api_key)

    def _to_msg_content(self, obj: Any) -> str:
        if obj is None:
            return ""
        if isinstance(obj, (dict, list)):
            return json.dumps(obj, ensure_ascii=False)
        return str(obj)

    # ==== DIPAKAI OLEH VERIFY USE-CASE ====
    async def explain(self, verdict) -> str:
        """Ringkasan verifikasi (tanpa web search). Kompatibel dengan LlmPort."""
        data = verdict.model_dump() if hasattr(verdict, "model_dump") else verdict or {}
        if not self._client_ok():
            # Fallback lokal/dev
            prod = (data.get("product") or {})
            name = prod.get("name") or prod.get("nie") or "produk"
            status = data.get("status") or "unknown"
            src = data.get("source") or "-"
            return f"Produk {name} status {status}. Sumber: {src}."
        # Online
        self._ensure_client()
        try:
            rsp = await self._client.chat.completions.create(
                model=self.chat_model,
                messages=[
                    {"role": "system", "content": "Ringkas hasil verifikasi untuk pengguna umum, ≤80 kata, Bahasa Indonesia, tanpa menambah fakta baru."},
                    {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                ],
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
                max_tokens=160,
            )
            return (rsp.choices[0].message.content or "").strip()
        except Exception:
            return "Ringkasan verifikasi tersedia."

    # ==== DIPAKAI OLEH AGENT (bisa dengan web search) ====
    async def complete(
        self,
        *,
        system: str,
        user: Any,
        use_web_search: bool = False,
        web_opts: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, str]]] = None,   # ⬅️ NEW
    ) -> Dict[str, Any]:
        """
        Unified completion.
        Now supports chat history: messages = [system] + history + [user].
        Saat use_web_search=True, gunakan model web-search preview TANPA temperature/top_p.
        """

        # Fallback lokal/dev
        if not self._client_ok():
            text = self._to_msg_content(user)
            return {
                "answer": "Mode lokal/dev: tidak memanggil LLM. Saya butuh koneksi ke OpenAI untuk mencari komposisi terbaru.",
                "sources": [],
                "key_facts": [],
                "confidence": "low",
                "_debug": {"offline": True, "echo_user": text[:2000]},
            }

        self._ensure_client()

        # --- SUSUN CHAT MESSAGES --- #
        messages: List[Dict[str, str]] = [{"role": "system", "content": system or SYSTEM_PROMPT}]

        # history diharapkan list[{"role":"user"|"assistant"|"system","content":str}]
        if history:
            for h in history:
                role = (h.get("role") or "").strip()
                content = self._to_msg_content(h.get("content"))
                if role in ("user", "assistant", "system") and content:
                    messages.append({"role": role, "content": content})

        # user terakhir
        messages.append({"role": "user", "content": self._to_msg_content(user)})

        if not use_web_search:
            rsp = await self._client.chat.completions.create(
                model=self.chat_model,
                messages=messages,
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "400")),
            )
            msg = rsp.choices[0].message
            return {
                "answer": (msg.content or "").strip(),
                "sources": [],
                "key_facts": [],
                "confidence": "medium",
                "model": self.chat_model
            }

        # Web search preview — JANGAN sertakan temperature/top_p
        opts = web_opts or {}
        rsp = await self._client.chat.completions.create(
            model=self.search_model,
            messages=messages,                # ⬅️ PENTING: kirim history juga
            web_search_options=opts,
        )
        msg = rsp.choices[0].message
        answer = (msg.content or "").strip()

        # Ambil citations bila ada
        sources: List[Dict[str, str]] = []
        annotations = getattr(msg, "annotations", None)
        if annotations and isinstance(annotations, list):
            for a in annotations:
                try:
                    if a.get("type") == "url_citation":
                        uc = a.get("url_citation") or {}
                        if uc.get("url"):
                            sources.append({"url": uc.get("url"), "title": uc.get("title") or ""})
                except Exception:
                    continue

        return {
            "answer": answer,
            "sources": sources,
            "key_facts": [],
            "confidence": "high" if sources else "medium",
            "model": self.search_model,
        }
