import os
import uuid
import hmac
import hashlib
import base64
import time
import asyncio
import logging
import inspect
import html
import re
from typing import Any
from pathlib import Path
from types import SimpleNamespace
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.logging_config import setup_logging
from core.route_handlers import GreetingHandler
from core.dependency_injection import RequestContext
from core.telegram_status import TelegramStatus
from personality.response import SystemResponse
from api.upload import router as upload_router
from integrations.gmail_readonly import router as gmail_readonly_router
from integrations.google_calendar_readonly import router as calendar_readonly_router
from integrations.google_drive_readonly import router as drive_readonly_router
from integrations.github_account_actions import router as github_account_actions_router
from integrations.phase4_actions import router as phase4_actions_router
from integrations.jarvis_status import router as jarvis_status_router
from integrations.personal_workspace import router as personal_workspace_router
from integrations.verified_automation import router as verified_automation_router
from integrations.nvidia_nim import router as nvidia_nim_router
from integrations.github_webhook import router as github_webhook_router
from brain.development.telegram_development import TelegramDevelopmentInterface
from brain.development.telegram_autonomous_engineering import (
    TelegramAutonomousEngineeringInterface,
)
from brain.development.telegram_approval_interface import (
    TelegramApprovalInterface,
)
from audio_engine import AudioEngine
from brain.knowledge.evidence_cleaner import hide_source_references
from brain.core.long_text_intelligence import analyze_long_text
from brain.telegram.safe_formatting import split_telegram_text, format_plain_text
from brain.knowledge.knowledge_hub import (
    mark_user_activity as _mark_knowledge_activity,
    begin_user_activity as _begin_knowledge_activity,
    end_user_activity as _end_knowledge_activity,
)


# =========================================================
# LOG SECURITY
# =========================================================

_TELEGRAM_URL_RE = re.compile(
    r"(https?://api\.telegram\.org/(?:file/)?bot)[^/\s?]+",
    flags=re.IGNORECASE,
)


def _sanitize_log_text(value: Any) -> str:
    """Remove Telegram bot tokens from log messages and trace text."""

    if value is None:
        return ""

    text = str(value)

    return _TELEGRAM_URL_RE.sub(
        r"\1[REDACTED]",
        text,
    )


class SensitiveLogFilter(logging.Filter):
    """Prevent secrets embedded in log records from being emitted."""

    def filter(self, record: logging.LogRecord) -> bool:

        try:

            rendered = record.getMessage()

            sanitized = _sanitize_log_text(
                rendered
            )

            if sanitized != rendered:

                record.msg = sanitized
                record.args = ()

            if getattr(record, "exc_text", None):

                record.exc_text = _sanitize_log_text(
                    record.exc_text
                )

        except Exception:

            # Logging must never break application execution.
            pass

        return True


setup_logging("INFO")

# httpx/httpcore request logs can contain the full Telegram Bot API URL.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_log_security_filter = SensitiveLogFilter()

for _handler in logging.getLogger().handlers:

    _handler.addFilter(
        _log_security_filter
    )

for _logger_name in (
    "aria",
    "httpx",
    "httpcore",
):

    _named_logger = logging.getLogger(
        _logger_name
    )

    _named_logger.addFilter(
        _log_security_filter
    )


logger = logging.getLogger("aria")


# =========================================================
# TELEGRAM REQUEST SAFETY
# =========================================================

# Maximum amount of time ARIA is allowed to process one Telegram
# request before the operation is stopped.
#
# This prevents:
#
#   - embedding stalls
#   - knowledge retrieval stalls
#   - external API hangs
#   - accidental infinite loops
#   - broken tool calls
#
# Once local knowledge is fast and reliable, this can be reduced.

TELEGRAM_PROCESS_TIMEOUT_SECONDS = max(
    30.0,
    float(
        os.getenv(
            "ARIA_TELEGRAM_PROCESS_TIMEOUT",
            "120",
        )
    ),
)


# =========================================================
# BACKGROUND TASK MANAGER
# =========================================================

class BackgroundTaskManager:

    def __init__(self):

        self.tasks = set()

    def schedule(self, coro):

        task = asyncio.create_task(
            coro
        )

        self.tasks.add(
            task
        )

        task.add_done_callback(
            self.tasks.discard
        )

        return task

    async def shutdown(self):

        if self.tasks:

            logger.info(
                "[BackgroundTaskManager] Awaiting completion "
                "of %d background tasks...",
                len(self.tasks),
            )

            await asyncio.gather(
                *self.tasks,
                return_exceptions=True,
            )


background_manager = BackgroundTaskManager()


# =========================================================
# TELEGRAM UPDATE DEDUPLICATION
# =========================================================

# Telegram supplies a unique update_id with every webhook update.
#
# Telegram can retry an update if the webhook endpoint does not
# acknowledge quickly enough.
#
# Previously, ARIA could receive:
#
#     update 100
#     update 100
#     update 100
#
# and start three independent cognitive requests.
#
# This cache prevents that.
#
# This is currently in-memory because ARIA is running as a single
# Render instance. If ARIA later becomes multi-instance, move this
# mechanism to MongoDB/Redis.

TELEGRAM_UPDATE_DEDUPE_TTL_SECONDS = max(
    300.0,
    float(
        os.getenv(
            "ARIA_TELEGRAM_UPDATE_DEDUPE_TTL",
            "600",
        )
    ),
)

_telegram_update_cache = {}

_telegram_update_lock = asyncio.Lock()


async def claim_telegram_update(
    update_id,
) -> bool:
    """
    Atomically claim a Telegram update.

    Returns:
        True  -> first delivery of this update.
        False -> duplicate delivery.

    Telegram normally provides update_id. If an unusual/custom
    request has no update_id, processing is allowed.
    """

    if update_id is None:

        return True

    try:

        update_key = int(
            update_id
        )

    except (
        TypeError,
        ValueError,
    ):

        update_key = str(
            update_id
        )

    now = asyncio.get_running_loop().time()

    async with _telegram_update_lock:

        # -----------------------------------------------------
        # Remove expired entries.
        # -----------------------------------------------------

        expired = [
            key
            for key, timestamp
            in _telegram_update_cache.items()
            if (
                now - timestamp
                > TELEGRAM_UPDATE_DEDUPE_TTL_SECONDS
            )
        ]

        for key in expired:

            _telegram_update_cache.pop(
                key,
                None,
            )

        # -----------------------------------------------------
        # Duplicate update.
        # -----------------------------------------------------

        if update_key in _telegram_update_cache:

            logger.warning(
                "[Telegram] Duplicate update ignored | "
                "update_id=%s",
                update_key,
            )

            return False

        # -----------------------------------------------------
        # First delivery.
        # -----------------------------------------------------

        _telegram_update_cache[
            update_key
        ] = now

        logger.info(
            "[Telegram] Update claimed | update_id=%s",
            update_key,
        )

        return True


# =========================================================
# PENDING DOCUMENT CONFIRMATIONS
# =========================================================

pending_document_actions = {}


# =========================================================
# FASTAPI LIFESPAN
# =========================================================

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):

    # Delay heavyweight optional service imports until the application starts.
    from core.bootstrap import bootstrap_application

    registry = await bootstrap_application()

    app.state.registry = registry

    app.state.bg_manager = background_manager

    # Phase 7 integration: register the safe engineering staging gate and run
    # the durable proactive task poller as part of the application lifecycle.
    from core.phase7_runtime import initialize_phase7_runtime
    phase7_runtime = await initialize_phase7_runtime(registry, app)

    # When MongoDB is configured, Telegram updates are queued durably before the
    # webhook acknowledges them. A named handler reconstructs only the minimal
    # request shape used by process_telegram_update; no Request object is stored.
    if registry.has("durable_job_queue"):
        durable_queue = registry.get("durable_job_queue")
        if getattr(durable_queue, "available", False):
            async def _process_durable_telegram_update(payload):
                fake_request = SimpleNamespace(app=SimpleNamespace(state=app.state))
                return await process_telegram_update(
                    fake_request,
                    payload["data"],
                    payload["request_id"],
                )

            durable_queue.register_handler(
                "telegram_update",
                _process_durable_telegram_update,
            )
            scheduler = registry.get("scheduler")
            app.state.durable_queue_worker_job = scheduler.schedule_recurring(
                1.0,
                durable_queue.run_one,
                goal_id="aria_durable_job_worker",
                timeout_seconds=60.0,
                run_immediately=True,
            )
            logger.info("[Lifespan] Mongo-backed durable job worker enabled.")

    logger.info(
        "[Lifespan] ARIA Platform successfully started."
    )

    yield

    logger.info(
        "[Lifespan] Shutting down resources..."
    )

    await background_manager.shutdown()

    try:
        await phase7_runtime.shutdown()
    except Exception:
        logger.exception("[Lifespan] Phase 7 runtime shutdown failed.")

    if registry.has(
        "scheduler"
    ):

        try:

            scheduler = registry.get(
                "scheduler"
            )

            shutdown_result = scheduler.shutdown()

            if inspect.isawaitable(
                shutdown_result
            ):

                await shutdown_result

            logger.info(
                "[Lifespan] Scheduler shutdown completed."
            )

        except Exception:

            logger.exception(
                "[Lifespan] Scheduler shutdown failed."
            )

    if registry.has(
        "http_client"
    ):

        await registry.get(
            "http_client"
        ).aclose()

    if registry.has(
        "mongo_client"
    ):

        registry.get(
            "mongo_client"
        ).close()

    logger.info(
        "[Lifespan] All resources successfully released."
    )


