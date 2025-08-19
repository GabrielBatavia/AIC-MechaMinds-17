# app/infra/api/verify.py
from fastapi import APIRouter, Depends, HTTPException
from app.services.query_parser import parse_user_query
from app.services.verification_service import VerificationService
from app.services.session_state import SessionStateService
from app.api.deps import get_verification_svc, get_session_state   # <-- ADD

router = APIRouter()

@router.post("/v1/verify")
async def verify(req: dict,
                 verif: VerificationService = Depends(get_verification_svc),
                 sess: SessionStateService = Depends(get_session_state)):
    if "session_id" not in req or "text" not in req:
        raise HTTPException(status_code=400, detail="Missing session_id or text")

    pq = parse_user_query(req["text"])
    vr = await verif.verify(pq)
    await sess.save_verification(req["session_id"], vr)
    await sess.append_turn(req["session_id"], "user", req["text"])
    return {
      "reply_kind": "template",
      "verification": vr,
      "next": "ask_followup"
    }
