# app/infra/llm/openai_embedder.py
from __future__ import annotations
import os, time
from typing import List, Optional
from openai import OpenAI
from openai import APIConnectionError, RateLimitError
from dotenv import load_dotenv

# Load .env lebih awal
load_dotenv()

_DEFAULT_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")  # 1536 dim

def _mk_client(api_key: Optional[str] = None) -> OpenAI:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY tidak ditemukan. Set env var atau .env dengan OPENAI_API_KEY=sk-***"
        )
    base = os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL")  # optional proxy
    org  = os.getenv("OPENAI_ORG") or os.getenv("OPENAI_ORGANIZATION")
    proj = os.getenv("OPENAI_PROJECT")

    kwargs = {"api_key": key}
    if base: kwargs["base_url"] = base
    if org:  kwargs["organization"] = org
    if proj: kwargs["project"] = proj
    return OpenAI(**kwargs)

class OpenAIEmbedder:
    def __init__(self, *, model: str | None = None, api_key: str | None = None):
        self.model = model or _DEFAULT_MODEL
        self.api_key = api_key
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = _mk_client(self.api_key)
        return self._client

    def _embed(self, inputs: List[str]) -> List[List[float]]:
        # retry sederhana untuk rate limit / koneksi
        for attempt in range(5):
            try:
                rsp = self.client.embeddings.create(model=self.model, input=inputs)
                return [d.embedding for d in rsp.data]
            except (RateLimitError, APIConnectionError) as e:
                sleep_s = min(2 ** attempt, 8)
                time.sleep(sleep_s)
                continue
        # satu percobaan terakhir (biar error terlihat)
        rsp = self.client.embeddings.create(model=self.model, input=inputs)
        return [d.embedding for d in rsp.data]

    def embed_query(self, text: str) -> list[float]:
        inp = [(text or "").replace("\n", " ")]
        return self._embed(inp)[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        inp = [t.replace("\n", " ") for t in texts]
        return self._embed(inp)
