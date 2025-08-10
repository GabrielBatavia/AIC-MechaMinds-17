# app/infra/llm/openai_adapter.py
import os, json
from openai import AsyncOpenAI
from app.domain.ports import LlmPort

_API_KEY = os.getenv("OPENAI_API_KEY")
_DEV_MODE = os.getenv("DEV_MODE") == "1"
client = AsyncOpenAI(api_key=_API_KEY)

SYSTEM_PROMPT = (
    "Kamu MedVerifyAI. Jawab ringkas (≤100 kata, bahasa Indonesia) "
    "hanya menggunakan data pada konteks JSON."
)

class OpenAILlm(LlmPort):
    async def explain(self, verdict):
        # dev-safe: skip network if no key or DEV_MODE
        if _DEV_MODE or not _API_KEY:
            return "Ringkasan: verifikasi selesai (mode dev, tanpa panggilan LLM)."

        content = json.dumps(verdict.model_dump(), ensure_ascii=False)
        rsp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            max_tokens=120,
            temperature=0.0,
        )
        return (rsp.choices[0].message.content or "").strip()
