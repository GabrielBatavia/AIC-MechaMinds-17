# app/services/prompt_service.py
import os, yaml
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

PROMPT_DIR = Path(os.getenv("PROMPT_DIR", "config/prompts"))

def _ctxdict(ctx: Any) -> Dict[str, Any]:
    """Pastikan konteks selalu dict (hindari 'str has no attribute get')."""
    return ctx if isinstance(ctx, dict) else {}

class PromptService:
    def __init__(self):
        self.base_system = (PROMPT_DIR / "base_system.md").read_text(encoding="utf-8")
        self.intents = yaml.safe_load((PROMPT_DIR / "intents.yaml").read_text(encoding="utf-8"))

    def system_prompt(self) -> str:
        return self.base_system

    def task_prompt(self, label: str, **kwargs) -> str:
        tpl = self.intents.get(label)
        if not tpl:
            return f"User asks: {kwargs.get('user_text','')}. Search authoritative sources; cite everything."
        # naive template expansion {{var}}
        txt = tpl
        for k, v in kwargs.items():
            txt = txt.replace("{{"+k+"}}", str(v))
        return txt

    def build_queries(self, label: str, ctx: Dict[str, Any]) -> SimpleNamespace:
        ctx = _ctxdict(ctx)
        vr = ctx.get("verification") or {}
        canon = vr.get("canon") or {}
        name = canon.get("name") or ctx.get("product_name")
        nie  = canon.get("nie")  or ctx.get("nie")
        ai   = ctx.get("active_ingredient")

        if label == "composition_query":
            q  = f'"{name or nie}" komposisi site:cekbpom.pom.go.id OR site:bpom.go.id'
            fq = "extract composition list with strengths"
        elif label == "interactions":
            q  = f'"{ai or name}" drug interactions'
            fq = "major and moderate interactions with mechanism and clinical management"
        elif label == "pregnancy_safety":
            q  = f'"{ai or name}" pregnancy lactation safety'
            fq = "pregnancy category (if any), key warnings, lactation notes"
        else:
            q  = f'"{name or nie}" BPOM'
            fq = "verify facts with quotes"

        return SimpleNamespace(search_query=q, fact_query=fq)


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