# =========================================================
# PRIVATE ANDROID APP AUTHENTICATION
# =========================================================

OWNER_ID_ENV = "ARIA_OWNER_TELEGRAM_ID"
OWNER_SECRET_ENV = "ARIA_OWNER_APP_SECRET"
TOKEN_SECRET_ENV = "ARIA_APP_TOKEN_SECRET"
# Long-lived owner session: sign in once per device; sessions survive app restarts.
APP_TOKEN_TTL_SECONDS = 365 * 24 * 60 * 60


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _security_collection(request: Request):
    """Return Mongo-backed persistent app-security collection or None."""
    try:
        registry = getattr(request.app.state, "registry", None)
        if registry is None or not registry.has("mongo_client"):
            return None
        return registry.get("mongo_client")["aria_db"]["app_security"]
    except Exception:
        return None


def _password_hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return _b64url(salt), _b64url(derived)


def _password_matches(password: str, record: dict) -> bool:
    try:
        salt = base64.urlsafe_b64decode(record["password_salt"] + "=" * (-len(record["password_salt"]) % 4))
        supplied_salt, supplied_hash = _password_hash(password, salt)
        return hmac.compare_digest(supplied_salt, record["password_salt"]) and hmac.compare_digest(supplied_hash, record["password_hash"])
    except (KeyError, ValueError, TypeError):
        return False


