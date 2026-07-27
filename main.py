import os
import uuid
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from core.logging_config import setup_logging
from core.bootstrap import bootstrap_application
from core.dependency_injection import RequestContext
from personality.response import SystemResponse

setup_logging("INFO")
logger = logging.getLogger("aria")

GREETINGS = {
    "hi", "hello", "hey", "hii", "hi there", "hello there",
    "good morning", "good afternoon", "good evening", "greetings",
    "how are you", "what's up", "sup"
}

class BackgroundTaskManager:
    def __init__(self):
        self.tasks = set()

    def schedule(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def shutdown(self):
        if self.tasks:
            logger.info("[BackgroundTaskManager] Awaiting completion of %d background tasks...", len(self.tasks))
            await asyncio.gather(*self.tasks, return_exceptions=True)

background_manager = BackgroundTaskManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = await bootstrap_application()
    app.state.registry = registry
    app.state.bg_manager = background_manager
    logger.info("[Lifespan] ARIA Platform successfully started.")
    yield
    logger.info("[Lifespan] Shutting down resources...")
    await background_manager.shutdown()
    
    if registry.has("scheduler"):
        try:
            registry.get("scheduler").shutdown()
        except Exception:
            pass
    if registry.has("http_client"):
        await registry.get("http_client").aclose()
    if registry.has("mongo_client"):
        registry.get("mongo_client").close()
    logger.info("[Lifespan] All resources successfully released.")

app = FastAPI(title="ARIA AI Operating Platform", version="12.0.0", lifespan=lifespan)

@app.middleware("http")
async def add_request_metadata(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("[GlobalExceptionHandler] Unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content={"success": False, "error": "An internal system error occurred, Sir.", "detail": str(exc)})

def build_request_context(session_id: str, request_id: str, registry) -> RequestContext:
    return RequestContext(
        session_id=session_id,
        request_id=request_id,
        session_manager=registry.get("session_manager"),
        memory_engine=registry.get("memory_engine"),
        skill_manager=registry.get("skill_manager"),
        action_manager=registry.get("action_manager"),
        planner=registry.get("planner"),
        cognitive_core=registry.get("cognitive_core"),
        executor=registry.get("executor"),
        personality_engine=registry.get("personality_engine"),
        context_manager=registry.get("context_manager"),
        event_bus=registry.get("event_bus")
    )

async def process_task(user_text: str, session_id: str, request_id: str, app_state) -> str:
    registry = app_state.registry
    ctx = build_request_context(session_id, request_id, registry)

    if ctx.memory_engine is not None:
        app_state.bg_manager.schedule(ctx.memory_engine.deterministic_extract_and_store(user_text))

    session = ctx.session_manager.get_or_create_session(session_id)
    base_context = {
        "app_state": app_state,
        "session": session,
        "memory_engine": registry.get("memory_engine") if registry.has("memory_engine") else None,
        "document_intelligence": registry.get("document_intelligence") if registry.has("document_intelligence") else None
    }

    cleaned_text = user_text.lower().strip()

    # Fast-Path: Bypass planning/execution for conversational greetings, leaving wording to PersonalityEngine
    if cleaned_text in GREETINGS:
        sys_res = SystemResponse(
            success=True,
            confidence=1.0,
            data={"intent": "greeting", "query": user_text},
            source="greeting_fast_path"
        )
        return ctx.personality_engine.apply_personality(session_id, user_text, sys_res)

    # 1. Strict SkillManager Routing & Direct Execution
    skill_response = await ctx.skill_manager.route_and_execute(user_text, base_context)
    if skill_response.success and skill_response.confidence >= 0.85:
        sys_res = SystemResponse(
            success=True,
            confidence=skill_response.confidence,
            data=skill_response.data,
            source=skill_response.source
        )
        return ctx.personality_engine.apply_personality(session_id, user_text, sys_res)

    # 2. Planner + Executor Orchestration Fallback
    plan = await ctx.planner.create_plan(user_text, base_context)
    
    # Graceful handling if planner returns empty task list
    if not plan.tasks:
        sys_res = SystemResponse(
            success=True,
            confidence=plan.confidence,
            data={"intent": "conversational", "query": user_text},
            source="planner_conversational"
        )
        return ctx.personality_engine.apply_personality(session_id, user_text, sys_res)

    exec_result = await ctx.executor.execute_plan(plan, base_context)

    final_data = exec_result.get("task_outputs", {})
    success = exec_result.get("success", False)
    combined_confidence = round((plan.confidence + skill_response.confidence) / 2.0, 2)

    sys_res = SystemResponse(
        success=success,
        confidence=combined_confidence,
        data=final_data,
        source="planner_executor",
        error=None if success else "Orchestration tasks encountered failures."
    )

    return ctx.personality_engine.apply_personality(session_id, user_text, sys_res)

@app.post("/telegram-webhook")
async def telegram_webhook(req: Request):
    request_id = req.headers.get("X-Request-ID", str(uuid.uuid4()))
    config = req.app.state.registry.get("config")
    token = config.telegram_token
    if not token:
        return {"status": "telegram token unconfigured"}

    data = await req.json()
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "").strip()

    if chat_id is None or not text:
        return {"status": "ok"}

    reply_text = await process_task(text, str(chat_id), request_id, req.app.state)
    
    # Diagnostic log to isolate whether {} comes from process_task or the API transport
    logger.info("[Telegram] Final reply text: %r", reply_text)

    http_client = req.app.state.registry.get("http_client")
    await http_client.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": reply_text}
    )
    return {"status": "ok"}

@app.get("/health")
async def health(req: Request):
    registry = req.app.state.registry
    checker = registry.get("health_checker")
    base_health = await checker.check_readiness()

    extended_status = {
        **base_health,
        "subsystems": {
            "memory_engine": registry.has("memory_engine"),
            "skill_manager": registry.has("skill_manager"),
            "action_manager": registry.has("action_manager"),
            "plugin_manager": registry.has("plugin_manager"),
            "scheduler": registry.has("scheduler"),
            "http_client": registry.has("http_client")
        },
        "plugins_loaded": list(registry.get("plugin_manager").plugins.keys()) if registry.has("plugin_manager") else [],
        "version": "12.0.0"
    }
    
    status_code = 200 if base_health["status"] == "healthy" else 503
    return JSONResponse(status_code=status_code, content=extended_status)

@app.get("/")
async def root():
    return {"system": "ARIA AI Operating Platform", "status": "operational", "version": "12.0.0"}
