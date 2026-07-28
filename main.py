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

    # Delegate core request processing entirely to CognitiveCore
    sys_res = await ctx.cognitive_core.process(
        query=user_text,
        session_id=session_id,
        user_id=session_id,
        base_context=base_context
    )

    return ctx.personality_engine.apply_personality(
        session_id,
        user_text,
        sys_res
    )

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

    if chat_id is None:
        return {"status": "ok"}

    # Handle document upload
    if "document" in msg:
        document = msg["document"]
        file_id = document["file_id"]

        http_client = req.app.state.registry.get("http_client")

        # Get Telegram file information
        file_info = await http_client.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id}
        )

        file_path = file_info.json()["result"]["file_path"]

        download_url = (
            f"https://api.telegram.org/file/bot"
            f"{token}/{file_path}"
        )

        os.makedirs("uploads", exist_ok=True)

        local_path = os.path.join(
            "uploads",
            os.path.basename(file_path)
        )

        response = await http_client.get(download_url)

        with open(local_path, "wb") as f:
            f.write(response.content)

        document_ai = req.app.state.registry.get("document_intelligence")

        session_id = str(chat_id)

        result = await document_ai.process_document(
            file_path=local_path,
            session_id=session_id
        )

        state_manager = req.app.state.registry.get("state_manager")

        if state_manager:

            state_manager.update_state(
                session_id,
                active_document=True
            )

            state_manager.update_state(
                session_id,
                document_uploaded=True
            )

        summary = result["summary"]
        formatted_response = f"✅ Document processed successfully.\n\nSummary:\n\n{summary}"

        await http_client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": formatted_response
            }
        )

        return {
            "status": "processed"
        }

    reply_text = await process_task(
        text,
        str(chat_id),
        request_id,
        req.app.state
    )

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