def _make_owner_token(owner_id: str, device_id: str, token_version: int) -> str:
    signing_secret = os.getenv(TOKEN_SECRET_ENV, "")
    if len(signing_secret) < 32:
        raise RuntimeError(f"{TOKEN_SECRET_ENV} must contain at least 32 characters.")
    expires = int(time.time()) + APP_TOKEN_TTL_SECONDS
    payload = f"{owner_id}|{device_id}|{expires}|{token_version}".encode("utf-8")
    encoded = _b64url(payload)
    signature = hmac.new(signing_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return encoded + "." + _b64url(signature)


def _decode_owner_token(token: str) -> dict | None:
    signing_secret = os.getenv(TOKEN_SECRET_ENV, "")
    owner_id = os.getenv(OWNER_ID_ENV, "").strip()
    if not signing_secret or not owner_id or not token or "." not in token:
        return None
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = _b64url(hmac.new(signing_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        padded = encoded + "=" * (-len(encoded) % 4)
        owner, device_id, expiry, version = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").rsplit("|", 3)
        if not hmac.compare_digest(owner, owner_id) or not device_id or int(expiry) <= int(time.time()):
            return None
        return {"owner_id": owner, "device_id": device_id, "expires": int(expiry), "version": int(version)}
    except (ValueError, UnicodeError, TypeError):
        return None


class OwnerLoginRequest(BaseModel):
    telegram_id: str
    secret: str
    device_id: str


class OwnerLoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = APP_TOKEN_TTL_SECONDS


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="ARIA AI Operating Platform",
    version="12.0.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def enforce_private_app_access(request: Request, call_next):
    # Health/root, sign-in, and Telegram webhook are public; all other HTTP API routes
    # require a signed owner session whose version still matches persistent Mongo state.
    public_paths = {
        "/", "/health", "/ready", "/app/login", "/telegram-webhook",
        # OAuth callbacks validate one-time state internally; the connect/status
        # endpoints remain protected by the owner-session middleware.
        "/gmail/oauth/callback", "/calendar/oauth/callback",
        "/drive/oauth/callback",
        # GitHub webhook authenticates every request with its HMAC signature.
        "/github-webhook",
    }
    if request.method == "OPTIONS" or request.url.path in public_paths:
        return await call_next(request)
    auth_header = request.headers.get("Authorization", "")
    scheme, _, token = auth_header.partition(" ")
    claims = _decode_owner_token(token.strip()) if scheme.lower() == "bearer" else None
    if claims is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required. Sign in to ARIA."}, headers={"WWW-Authenticate": "Bearer"})
    collection = _security_collection(request)
    if collection is None:
        return JSONResponse(status_code=503, content={"detail": "Persistent private-app security storage is unavailable."})
    try:
        record = await collection.find_one({"_id": claims["owner_id"]})
    except Exception:
        logger.exception("Could not verify ARIA app session against persistent storage")
        return JSONResponse(status_code=503, content={"detail": "Private-app security storage is temporarily unavailable."})
    if not record or int(record.get("token_version", 0)) != claims["version"]:
        return JSONResponse(status_code=401, content={"detail": "This ARIA session was revoked. Please sign in again."}, headers={"WWW-Authenticate": "Bearer"})
    request.state.aria_owner = claims["owner_id"]
    request.state.aria_device_id = claims["device_id"]
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://ariaintel.vercel.app",
        "https://ariaassisant.vercel.app",
        "https://aria-frontend.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(upload_router)
app.include_router(gmail_readonly_router)
app.include_router(calendar_readonly_router)
app.include_router(drive_readonly_router)
app.include_router(github_webhook_router)
app.include_router(github_account_actions_router)
app.include_router(phase4_actions_router)
app.include_router(jarvis_status_router)
app.include_router(personal_workspace_router)
app.include_router(verified_automation_router)
app.include_router(nvidia_nim_router)


# =========================================================
# REQUEST METADATA
# =========================================================

@app.middleware("http")
async def add_request_metadata(
    request: Request,
    call_next,
):

    request_id = request.headers.get(
        "X-Request-ID",
        str(uuid.uuid4()),
    )

    response: Response = await call_next(
        request
    )

    response.headers[
        "X-Request-ID"
    ] = request_id

    return response


# =========================================================
# GLOBAL EXCEPTION HANDLER
# =========================================================

@app.exception_handler(Exception)
async def global_exception_handler(
    request: Request,
    exc: Exception,
):

    logger.exception(
        "[GlobalExceptionHandler] Unhandled exception: %s",
        exc,
    )

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "An internal system error occurred.",
            "detail": str(exc),
        },
    )


# =========================================================
# REQUEST CONTEXT
# =========================================================

def build_request_context(
    session_id: str,
    request_id: str,
    registry,
) -> RequestContext:

    return RequestContext(
        session_id=session_id,
        request_id=request_id,
        session_manager=registry.get(
            "session_manager"
        ),
        memory_engine=registry.get(
            "memory_engine"
        ),
        skill_manager=registry.get(
            "skill_manager"
        ),
        action_manager=registry.get(
            "action_manager"
        ),
        planner=registry.get(
            "planner"
        ),
        cognitive_core=registry.get(
            "cognitive_core"
        ),
        executor=registry.get(
            "executor"
        ),
        personality_engine=registry.get(
            "personality_engine"
        ),
    )


# =========================================================
# MAIN COGNITIVE PIPELINE
# =========================================================

async def process_task(
    user_text: str,
    session_id: str,
    request_id: str,
    app_state,
) -> Any:

    registry = app_state.registry

    ctx = build_request_context(
        session_id,
        request_id,
        registry,
    )

    # -----------------------------------------------------
    # NON-BLOCKING MEMORY EXTRACTION
    # -----------------------------------------------------

    if ctx.memory_engine is not None:

        app_state.bg_manager.schedule(
            ctx.memory_engine.deterministic_extract_and_store(
                user_text
            )
        )

    # -----------------------------------------------------
    # SESSION
    # -----------------------------------------------------

    session = (
        ctx.session_manager.get_or_create_session(
            session_id
        )
    )

    conversation_manager = registry.get(
        "conversation_manager"
    )

    resolved_text = user_text

    # -----------------------------------------------------
    # REFERENCE RESOLUTION
    # -----------------------------------------------------
    # Explicit local-knowledge instructions must reach CognitiveCore
    # unchanged. The reference resolver can otherwise rewrite a short
    # follow-up before the deterministic local-knowledge gate sees it.
    is_local_knowledge_instruction = False
    try:
        is_local_knowledge_instruction = bool(
            ctx.cognitive_core
            and ctx.cognitive_core._is_local_knowledge_instruction(user_text)
        )
    except Exception:
        is_local_knowledge_instruction = False

    if conversation_manager and not is_local_knowledge_instruction:
        resolved_text = conversation_manager.resolve_reference(
            session_id=session_id,
            query=user_text,
        )

    # -----------------------------------------------------
    # BASE CONTEXT
    # -----------------------------------------------------

    # Preserve both the literal user request and available dialogue history.
    # Deterministic follow-up handling must not depend on a rewritten query alone.
    conversation_history = []
    if conversation_manager:
        try:
            conversation_state = conversation_manager.get_session(session_id)
            if isinstance(conversation_state, dict):
                raw_history = conversation_state.get("conversation_history", [])
                if isinstance(raw_history, list):
                    conversation_history = raw_history[-12:]
        except Exception:
            logger.exception("[Conversation] Failed to expose history to cognitive core.")

    # Structural metadata is additive; the exact original query remains intact.
    try:
        long_text_packet = analyze_long_text(user_text)
    except Exception:
        logger.exception("[LongText] Structural analysis failed; preserving raw query.")
        long_text_packet = {
            "character_count": len(user_text), "complete": True,
            "truncated": False, "analysis_error": True,
        }

    base_context = {
        "original_user_query": user_text,
        "long_text_analysis": long_text_packet,
        "conversation_history": conversation_history,
        "app_state": app_state,
        "session": session,
        "memory_engine": (
            registry.get(
                "memory_engine"
            )
            if registry.has(
                "memory_engine"
            )
            else None
        ),
        "document_intelligence": (
            registry.get(
                "document_intelligence"
            )
            if registry.has(
                "document_intelligence"
            )
            else None
        ),
    }

    # -----------------------------------------------------
    # COGNITIVE CORE
    # -----------------------------------------------------

    sys_res = await ctx.cognitive_core.process(
        query=resolved_text,
        session_id=session_id,
        user_id=session_id,
        base_context=base_context,
    )

    # -----------------------------------------------------
    # UPDATE CONVERSATIONAL STATE
    # -----------------------------------------------------

    if conversation_manager:

        assistant_text = str(
            sys_res
        )

        conversation_manager.update_turn(
            session_id=session_id,
            user_message=user_text,
            assistant_message=assistant_text,
            intent=None,
        )

    # -----------------------------------------------------
    # STRUCTURED DOCUMENT ACTIONS
    # -----------------------------------------------------

    if (
        sys_res
        and isinstance(
            sys_res.data,
            dict,
        )
        and sys_res.data.get(
            "document_action"
        )
    ):

        return sys_res

    # -----------------------------------------------------
    # PERSONALITY LAYER
    # -----------------------------------------------------

    return await ctx.personality_engine.apply_personality(
        session_id,
        resolved_text,
        sys_res,
    )


# =========================================================
# TELEGRAM RESPONSE FORMATTER
# =========================================================

def markdown_to_telegram_html(
    text: str,
) -> str:

    if not text:

        return ""

    text = str(text)

    text = text.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    # -----------------------------------------------------
    # PROTECT CODE BLOCKS
    # -----------------------------------------------------

    protected = []

    def protect(match):

        index = len(
            protected
        )

        protected.append(
            match.group(0)
        )

        return (
            f"__ARIA_PROTECTED_{index}__"
        )

    text = re.sub(
        r"```(?:[\w+#.-]+)?\n?.*?```",
        protect,
        text,
        flags=re.DOTALL,
    )

    # -----------------------------------------------------
    # PROTECT INLINE CODE
    # -----------------------------------------------------

    text = re.sub(
        r"`([^`\n]+)`",
        protect,
        text,
    )

    # -----------------------------------------------------
    # ESCAPE HTML
    # -----------------------------------------------------

    text = html.escape(
        text,
        quote=False,
    )

    # -----------------------------------------------------
    # BOLD
    # -----------------------------------------------------

    text = re.sub(
        r"\*\*(.+?)\*\*",
        r"<b>\1</b>",
        text,
        flags=re.DOTALL,
    )

    # -----------------------------------------------------
    # ITALIC
    # -----------------------------------------------------

    text = re.sub(
        r"(?<!\*)\*([^*\n]+?)\*(?!\*)",
        r"<i>\1</i>",
        text,
    )

    # -----------------------------------------------------
    # HEADINGS
    # -----------------------------------------------------

    text = re.sub(
        r"(?m)^\s*#{1,6}\s+(.+?)\s*$",
        r"<b>\1</b>",
        text,
    )

    # -----------------------------------------------------
    # BLOCKQUOTES
    # -----------------------------------------------------

    lines = text.split(
        "\n"
    )

    formatted_lines = []

    for line in lines:

        stripped = line.strip()

        if stripped.startswith(
            "&gt;"
        ):

            quote = stripped[4:].strip()

            if quote:

                formatted_lines.append(
                    f"<blockquote>{quote}</blockquote>"
                )

            else:

                formatted_lines.append(
                    "<blockquote> </blockquote>"
                )

        else:

            formatted_lines.append(
                line
            )

    text = "\n".join(
        formatted_lines
    )

    # -----------------------------------------------------
    # BULLETS
    # -----------------------------------------------------

    text = re.sub(
        r"(?m)^\s*[-*]\s+",
        "• ",
        text,
    )

    # -----------------------------------------------------
    # NUMBERED LISTS
    # -----------------------------------------------------

    text = re.sub(
        r"(?m)^\s*(\d+)\.\s+",
        r"\1. ",
        text,
    )

    # -----------------------------------------------------
    # TABLES
    # -----------------------------------------------------

    lines = text.split(
        "\n"
    )

    output = []

    table_rows = []

    in_table = False

    def flush_table():

        nonlocal table_rows

        if not table_rows:

            return

        rows = []

        for row in table_rows:

            cells = [
                cell.strip()
                for cell in (
                    row.strip()
                    .strip("|")
                    .split("|")
                )
            ]

            if cells and all(
                re.fullmatch(
                    r":?-{3,}:?",
                    cell or "",
                )
                for cell in cells
            ):

                continue

            rows.append(
                cells
            )

        table_rows = []

        if not rows:

            return

        headers = rows[0]

        if len(headers) == 2:

            comparison = []

            for row in rows[1:]:

                if len(row) < 2:

                    continue

                feature = row[0].strip()
                value = row[1].strip()

                if not feature:

                    continue

                comparison.append(
                    f"<b>▸ {feature}</b>\n"
                    f"  {value}"
                )

            if comparison:

                output.append(
                    "\n\n".join(
                        comparison
                    )
                )

            return

        if len(headers) >= 3:

            comparison = []

            names = [
                h.strip()
                for h in headers[1:]
                if h.strip()
            ]

            if names:

                comparison.append(
                    "⚖️ <b>"
                    + " vs ".join(names)
                    + "</b>"
                )

            for row in rows[1:]:

                if not row:

                    continue

                feature = row[0].strip()

                if not feature:

                    continue

                comparison.append(
                    f"<b>▸ {feature}</b>"
                )

                for index in range(
                    1,
                    len(headers),
                ):

                    header = headers[
                        index
                    ].strip()

                    if not header:

                        continue

                    value = (
                        row[index].strip()
                        if index < len(row)
                        else "—"
                    )

                    if not value:

                        value = "—"

                    comparison.append(
                        f"  <b>{header}:</b> {value}"
                    )

                comparison.append("")

            if comparison:

                output.append(
                    "\n".join(
                        comparison
                    ).strip()
                )

    for line in lines:

        stripped = line.strip()

        if (
            stripped.startswith("|")
            and stripped.endswith("|")
            and "|" in stripped[1:-1]
        ):

            table_rows.append(
                line
            )

            in_table = True

            continue

        if in_table:

            flush_table()

            in_table = False

        output.append(
            line
        )

    if in_table:

        flush_table()

    text = "\n".join(
        output
    )

    # -----------------------------------------------------
    # RESTORE PROTECTED CODE
    # -----------------------------------------------------

    for index, original in enumerate(
        protected
    ):

        placeholder = (
            f"__ARIA_PROTECTED_{index}__"
        )

        if original.startswith(
            "```"
        ):

            match = re.match(
                r"```(?:([\w+#.-]+))?\n?(.*?)```$",
                original,
                flags=re.DOTALL,
            )

            if match:

                code = match.group(2)

                code_html = html.escape(
                    code,
                    quote=False,
                )

                replacement = (
                    "<pre><code>"
                    f"{code_html}"
                    "</code></pre>"
                )

            else:

                replacement = (
                    "<pre><code>"
                    f"{html.escape(original)}"
                    "</code></pre>"
                )

        else:

            code = original[1:-1]

            replacement = (
                "<code>"
                f"{html.escape(code, quote=False)}"
                "</code>"
            )

        text = text.replace(
            placeholder,
            replacement,
        )

    # -----------------------------------------------------
    # FINAL CLEANUP
    # -----------------------------------------------------

    text = re.sub(
        r"\*\*(.*?)\*\*",
        r"<b>\1</b>",
        text,
        flags=re.DOTALL,
    )

    text = re.sub(
        r"(?<!\*)\*([^*\n]+?)\*(?!\*)",
        r"<i>\1</i>",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def format_telegram_response(
    text: str,
    *,
    include_sources: bool = False,
) -> str:
    """Format Telegram answers, showing citations only when the user asks for them."""
    visible_text = str(text or "") if include_sources else hide_source_references(text)
    return markdown_to_telegram_html(visible_text)


# =========================================================
# TELEGRAM STATUS
# =========================================================

def get_telegram_status_message(
    text: str,
) -> str:

    query = (
        text or ""
    ).lower().strip()

    if any(
        word in query
        for word in (
            "search",
            "find",
            "latest",
            "news",
            "current",
            "today",
            "recent",
            "look up",
            "online",
        )
    ):

        return (
            "Searching for the relevant information..."
        )

    if any(
        word in query
        for word in (
            "buy",
            "purchase",
            "price",
            "cost",
            "product",
            "shop",
            "shopping",
            "amazon",
            "flipkart",
        )
    ):

        return (
            "Looking for the relevant options..."
        )

    if any(
        word in query
        for word in (
            "pdf",
            "document",
            "file",
            "paper",
            "notes",
        )
    ):

        return (
            "Checking the relevant documents..."
        )

    if any(
        word in query
        for word in (
            "calculate",
            "how much",
            "percentage",
            "convert",
            "multiply",
            "divide",
            "sum",
        )
    ):

        return (
            "Working that out..."
        )

    if any(
        word in query
        for word in (
            "remember",
            "forgot",
            "what do you know about me",
            "my name",
            "what's my",
        )
    ):

        return (
            "Checking what I remember..."
        )

    if any(
        word in query
        for word in (
            "code",
            "python",
            "javascript",
            "program",
            "error",
            "bug",
            "function",
            "api",
        )
    ):

        return (
            "Working through the code..."
        )

    if any(
        word in query
        for word in (
            "compare",
            "difference",
            "versus",
            "vs",
            "which one",
        )
    ):

        return (
            "Comparing the relevant points..."
        )

    if len(query) > 120:

        return (
            "Working through your request..."
        )

    return "Thinking..."


# =========================================================
# SAFE STATUS CLEANUP
# =========================================================

async def safe_delete_status(
    status: TelegramStatus | None,
) -> None:
    """
    Delete the temporary Telegram status.

    Failure to delete the status must never break the actual
    ARIA request.
    """

    if status is None:

        return

    try:

        await status.delete()

    except asyncio.CancelledError:

        raise

    except Exception:

        logger.exception(
            "[TelegramStatus] Failed to delete "
            "temporary status message."
        )


# =========================================================
# TELEGRAM WEBHOOK ENTRYPOINT
# =========================================================

@app.post("/telegram-webhook")
async def telegram_webhook(
    req: Request,
):
    """
    Fast Telegram webhook acknowledgement.

    The webhook MUST acknowledge Telegram quickly.

    Actual ARIA processing is scheduled in the background.

    This prevents Telegram from retrying the same update while
    ARIA is still processing the request.
    """

    request_id = req.headers.get(
        "X-Request-ID",
        str(uuid.uuid4()),
    )

    # ---------------------------------------------------------
    # PARSE UPDATE
    # ---------------------------------------------------------

    try:

        data = await req.json()

    except Exception:

        logger.exception(
            "[Telegram] Failed to decode webhook payload."
        )

        return {
            "status": "invalid_payload"
        }

    update_id = data.get(
        "update_id"
    )

    # ---------------------------------------------------------
    # DUPLICATE PROTECTION
    # ---------------------------------------------------------

    claimed = await claim_telegram_update(
        update_id
    )

    if not claimed:

        return {
            "status": "duplicate_ignored",
            "update_id": update_id,
        }

    # ---------------------------------------------------------
    # BASIC MESSAGE VALIDATION
    # ---------------------------------------------------------

    msg = data.get(
        "message",
        {}
    )

    chat_id = (
        msg.get(
            "chat",
            {}
        ).get(
            "id"
        )
    )

    user_id = (
        msg.get(
            "from",
            {}
        ).get(
            "id"
        )
    )

    if chat_id is None or user_id is None:

        logger.info(
            "[Telegram] Ignoring update without "
            "chat/user information | update_id=%s",
            update_id,
        )

        return {
            "status": "ignored",
            "update_id": update_id,
        }

    # ---------------------------------------------------------
    # PRIVATE OWNER-ONLY ACCESS
    # ---------------------------------------------------------

    allowed_user_id = os.getenv(
        "ALLOWED_TELEGRAM_USER_ID",
        "",
    ).strip()

    if not allowed_user_id:

        logger.error(
            "[Security] ALLOWED_TELEGRAM_USER_ID "
            "is not configured."
        )

        return {
            "status": "unauthorized"
        }

    if str(user_id) != allowed_user_id:

        logger.warning(
            "[Security] Unauthorized Telegram access attempt | "
            "user_id=%s | update_id=%s",
            user_id,
            update_id,
        )

        return {
            "status": "unauthorized"
        }

    logger.info(
        "[Security] Authorized Telegram user | "
        "update_id=%s",
        update_id,
    )

    try:
        _mark_knowledge_activity()
    except Exception:
        logger.exception("[KnowledgeHub] Failed to record incoming user activity.")

    # ---------------------------------------------------------
    # SCHEDULE ACTUAL PROCESSING
    # ---------------------------------------------------------

    logger.info(
        "[Telegram] Scheduling background processing | "
        "update_id=%s | request_id=%s",
        update_id,
        request_id,
    )

    registry = getattr(req.app.state, "registry", None)
    durable_queue = None
    if registry is not None and registry.has("durable_job_queue"):
        candidate = registry.get("durable_job_queue")
        if getattr(candidate, "available", False):
            durable_queue = candidate

    if durable_queue is not None:
        # Stable IDs make Telegram retries idempotent across process restarts.
        durable_id = f"telegram-update-{update_id}" if update_id is not None else None
        try:
            await durable_queue.enqueue(
                "telegram_update",
                {"data": data, "request_id": request_id},
                job_id=durable_id,
            )
        except Exception as exc:
            # A duplicate durable ID means the update was already accepted.
            try:
                existing = await durable_queue.collection.find_one({"_id": durable_id}) if durable_id else None
            except Exception:
                existing = None
            if existing is not None:
                return {"status": "duplicate_ignored", "update_id": update_id}
            logger.exception("[Telegram] Could not persist accepted update %s", update_id)
            return JSONResponse(
                status_code=503,
                content={"status": "temporarily_unavailable", "update_id": update_id},
            )
    else:
        # Explicit fallback for local/test deployments without MongoDB. This is
        # best-effort only and is reported as non-durable by /ready.
        background_manager.schedule(
            process_telegram_update(
                req,
                data,
                request_id,
            )
        )

    # ---------------------------------------------------------
    # IMMEDIATE TELEGRAM ACKNOWLEDGEMENT
    # ---------------------------------------------------------

    return {
        "status": "accepted",
        "update_id": update_id,
    }


# =========================================================
# PHASE 1 — MASTER DEVELOPMENT / VOICE INPUT
# =========================================================

async def _transcribe_telegram_voice(
    *,
    http_client,
    token: str,
    message: dict,
) -> str | None:
    """
    Download a Telegram voice/audio message and transcribe it.

    Telegram voice notes are normally OGG/Opus. AudioEngine performs
    transcription without changing the development safety boundary.
    """
    voice = message.get("voice") or message.get("audio")

    if not isinstance(voice, dict):
        return None

    file_id = voice.get("file_id")
    if not file_id:
        return None

    try:
        file_response = await http_client.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
        )

        if not file_response.is_success:
            logger.error(
                "[Telegram][Voice] getFile failed | status=%s",
                file_response.status_code,
            )
            return None

        file_payload = file_response.json()

        if not file_payload.get("ok"):
            logger.error(
                "[Telegram][Voice] Telegram getFile returned failure."
            )
            return None

        file_path = (
            file_payload.get("result", {})
            .get("file_path")
        )

        if not file_path:
            return None

        audio_response = await http_client.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}"
        )

        if not audio_response.is_success:
            logger.error(
                "[Telegram][Voice] Audio download failed | status=%s",
                audio_response.status_code,
            )
            return None

        audio_bytes = audio_response.content

        mime_type = "audio/ogg"
        if message.get("audio"):
            mime_type = (
                message.get("audio", {}).get("mime_type")
                or "audio/mpeg"
            )

        engine = AudioEngine()

        # transcribe_audio is async; awaiting it directly avoids returning an
        # un-awaited coroutine from asyncio.to_thread. The engine itself moves
        # blocking provider work off the event loop.
        result = await engine.transcribe_audio(
            audio_bytes,
            mime_type,
        )

        if not isinstance(result, dict) or not result.get("success"):
            logger.warning(
                "[Telegram][Voice] Transcription unavailable: %s",
                (
                    result.get("summary")
                    if isinstance(result, dict)
                    else "unknown error"
                ),
            )
            return None

        transcript = str(
            result.get("transcript") or ""
        ).strip()

        if transcript:
            logger.info(
                "[Telegram][Voice] Voice transcribed successfully | chars=%d",
                len(transcript),
            )
            return transcript

    except Exception:
        logger.exception(
            "[Telegram][Voice] Voice transcription failed."
        )

    return None


