# app/infra/api/agent.py
from fastapi import APIRouter, Depends, HTTPException
from app.services.session_state import SessionStateService
from app.services.medical_classifier import classify
from app.services.prompt_service import PromptService
from app.services.agent_orchestrator import AgentOrchestrator
from app.api.deps import get_session_state, get_prompt_service, get_agent_orchestrator

router = APIRouter()

@router.post("/v1/agent")
async def agent(req: dict,
                sess: SessionStateService = Depends(get_session_state),
                prompts: PromptService = Depends(get_prompt_service),
                agent: AgentOrchestrator = Depends(get_agent_orchestrator)):
    if "session_id" not in req or "text" not in req:
        raise HTTPException(status_code=400, detail="Missing session_id or text")

    ctx = await sess.get_agent_context(req["session_id"])

    # ⬇️ PASS CONTEXT ke classifier biar paham “obat ini”, “apa itu <produk>”, dst.
    label = classify(req["text"], ctx)
    await sess.set_last_intent(req["session_id"], label)

    sys_prompt = prompts.system_prompt()
    task_prompt = prompts.task_prompt(
        label,
        user_text=req["text"],
        product_or_nie=(ctx.get("verification") or {}).get("canon", {}).get("nie")
                       or (ctx.get("verification") or {}).get("canon", {}).get("name")
    )
    q = prompts.build_queries(label, {**ctx, "user_text": req["text"]})
    out = await agent.handle(
        sys_prompt=sys_prompt,
        task_prompt=task_prompt,
        search_query=q.search_query,
        fact_query=q.fact_query
    )

    await sess.set_agent_facts(req["session_id"], out.get("key_facts", []))
    await sess.append_turn(req["session_id"], "user", req["text"])
    await sess.append_turn(
        req["session_id"], "assistant",
        out.get("answer", ""), {"sources": out.get("sources", [])}
    )
    return {"reply_kind": "agent", **out}
