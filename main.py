import os
import httpx
import traceback
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from platform.logging_config import setup_logging
from platform.bootstrap import bootstrap_application
from personality.response import SystemResponse

# Initialize structured logging
setup_logging("INFO")

app = FastAPI(
    title="ARIA AI Operating Platform",
    version="12.0.0",
    description="Production-grade AI Operating System with 12-phase modular architecture."
)

@app.on_event("startup")
async def startup_event():
    """Bootstraps all 12 platform subsystems and registers them into the container on startup."""
    registry = await bootstrap_application()
    app.state.registry = registry

@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully disposes of active connections and clients on shutdown."""
    if app.state.registry.has("http_client"):
        await app.state.registry.get("http_client").aclose()
    if app.state.registry.has("mongo_client"):
        app.state.registry.get("mongo_client").close()

async def process_task(user_text: str, session_id: str, app_state) -> str:
    """Executes an incoming user message through ARIA's full 12-phase orchestration pipeline."""
    registry = app_state.registry
    session_mgr = registry.get("session_manager")
    memory_eng = registry.get("memory_engine")
    skill_mgr = registry.get("skill_manager")
    planner = registry.get("planner")
    executor = registry.get("executor")
    personality_eng = registry.get("personality_engine")

    # 1. Non-blocking deterministic memory extraction (Phase 2.1)
    if memory_eng is not None:
        import asyncio
        asyncio.create_task(memory_eng.deterministic_extract_and_store(user_text))

    # 2. Retrieve Unified Session & World State Context (Phase 6)
    session = session_mgr.get_or_create_session(session_id)
    base_context = {"app_state": app_state, "session": session}

    # 3. Direct Skill Routing / Zero-LLM Fast Path (Phase 4)
    for skill in skill_mgr.skills:
        conf = await skill.can_run(user_text, base_context)
        if conf >= 0.90:
            res = await skill.execute(user_text, base_context)
            sys_res = SystemResponse(
                success=res.success,
                confidence=res.confidence,
                data=res.data,
                source=res.source,
                error=res.error
            )
            return personality_eng.apply_personality(session_id, user_text, sys_res)

    # 4. Fallback: Planner + Executor Orchestration (Phase 5 & 10)
    available_skills_desc = {s.name: s.description for s in skill_mgr.skills}
    plan = await planner.create_plan(user_text, available_skills_desc, base_context)
    exec_result = await executor.execute_plan(plan, base_context)

    final_data = exec_result.get("task_outputs", {})
    success = exec_result.get("success", False)

    sys_res = SystemResponse(
        success=success,
        confidence=plan.confidence,
        data=final_data,
        source="planner_executor",
        error=None if success else "One or more orchestration tasks failed execution."
    )

    # 5. Personality Presentation Layer (Phase 9)
    return personality_eng.apply_personality(session_id, user_text, sys_res)

@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    """Production webhook endpoint for Telegram messaging integration."""
    config = app.state.registry.get("config")
    token = config.telegram_token
    if not token:
        return {"status": "telegram token unconfigured"}

    try:
        data = await req.json()
        msg = data.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()

        if chat_id is None or not text:
            return {"status": "ok"}

        # Process through full ARIA architecture
        reply_text = await process_task(text, str(chat_id), app.state)

        # Dispatch back via Telegram Bot API
        http_client = app.state.registry.get("http_client")
        await http_client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": reply_text}
        )
        return {"status": "ok"}
    except Exception:
        traceback.print_exc()
        return {"status": "error"}

@app.get("/health")
async def health():
    """Liveness and readiness check endpoint for container orchestrators (Phase 12)."""
    checker = app.state.registry.get("health_checker")
    status_report = await checker.check_readiness()
    status_code = 200 if status_report["status"] == "healthy" else 503
    return JSONResponse(status_code=status_code, content=status_report)

@app.get("/")
async def root():
    return {"system": "ARIA AI Operating Platform", "status": "operational", "version": "12.0.0"}