async def _handle_master_architecture_command(
    *,
    registry,
    user_id,
    text: str,
) -> dict[str, Any] | None:
    """Handle the Master-only, read-only architecture inspection command."""

    normalized = (text or "").strip().lower()

    if normalized not in {
        "/master architecture",
        "/master  architecture",
        "master architecture",
        "master, architecture",
        "/master arch",
        "/master  arch",
    }:
        return None

    allowed = os.getenv(
        "ALLOWED_TELEGRAM_USER_ID",
        "",
    ).strip()

    if not allowed or str(user_id) != allowed:
        logger.warning(
            "[Phase1][TelegramArchitecture] Unauthorized request | user_id=%s",
            user_id,
        )
        return {
            "handled": True,
            "success": False,
            "text": (
                "Architecture inspection is available only to "
                "the authorized Master account."
            ),
        }

    architecture = registry.get(
        "architecture_intelligence"
    )

    if architecture is None:
        return {
            "handled": True,
            "success": False,
            "text": (
                "Architecture Intelligence is not registered. "
                "Step 2 integration is incomplete."
            ),
        }

    try:
        snapshot = await asyncio.to_thread(
            architecture.inspect,
            Path.cwd(),
        )
        data = snapshot.to_dict()

        repository = data.get("repository") or {}
        components = data.get("components") or []
        roles = data.get("module_roles") or {}
        impact = data.get("change_impact") or {}
        warnings = data.get("architecture_warnings") or []
        errors = data.get("analysis_errors") or []
        protected = data.get("protected_areas") or []
        languages = repository.get("languages") or []
        if isinstance(languages, dict):
            language_items = list(languages.items())
        else:
            language_items = [(str(language), 1) for language in languages]
        entry_points = repository.get("entry_points") or []

        component_names: list[str] = []
        for component in components[:12]:
            if isinstance(component, dict):
                name = str(
                    component.get("name") or ""
                ).strip()
                if name:
                    component_names.append(name)

        impacted = sorted(
            impact.items(),
            key=lambda item: len(item[1] or []),
            reverse=True,
        )[:5]

        lines = [
            "🏗️ ARIA Architecture Report",
            "",
            f"Project type: {repository.get('project_type', 'unknown')}",
            f"Files: {repository.get('total_files', 0)}",
            f"Directories: {repository.get('total_directories', 0)}",
            f"Python modules: {len(repository.get('python_modules') or [])}",
            f"Architecture components: {len(components)}",
            f"Module roles: {len(roles)}",
            f"Change-impact entries: {len(impact)}",
            f"Protected areas: {len(protected)}",
            "",
            "Languages:",
        ]

        if language_items:
            for name, count in sorted(
                language_items,
                key=lambda item: str(item[0]).lower(),
            )[:12]:
                lines.append(
                    f"• {name}: {count}"
                )
        else:
            lines.append("• None detected")

        lines.extend(["", "Entry points:"])
        if entry_points:
            lines.extend(
                f"• {entry}"
                for entry in entry_points[:10]
            )
        else:
            lines.append("• None detected")

        lines.extend(["", "Major components:"])
        if component_names:
            lines.extend(
                f"• {name}"
                for name in component_names
            )
        else:
            lines.append("• None detected")

        lines.extend(["", "Highest-impact modules:"])
        if impacted:
            for module_name, affected in impacted:
                lines.append(
                    f"• {module_name}: {len(affected or [])} affected"
                )
        else:
            lines.append("• None detected")

        lines.extend(["", "Architecture warnings:"])
        if warnings:
            lines.extend(
                f"• {warning}"
                for warning in warnings[:8]
            )
        else:
            lines.append("• None")

        lines.extend(["", "Analysis errors:"])
        if errors:
            lines.extend(
                f"• {error}"
                for error in errors[:8]
            )
        else:
            lines.append("• None")

        lines.extend([
            "",
            "Mode: READ-ONLY. No files were modified, executed, deployed, or pushed.",
        ])

        return {
            "handled": True,
            "success": True,
            "text": "\n".join(lines),
            "architecture": data,
        }

    except Exception as exc:
        logger.exception(
            "[Phase1][TelegramArchitecture] Architecture inspection failed."
        )
        return {
            "handled": True,
            "success": False,
            "text": (
                "Architecture inspection failed safely.\n"
                f"Reason: {exc}"
            ),
        }


