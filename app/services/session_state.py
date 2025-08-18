# app/services/session_state.py
from datetime import datetime, timezone
from typing import Literal, Optional, List, Dict, Any
from app.infra.cache.redis_cache import RedisCache  

Role = Literal["user", "assistant", "system"]

class SessionStateService:
    def __init__(self, store: RedisCache):
        self.rs = store

    # ---- Verification (from /verify) ----
    async def save_verification(self, session_id: str, verification: dict):
        await self.rs.set_json(f"session:{session_id}:verification", verification)
        await self.rs.hset(f"session:{session_id}:meta", {
            "updated_at": datetime.now(timezone.utc).isoformat()
        })

    async def get_verification(self, session_id: str) -> Optional[dict]:
        return await self.rs.get_json(f"session:{session_id}:verification")

    # ---- Intent + facts (from /agent) ----
    async def set_last_intent(self, session_id: str, label: str):
        await self.rs.set_json(f"session:{session_id}:last_intent", label)

    async def get_last_intent(self, session_id: str) -> Optional[str]:
        return await self.rs.get_json(f"session:{session_id}:last_intent")

    async def set_agent_facts(self, session_id: str, facts: List[dict]):
        await self.rs.set_json(f"session:{session_id}:agent_facts", facts)

    async def get_agent_facts(self, session_id: str) -> List[dict]:
        return (await self.rs.get_json(f"session:{session_id}:agent_facts")) or []

    # ---- History (compact) ----
    async def append_turn(self, session_id: str, role: Role, content: str, meta: Dict[str, Any] | None = None):
        item = {
            "t": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "text": content[:2000],   # keep small; we store long facts separately
            "meta": meta or {}
        }
        await self.rs.lpush_cap(f"session:{session_id}:history", item, cap=30)

    async def get_last_turns(self, session_id: str, n: int = 12):
        return await self.rs.lrange_json(f"session:{session_id}:history", 0, n-1)

    # ---- Snapshot for Agent context ----
    async def get_agent_context(self, session_id: str) -> dict:
        return {
            "verification": await self.get_verification(session_id),
            "last_intent": await self.get_last_intent(session_id),
            "last_turns": await self.get_last_turns(session_id),
            "facts": await self.get_agent_facts(session_id),
        }
