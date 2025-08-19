# app/infra/api/deps.py
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.verification_service import VerificationService
from app.infra.api.satusehat_adapter import SatusehatAdapter

_cache = RedisCache.from_env()
_session_svc = SessionStateService(_cache)
_prompts = PromptService()
_agent = AgentOrchestrator()                 # sesuaikan ctor jika perlu
_verif = VerificationService(                # sesuaikan ctor jika perlu
    satusehat=SatusehatAdapter(_cache),
    cache=_cache
)

def get_session_state(): return _session_svc
def get_prompt_service(): return _prompts
def get_agent_orchestrator(): return _agent          # <-- ADD
def get_verification_svc(): return _verif            # <-- ADD