async def _handle_master_requirement_command(
    *,
    registry,
    user_id,
    text: str,
) -> dict[str, Any] | None:
    """Handle Master-only Phase 1 Requirement Intelligence inspection."""

    normalized = (text or "").strip().lower()

    if normalized not in {
        "/master requirement",
        "/master  requirement",
        "master requirement",
        "master, requirement",
        "/master req",
        "/master  req",
    }:
        return None

    allowed = os.getenv(
        "ALLOWED_TELEGRAM_USER_ID",
        "",
    ).strip()

    if not allowed or str(user_id) != allowed:
        logger.warning(
            "[Phase1][TelegramRequirement] Unauthorized request | user_id=%s",
            user_id,
        )
        return {
            "handled": True,
            "success": False,
            "text": (
                "Requirement Intelligence is available only to "
                "the authorized Master account."
            ),
        }

    intelligence = registry.get(
        "requirement_intelligence"
    )

    if intelligence is None:
        return {
            "handled": True,
            "success": False,
            "text": (
                "Requirement Intelligence is not registered. "
                "Step 3 integration is incomplete."
            ),
        }

    # The command itself needs a requirement payload. Keep this command
    # read-only and useful by supporting an optional payload after the
    # command, e.g. /master requirement Create a new API endpoint.
    prefixes = (
        "/master requirement",
        "/master  requirement",
        "master requirement",
        "master, requirement",
        "/master req",
        "/master  req",
    )

    requirement_text = ""
    original = (text or "").strip()
    lower_original = original.lower()
    for prefix in prefixes:
        if lower_original.startswith(prefix):
            requirement_text = original[len(prefix):].lstrip(" :,-").strip()
            break

    if not requirement_text:
        return {
            "handled": True,
            "success": False,
            "text": (
                "Usage: /master requirement <development requirement>\n\n"
                "Example: /master requirement Create a new file "
                "aria_test.txt containing exactly ARIA self-development test successful. "
                "Do not modify existing files."
            ),
        }

    try:
        analysis = await asyncio.to_thread(
            intelligence.analyze,
            requirement_text,
        )
        data = analysis.to_dict()
        requirement = data.get("requirement") or {}

        lines = [
            "🧠 <b>ARIA Requirement Intelligence</b>",
            "",
            f"<b>Intent:</b> {html.escape(str(data.get('intent', 'unknown')))}",
            f"<b>Primary action:</b> {html.escape(str(data.get('primary_action', 'unknown')))}",
            f"<b>Scope:</b> {html.escape(str(data.get('scope', 'unspecified')))}",
            f"<b>Confidence:</b> {float(data.get('confidence', 0.0)):.3f}",
            f"<b>Ready for planning:</b> {'YES' if data.get('ready_for_planning') else 'NO'}",
            f"<b>Requires approval:</b> {'YES' if requirement.get('requires_approval') else 'NO'}",
            "",
            "<b>Goals:</b>",
        ]

        goals = requirement.get("goals") or []
        lines.extend(f"• {html.escape(str(item))}" for item in goals[:8])
        if not goals:
            lines.append("• None detected")

        lines.append("<b>Requested files:</b>")
        files = requirement.get("requested_files") or []
        lines.extend(f"• <code>{html.escape(str(item))}</code>" for item in files[:12])
        if not files:
            lines.append("• None detected")

        lines.append("<b>Dependencies:</b>")
        dependencies = data.get("dependencies") or []
        lines.append("• " + (", ".join(html.escape(str(x)) for x in dependencies) if dependencies else "None detected"))

        lines.append("<b>Ambiguity:</b>")
        ambiguity = data.get("ambiguity_flags") or []
        lines.extend(f"• {html.escape(str(item))}" for item in ambiguity[:8])
        if not ambiguity:
            lines.append("• None detected")

        questions = data.get("clarification_questions") or []
        if questions:
            lines.append("<b>Clarification:</b>")
            lines.extend(f"• {html.escape(str(item))}" for item in questions[:5])

        lines.append(
            "\n<i>Read-only analysis. No files were changed, executed, deployed, or pushed.</i>"
        )

        return {
            "handled": True,
            "success": True,
            "text": "\n".join(lines),
            "analysis": data,
        }

    except Exception as exc:
        logger.exception(
            "[Phase1][TelegramRequirement] Requirement analysis failed."
        )
        return {
            "handled": True,
            "success": False,
            "text": f"Requirement analysis failed safely: {exc}",
        }


async def _handle_master_development_command(
    *,
    registry,
    user_id,
    text: str,
) -> dict[str, Any] | None:
    phase1_runtime = registry.get(
        "phase1_runtime"
    )

    if phase1_runtime is not None:
        interface = TelegramAutonomousEngineeringInterface(
            phase1_runtime
        )
        return await interface.handle(
            user_id=user_id,
            text=text,
        )

    controller = registry.get(
        "development_controller"
    )

    if controller is None:
        return {
            "handled": True,
            "success": False,
            "text": (
                "Self-development is not available because "
                "neither Phase 1 runtime nor DevelopmentController "
                "is registered."
            ),
        }

    interface = TelegramDevelopmentInterface(
        controller
    )

    return await interface.handle(
        user_id=user_id,
        text=text,
    )


async def _handle_master_approval_command(
    *,
    registry,
    user_id,
    text: str,
) -> dict[str, Any] | None:
    approval_interface = registry.get(
        "telegram_approval_interface"
    )

    if approval_interface is None:
        return None

    return await approval_interface.handle(
        user_id=user_id,
        text=text,
    )


# =========================================================
# ACTUAL TELEGRAM PROCESSING
# =========================================================

async def process_telegram_update(
    req: Request,
    data: dict,
    request_id: str,
):
    """
    Process one already-validated Telegram update.

    This function runs in the background.

    It is deliberately separate from /telegram-webhook so
    Telegram receives an immediate acknowledgement.
    """

    status = None

    status_started = False

    chat_id = None

    user_id = None

    token = None

    http_client = None

    try:
        _begin_knowledge_activity(request_id)
    except Exception:
        logger.exception("[KnowledgeHub] Failed to mark active Telegram processing.")

    try:

        registry = req.app.state.registry

        config = registry.get(
            "config"
        )

        token = config.telegram_token

        if not token:

            logger.error(
                "[Telegram] Telegram token is not configured."
            )

            return

        msg = data.get(
            "message",
            {}
        )

        chat_id = (
            msg.get(
                "chat",
                {}
            ).get(
                "id"
            )
        )

        user_id = (
            msg.get(
                "from",
                {}
            ).get(
                "id"
            )
        )

        if chat_id is None or user_id is None:
            return

        http_client = registry.get(
            "http_client"
        )

        # -----------------------------------------------------
        # VOICE / AUDIO → TEXT
        # -----------------------------------------------------
        #
        # Voice is normalized into the same text pipeline used by
        # typed commands. This means "Master, develop ..." spoken
        # through Telegram can invoke the same Master-only
        # development interface as the typed command.
        #
        text = msg.get(
            "text",
            ""
        ).strip()

        if not text and (
            msg.get("voice")
            or msg.get("audio")
        ):
            transcribed = await _transcribe_telegram_voice(
                http_client=http_client,
                token=token,
                message=msg,
            )

            if transcribed:
                text = transcribed
                logger.info(
                    "[Telegram] Voice normalized to text: %r",
                    text,
                )
            else:
                await http_client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": (
                            "I couldn't transcribe that voice message. "
                            "Please try again."
                        ),
                    },
                )
                return


        # -----------------------------------------------------
        # TELEGRAM STATUS MESSAGE
        # -----------------------------------------------------

        status = TelegramStatus(
            http_client=http_client,
            token=token,
            chat_id=chat_id,
        )

        await status.start(
            get_telegram_status_message(
                text
            )
        )

        status_started = True

        # -----------------------------------------------------
        # MASTER APPROVAL / CONTINUATION COMMAND
        # -----------------------------------------------------

        approval_result = await _handle_master_approval_command(
            registry=registry,
            user_id=user_id,
            text=text,
        )

        if approval_result is not None:
            await safe_delete_status(status)

            await http_client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": approval_result.get(
                        "text",
                        "Approval request processed.",
                    ),
                    "parse_mode": "HTML",
                },
            )

            return approval_result

        # -----------------------------------------------------
        # MASTER ARCHITECTURE COMMAND
        # -----------------------------------------------------
        #
        # Read-only architecture inspection is handled before the
        # development pipeline. Voice and text both arrive here as text.
        #
        architecture_result = await _handle_master_architecture_command(
            registry=registry,
            user_id=user_id,
            text=text,
        )

        if architecture_result is not None:
            await safe_delete_status(status)

            await http_client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": architecture_result.get(
                        "text",
                        "Architecture inspection completed.",
                    ),
                },
            )

            return architecture_result

        # -----------------------------------------------------
        # MASTER REQUIREMENT INTELLIGENCE COMMAND
        # -----------------------------------------------------

        requirement_result = await _handle_master_requirement_command(
            registry=registry,
            user_id=user_id,
            text=text,
        )

        if requirement_result is not None:
            await safe_delete_status(status)

            await http_client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": requirement_result.get(
                        "text",
                        "Requirement analysis completed.",
                    ),
                    "parse_mode": "HTML",
                },
            )

            return requirement_result

        # -----------------------------------------------------
        # MASTER DEVELOPMENT COMMAND
        # -----------------------------------------------------
        #
        # This is checked before the normal cognitive pipeline so
        # development requests cannot accidentally become ordinary
        # chat requests. Voice and text both arrive here as text.
        #
        development_result = await _handle_master_development_command(
            registry=registry,
            user_id=user_id,
            text=text,
        )

        if development_result is not None:
            await safe_delete_status(status)

            await http_client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": development_result.get(
                        "text",
                        "Development request processed.",
                    ),
                },
            )

            return development_result

        # -----------------------------------------------------
        # HANDLE PENDING DOCUMENT CONFIRMATION
        # -----------------------------------------------------

        confirmation_key = str(
            user_id
        )

        if confirmation_key in pending_document_actions:

            pending = pending_document_actions[
                confirmation_key
            ]

            answer = text.lower().strip()

            # =================================================
            # USER SELECTING A DOCUMENT
            # =================================================

            if pending.get(
                "action"
            ) == "select_document":

                cancel_phrases = {
                    "cancel",
                    "cancel it",
                    "leave it",
                    "leave",
                    "never mind",
                    "nevermind",
                    "forget it",
                    "stop",
                    "no",
                    "no thanks",
                    "no thank you",
                }

                if answer in cancel_phrases:

                    pending_document_actions.pop(
                        confirmation_key,
                        None,
                    )

                    await safe_delete_status(
                        status
                    )

                    await http_client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": (
                                "Alright. Document selection "
                                "cancelled."
                            ),
                        },
                    )

                    return {
                        "status": (
                            "document_selection_cancelled"
                        )
                    }

                documents = pending.get(
                    "documents",
                    []
                )

                ignored_words = {
                    "pdf",
                    "document",
                    "file",
                    "the",
                    "my",
                    "one",
                    "give",
                    "send",
                    "me",
                    "please",
                }

                query_words = {
                    word
                    for word in (
                        answer
                        .replace(
                            ".pdf",
                            ""
                        )
                        .replace(
                            "_",
                            " "
                        )
                        .replace(
                            "-",
                            " "
                        )
                        .split()
                    )
                    if word not in ignored_words
                }

                best_document = None

                best_score = 0

                for document in documents:

                    filename = str(
                        document.get(
                            "filename",
                            ""
                        )
                    )

                    filename_words = {
                        word
                        for word in (
                            filename
                            .lower()
                            .replace(
                                ".pdf",
                                ""
                            )
                            .replace(
                                "_",
                                " "
                            )
                            .replace(
                                "-",
                                " "
                            )
                            .split()
                        )
                        if word not in ignored_words
                    }

                    score = len(
                        query_words.intersection(
                            filename_words
                        )
                    )

                    if score > best_score:

                        best_score = score

                        best_document = document

                if (
                    best_document
                    and best_score > 0
                ):

                    telegram_file_id = (
                        best_document.get(
                            "telegram_file_id"
                        )
                    )

                    filename = (
                        best_document.get(
                            "filename",
                            "document.pdf",
                        )
                    )

                    if telegram_file_id:

                        await safe_delete_status(
                            status
                        )

                        telegram_response = (
                            await http_client.post(
                                f"https://api.telegram.org/bot{token}/sendDocument",
                                json={
                                    "chat_id": chat_id,
                                    "document": telegram_file_id,
                                    "caption": filename,
                                },
                            )
                        )

                        if telegram_response.is_success:

                            pending_document_actions.pop(
                                confirmation_key,
                                None,
                            )

                            return {
                                "status": "document_sent"
                            }

                filenames = [
                    document.get(
                        "filename",
                        "Unnamed document",
                    )
                    for document in documents
                ]

                await safe_delete_status(
                    status
                )

                await http_client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": (
                            "I couldn't identify which "
                            "document you meant. "
                            "Please choose one of these:\n\n"
                            + "\n".join(
                                f"• {name}"
                                for name in filenames
                            )
                        ),
                    },
                )

                return {
                    "status": (
                        "document_selection_required"
                    )
                }

            # =================================================
            # CANCEL PENDING OPERATION
            # =================================================

            if answer in (
                "no",
                "n",
                "cancel",
                "stop",
                "don't",
                "dont",
            ):

                pending_document_actions.pop(
                    confirmation_key,
                    None,
                )

                await safe_delete_status(
                    status
                )

                await http_client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": "Cancelled.",
                    },
                )

                return {
                    "status": (
                        "document_action_cancelled"
                    )
                }

            # =================================================
            # CONFIRM PENDING OPERATION
            # =================================================

            if answer in (
                "yes",
                "y",
                "confirm",
                "yes delete",
                "delete it",
                "do it",
            ):

                document_repository = (
                    registry.get(
                        "document_repository"
                    )
                )

                action = pending.get(
                    "action"
                )

                if action == "delete_document":

                    document_id = pending.get(
                        "document_id"
                    )

                    filename = pending.get(
                        "filename",
                        "document",
                    )

                    deleted = (
                        await document_repository.delete_document(
                            document_id=document_id,
                            user_id=str(user_id),
                        )
                    )

                    pending_document_actions.pop(
                        confirmation_key,
                        None,
                    )

                    message = (
                        f"Deleted {filename}."
                        if deleted
                        else (
                            "I couldn't delete "
                            "that document."
                        )
                    )

                    await safe_delete_status(
                        status
                    )

                    await http_client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": message,
                        },
                    )

                    return {
                        "status": (
                            "document_deleted"
                            if deleted
                            else "document_delete_failed"
                        )
                    }

                if action == "delete_all_documents":

                    deleted_count = (
                        await document_repository
                        .delete_all_user_documents(
                            user_id=str(user_id)
                        )
                    )

                    pending_document_actions.pop(
                        confirmation_key,
                        None,
                    )

                    await safe_delete_status(
                        status
                    )

                    await http_client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": (
                                f"Deleted {deleted_count} "
                                f"stored document(s)."
                            ),
                        },
                    )

                    return {
                        "status": (
                            "all_documents_deleted"
                        )
                    }

        # =====================================================
        # DOCUMENT UPLOAD
        # =====================================================

        if "document" in msg:

            await status.update(
                "Checking the uploaded document..."
            )

            document = msg[
                "document"
            ]

            file_id = document[
                "file_id"
            ]

            # -------------------------------------------------
            # GET TELEGRAM FILE INFORMATION
            # -------------------------------------------------

            file_info = await http_client.get(
                f"https://api.telegram.org/bot{token}/getFile",
                params={
                    "file_id": file_id
                },
            )

            file_info.raise_for_status()

            file_info_json = file_info.json()

            file_path = (
                file_info_json
                .get(
                    "result",
                    {}
                )
                .get(
                    "file_path"
                )
            )

            if not file_path:

                raise RuntimeError(
                    "Telegram did not return a file path."
                )

            download_url = (
                "https://api.telegram.org/"
                f"file/bot{token}/{file_path}"
            )

            os.makedirs(
                "uploads",
                exist_ok=True,
            )

            original_filename = document.get(
                "file_name"
            )

            if original_filename:

                safe_filename = os.path.basename(
                    original_filename
                )

            else:

                safe_filename = os.path.basename(
                    file_path
                )

            local_path = os.path.join(
                "uploads",
                safe_filename,
            )

            response = await http_client.get(
                download_url
            )

            response.raise_for_status()

            with open(
                local_path,
                "wb",
            ) as f:

                f.write(
                    response.content
                )

            document_ai = (
                registry.get(
                    "document_intelligence"
                )
            )

            session_id = str(
                chat_id
            )

            original_filename = (
                document.get(
                    "file_name"
                )
                or Path(
                    local_path
                ).name
            )

            await status.update(
                "Processing the document..."
            )

            # -------------------------------------------------
            # DOCUMENT PROCESSING TIMEOUT
            # -------------------------------------------------

            result = await asyncio.wait_for(
                document_ai.process_document(
                    file_path=local_path,
                    session_id=session_id,
                    document_name=original_filename,
                ),
                timeout=TELEGRAM_PROCESS_TIMEOUT_SECONDS,
            )

            # -------------------------------------------------
            # PERSIST DOCUMENT METADATA
            # -------------------------------------------------

            if registry.has(
                "document_repository"
            ):

                document_repository = (
                    registry.get(
                        "document_repository"
                    )
                )

                try:

                    saved_document = (
                        await document_repository.save_document(
                            user_id=str(user_id),
                            filename=safe_filename,
                            telegram_file_id=document.get(
                                "file_id"
                            ),
                            telegram_file_unique_id=document.get(
                                "file_unique_id"
                            ),
                            mime_type=document.get(
                                "mime_type"
                            ),
                            size=document.get(
                                "file_size"
                            ),
                            summary=result.get(
                                "summary"
                            ),
                            text_preview=result.get(
                                "text_preview"
                            ),
                            vector_ids=result.get(
                                "vector_ids",
                                [],
                            ),
                            metadata={
                                "source": "telegram",
                                "chat_id": str(chat_id),
                                "session_id": session_id,
                            },
                        )
                    )

                    logger.info(
                        "[Telegram] Document catalogue entry saved: %s",
                        saved_document.get(
                            "document_id"
                        ),
                    )

                except Exception:

                    logger.exception(
                        "[Telegram] Failed to persist "
                        "document metadata."
                    )

            state_manager = (
                registry.get(
                    "state_manager"
                )
            )

            if state_manager:

                doc_name = (
                    document.get(
                        "file_name"
                    )
                    or Path(
                        local_path
                    ).name
                )

                state_manager.update_state(
                    session_id,
                    active_document=True,
                    document_uploaded=True,
                    current_document=doc_name,
                    current_document_summary=result[
                        "summary"
                    ],
                    last_document_question=None,
                    last_document_answer=None,
                )

            logger.info(
                "[Telegram] Document processed and stored "
                "for session %s. Waiting for user instruction.",
                session_id,
            )

            await safe_delete_status(
                status
            )

            return {
                "status": "processed",
                "document_ready": True,
            }

        # =====================================================
        # NORMAL TEXT REQUEST
        # =====================================================

        await status.update(
            "Working on your request..."
        )

        logger.info(
            "[Telegram] Starting cognitive request | "
            "request_id=%s | chat_id=%s | timeout=%ss",
            request_id,
            chat_id,
            TELEGRAM_PROCESS_TIMEOUT_SECONDS,
        )

        try:

            result = await asyncio.wait_for(
                process_task(
                    text,
                    str(chat_id),
                    request_id,
                    req.app.state,
                ),
                timeout=TELEGRAM_PROCESS_TIMEOUT_SECONDS,
            )

        except asyncio.TimeoutError:

            logger.error(
                "[Telegram] Request timed out after %.1f seconds | "
                "request_id=%s | query=%r",
                TELEGRAM_PROCESS_TIMEOUT_SECONDS,
                request_id,
                text,
            )

            await safe_delete_status(
                status
            )

            timeout_message = (
                "I couldn't complete that request within the "
                "allowed processing time. The operation was stopped "
                "instead of continuing indefinitely."
            )

            await http_client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": timeout_message,
                },
            )

            return {
                "status": "processing_timeout",
                "request_id": request_id,
            }

        except asyncio.CancelledError:

            logger.warning(
                "[Telegram] Request cancelled | "
                "request_id=%s",
                request_id,
            )

            raise

        except Exception as exc:

            logger.exception(
                "[Telegram] Cognitive request failed | "
                "request_id=%s | error=%s",
                request_id,
                exc,
            )

            await safe_delete_status(
                status
            )

            await http_client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": (
                        "I ran into an internal problem while "
                        "processing that request. The stuck operation "
                        "has been stopped."
                    ),
                },
            )

            return {
                "status": "processing_failed",
                "request_id": request_id,
            }

        # =====================================================
        # STRUCTURED DOCUMENT ACTION
        # =====================================================

        if isinstance(
            result,
            SystemResponse,
        ):

            response_data = (
                result.data
                if isinstance(
                    result.data,
                    dict,
                )
                else {}
            )

            document_action = (
                response_data.get(
                    "document_action"
                )
            )

            # -------------------------------------------------
            # SEND STORED DOCUMENT
            # -------------------------------------------------

            if document_action == "send_document":

                documents = (
                    response_data.get(
                        "documents",
                        [],
                    )
                )

                query = str(
                    response_data.get(
                        "query",
                        text,
                    )
                ).lower()

                if not documents:

                    await safe_delete_status(
                        status
                    )

                    await http_client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": (
                                "I couldn't find "
                                "that document."
                            ),
                        },
                    )

                    return {
                        "status": (
                            "document_not_found"
                        )
                    }

                best_document = None

                best_score = -1

                ignored_words = {
                    "pdf",
                    "document",
                    "file",
                    "give",
                    "send",
                    "get",
                    "return",
                    "download",
                    "share",
                    "show",
                    "me",
                    "my",
                    "the",
                    "a",
                    "an",
                    "please",
                    "now",
                }

                for document in documents:

                    filename = str(
                        document.get(
                            "filename",
                            "",
                        )
                    )

                    normalized_filename = (
                        filename
                        .lower()
                        .replace(
                            ".pdf",
                            "",
                        )
                        .replace(
                            "_",
                            " ",
                        )
                        .replace(
                            "-",
                            " ",
                        )
                    )

                    filename_words = {
                        word
                        for word in (
                            normalized_filename.split()
                        )
                        if word not in ignored_words
                    }

                    score = sum(
                        1
                        for word in filename_words
                        if word in query
                    )

                    if score > best_score:

                        best_score = score

                        best_document = document

                # -------------------------------------------------
                # MULTIPLE DOCUMENTS WITH NO CLEAR MATCH
                # -------------------------------------------------

                if (
                    len(documents) > 1
                    and best_score <= 0
                ):

                    filenames = [
                        document.get(
                            "filename",
                            "Unnamed document",
                        )
                        for document in documents
                    ]

                    pending_document_actions[
                        str(user_id)
                    ] = {
                        "action": "select_document",
                        "documents": documents,
                    }

                    await safe_delete_status(
                        status
                    )

                    await http_client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": (
                                "I found multiple documents. "
                                "Which one would you like?\n\n"
                                + "\n".join(
                                    f"• {name}"
                                    for name in filenames
                                )
                            ),
                        },
                    )

                    return {
                        "status": (
                            "document_selection_required"
                        )
                    }

                if not best_document:

                    await safe_delete_status(
                        status
                    )

                    await http_client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": (
                                "I couldn't identify "
                                "the requested document."
                            ),
                        },
                    )

                    return {
                        "status": (
                            "document_not_found"
                        )
                    }

                telegram_file_id = (
                    best_document.get(
                        "telegram_file_id"
                    )
                )

                filename = (
                    best_document.get(
                        "filename",
                        "document.pdf",
                    )
                )

                if not telegram_file_id:

                    logger.warning(
                        "[Telegram] Stored document '%s' "
                        "has no telegram_file_id.",
                        filename,
                    )

                    await safe_delete_status(
                        status
                    )

                    await http_client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": (
                                "I found the document record, "
                                "but its original Telegram file "
                                "reference is unavailable."
                            ),
                        },
                    )

                    return {
                        "status": (
                            "document_file_unavailable"
                        )
                    }

                await safe_delete_status(
                    status
                )

                telegram_response = (
                    await http_client.post(
                        f"https://api.telegram.org/bot{token}/sendDocument",
                        json={
                            "chat_id": chat_id,
                            "document": telegram_file_id,
                            "caption": filename,
                        },
                    )
                )

                if telegram_response.is_success:

                    logger.info(
                        "[Telegram] Sent stored document '%s'.",
                        filename,
                    )

                    return {
                        "status": "document_sent"
                    }

                logger.error(
                    "[Telegram] Failed to send stored document "
                    "'%s': %s",
                    filename,
                    telegram_response.text,
                )

                await http_client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": (
                            "I found the document, but Telegram "
                            "couldn't send it."
                        ),
                    },
                )

                return {
                    "status": (
                        "document_send_failed"
                    )
                }

        # =====================================================
        # NORMAL TEXT RESPONSE
        # =====================================================

        await status.update(
            "Finishing the response..."
        )

        reply_text = str(result)

        asks_for_source = bool(re.search(
            r"\b(?:source\s+urls?|urls?\s+of\s+(?:the\s+)?sources?|provide\s+(?:the\s+)?sources?|give\s+(?:me\s+)?(?:the\s+)?sources?)\b",
            text or "",
            flags=re.IGNORECASE,
        ))
        # Split the raw response BEFORE Markdown-to-HTML conversion. Splitting
        # already-generated HTML can cut a tag in half and make Telegram reject
        # the entire chunk with a parse-entity error.
        visible_reply = reply_text if asks_for_source else hide_source_references(reply_text)
        visible_reply = format_plain_text(visible_reply)
        logger.info(
            "[Telegram] Final reply prepared (chars=%d, source_links_requested=%s)",
            len(visible_reply),
            asks_for_source,
        )

        await safe_delete_status(status)

        telegram_response = None
        response_parts = split_telegram_text(visible_reply, limit=3600)
        for part_index, response_part in enumerate(response_parts, start=1):
            formatted_part = markdown_to_telegram_html(response_part)
            telegram_response = await http_client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": formatted_part,
                    "parse_mode": "HTML",
                },
            )
            if not telegram_response.is_success:
                logger.error(
                    "[Telegram] Failed to send response part %d/%d (HTTP %s).",
                    part_index,
                    len(response_parts),
                    getattr(telegram_response, "status_code", "unknown"),
                )
                break

        # -----------------------------------------------------
        # SAVE COMPLETED CONVERSATION TURN
        # -----------------------------------------------------

        if telegram_response.is_success:

            state_manager = (
                registry.get(
                    "state_manager"
                )
            )

            if state_manager:

                state_manager.update_state(
                    str(chat_id),
                    last_query=text,
                    last_assistant_response=reply_text,
                )

                state_manager.add_conversation_turn(
                    session_id=str(chat_id),
                    user_message=text,
                    assistant_message=reply_text,
                )

                logger.info(
                    "[Conversation] Stored completed turn "
                    "for session %s.",
                    chat_id,
                )

        return {
            "status": "ok"
        }

    # =========================================================
    # UNEXPECTED BACKGROUND FAILURE
    # =========================================================

    except asyncio.CancelledError:

        logger.warning(
            "[Telegram] Background update cancelled | "
            "request_id=%s",
            request_id,
        )

        raise

    except Exception as exc:

        logger.exception(
            "[Telegram] Unhandled background update failure | "
            "request_id=%s | error=%s",
            request_id,
            exc,
        )

        try:

            if status is not None:

                await safe_delete_status(
                    status
                )

            if (
                http_client is not None
                and token
                and chat_id is not None
            ):

                await http_client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": (
                            "I ran into an internal problem while "
                            "processing that request. The operation "
                            "has been stopped."
                        ),
                    },
                )

        except Exception:

            logger.exception(
                "[Telegram] Failed to send background "
                "failure response | request_id=%s",
                request_id,
            )

    finally:

        try:
            _end_knowledge_activity(request_id)
        except Exception:
            logger.exception("[KnowledgeHub] Failed to clear active Telegram processing marker.")

        if (
            status_started
            and status is not None
        ):

            await safe_delete_status(
                status
            )


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
async def health():
    """Liveness probe: confirms the HTTP process can answer requests.

    Use /ready for dependency registration/readiness. Keeping liveness separate
    prevents a dependency outage from causing an orchestrator restart loop.
    """
    return {
        "status": "healthy",
        "live": True,
        "version": "12.0.0",
    }


@app.get("/ready")
async def readiness(req: Request):
    """Readiness probe: reports whether ARIA's core request services are present."""
    from fastapi.responses import JSONResponse

    registry = getattr(req.app.state, "registry", None)
    if registry is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "ready": False,
                "reason": "Application service registry has not been initialized.",
                "version": "12.0.0",
            },
        )

    if not registry.has("health_checker"):
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "ready": False,
                "reason": "Health checker is not registered.",
                "version": "12.0.0",
            },
        )

    try:
        checker = registry.get("health_checker")
        result = await checker.check_readiness()
        result["version"] = "12.0.0"
        result["subsystems"] = {
            name: registry.has(name)
            for name in (
                "memory_engine",
                "skill_manager",
                "action_manager",
                "plugin_manager",
                "scheduler",
                "http_client",
            )
        }
        result["plugins_loaded"] = (
            list(registry.get("plugin_manager").plugins.keys())
            if registry.has("plugin_manager")
            else []
        )
        if not result.get("ready", False):
            return JSONResponse(status_code=503, content=result)
        return result
    except Exception:
        logger.exception("ARIA readiness check failed")
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "ready": False,
                "reason": "Readiness check raised an internal error.",
                "version": "12.0.0",
            },
        )


# =========================================================
# ROOT
# =========================================================

@app.get("/")
async def root():

    return {
        "system": "ARIA AI Operating Platform",
        "status": "operational",
        "version": "12.0.0",
    }


# =========================================================
# OWNER LOGIN
# =========================================================

@app.post("/app/login", response_model=OwnerLoginResponse)
async def app_owner_login(credentials: OwnerLoginRequest, request: Request):
    expected_id = os.getenv(OWNER_ID_ENV, "").strip()
    initial_password = os.getenv(OWNER_SECRET_ENV, "")
    token_secret = os.getenv(TOKEN_SECRET_ENV, "")
    device_id = str(credentials.device_id).strip()
    if not expected_id or not initial_password or len(token_secret) < 32:
        return JSONResponse(status_code=503, content={"detail": "Private ARIA sign-in is not configured. Set the owner ID, initial app password, and a 32+ character token-signing secret."})
    if not device_id or len(device_id) > 128:
        return JSONResponse(status_code=400, content={"detail": "A valid device identifier is required."})
    if not hmac.compare_digest(str(credentials.telegram_id).strip(), expected_id):
        return JSONResponse(status_code=401, content={"detail": "Invalid owner credentials."})
    collection = _security_collection(request)
    if collection is None:
        return JSONResponse(status_code=503, content={"detail": "Persistent security storage is required. Configure MONGODB_URI and redeploy."})
    try:
        record = await collection.find_one({"_id": expected_id})
        if record and record.get("password_hash"):
            valid = _password_matches(str(credentials.secret), record)
        else:
            # First sign-in bootstraps a persistent scrypt hash from the Render secret.
            valid = hmac.compare_digest(str(credentials.secret), initial_password)
            if valid:
                salt, digest = _password_hash(str(credentials.secret))
                await collection.update_one({"_id": expected_id}, {"$set": {
                    "password_salt": salt, "password_hash": digest,
                    "token_version": int((record or {}).get("token_version", 1)),
                    "created_at": int((record or {}).get("created_at", time.time())),
                }}, upsert=True)
                record = await collection.find_one({"_id": expected_id})
        if not valid:
            return JSONResponse(status_code=401, content={"detail": "Invalid owner credentials."})
        record = record or await collection.find_one({"_id": expected_id}) or {"token_version": 1}
        version = int(record.get("token_version", 1))
        token = _make_owner_token(expected_id, device_id, version)
        # Record active device metadata without storing the bearer token itself.
        await collection.update_one({"_id": expected_id}, {"$set": {f"devices.{hashlib.sha256(device_id.encode()).hexdigest()[:32]}": {
            "device_id": device_id, "last_sign_in": int(time.time())
        }}}, upsert=True)
        return OwnerLoginResponse(access_token=token)
    except Exception:
        logger.exception("ARIA owner sign-in failed due to persistent security storage error")
        return JSONResponse(status_code=503, content={"detail": "Could not complete secure sign-in. Check database connectivity."})


@app.post("/app/change-password")
async def app_change_password(payload: ChangePasswordRequest, request: Request):
    owner_id = os.getenv(OWNER_ID_ENV, "").strip()
    collection = _security_collection(request)
    if not owner_id or collection is None:
        return JSONResponse(status_code=503, content={"detail": "Persistent private-app security storage is unavailable."})
    current = str(payload.current_password)
    new = str(payload.new_password)
    if not current or not new:
        return JSONResponse(status_code=400, content={"detail": "Current and new passwords are required."})
    if len(new) > 1024:
        return JSONResponse(status_code=400, content={"detail": "New password is too long."})
    try:
        record = await collection.find_one({"_id": owner_id})
        if not record or not _password_matches(current, record):
            return JSONResponse(status_code=401, content={"detail": "Current password is incorrect."})
        salt, digest = _password_hash(new)
        await collection.update_one({"_id": owner_id}, {"$set": {
            "password_salt": salt,
            "password_hash": digest,
            "token_version": int(record.get("token_version", 1)) + 1,
            "password_changed_at": int(time.time()),
        }})
        return {"success": True, "message": "Password changed. Sign in again on your devices."}
    except Exception:
        logger.exception("ARIA owner password change failed")
        return JSONResponse(status_code=503, content={"detail": "Could not save the new password. Try again later."})

# =========================================================
# WEB CHAT
# =========================================================

class ChatRequest(BaseModel):

    message: str

    session_id: str = "web"


class ChatResponse(BaseModel):

    success: bool

    reply: str


@app.get("/app/notifications")
async def app_notifications(request: Request, limit: int = 30, after_id: int | None = None):
    """Return recent owner-scoped ARIA alerts to the signed-in app inbox."""
    registry = getattr(request.app.state, "registry", None)
    if registry is None or not registry.has("alert_manager"):
        return {"success": True, "items": [], "configured": False}
    try:
        manager = registry.get("alert_manager")
        bounded_limit = max(1, min(int(limit), 100))
        items = await asyncio.to_thread(manager.recent_alerts, bounded_limit, after_id)
        return {"success": True, "items": items, "configured": True}
    except Exception:
        logger.exception("Could not load ARIA app notifications")
        return JSONResponse(status_code=503, content={"success": False, "detail": "Notifications are temporarily unavailable."})


@app.post(
    "/chat",
    response_model=ChatResponse,
)
async def web_chat(
    request: ChatRequest,
    req: Request,
):

    request_id = str(
        uuid.uuid4()
    )

    try:

        result = await process_task(
            user_text=request.message,
            session_id=request.session_id,
            request_id=request_id,
            app_state=req.app.state,
        )

        return ChatResponse(
            success=True,
            reply=str(result),
        )

    except asyncio.TimeoutError:

        logger.error(
            "[WEB CHAT] Request timed out | request_id=%s",
            request_id,
        )

        return ChatResponse(
            success=False,
            reply=(
                "The request took too long to complete "
                "and was stopped."
            ),
        )

    except Exception as e:

        logger.exception(
            "[WEB CHAT] Request failed | request_id=%s",
            request_id,
        )

        return ChatResponse(
            success=False,
            reply=f"System Error: {e}",
        )
