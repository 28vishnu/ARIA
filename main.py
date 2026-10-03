import os
import uuid
import asyncio
import logging
import inspect
import html
import re
from typing import Any
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.logging_config import setup_logging
from core.bootstrap import bootstrap_application
from core.dependency_injection import RequestContext
from core.telegram_status import TelegramStatus
from personality.response import SystemResponse
from api.upload import router as upload_router


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

    registry = await bootstrap_application()

    app.state.registry = registry

    app.state.bg_manager = background_manager

    logger.info(
        "[Lifespan] ARIA Platform successfully started."
    )

    yield

    logger.info(
        "[Lifespan] Shutting down resources..."
    )

    await background_manager.shutdown()

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
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="ARIA AI Operating Platform",
    version="12.0.0",
    lifespan=lifespan,
)


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


app.include_router(
    upload_router
)


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

    if conversation_manager:

        resolved_text = (
            conversation_manager.resolve_reference(
                session_id=session_id,
                query=user_text,
            )
        )

    # -----------------------------------------------------
    # BASE CONTEXT
    # -----------------------------------------------------

    base_context = {
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
) -> str:

    return markdown_to_telegram_html(
        text
    )


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

    # ---------------------------------------------------------
    # SCHEDULE ACTUAL PROCESSING
    # ---------------------------------------------------------

    logger.info(
        "[Telegram] Scheduling background processing | "
        "update_id=%s | request_id=%s",
        update_id,
        request_id,
    )

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

        text = msg.get(
            "text",
            ""
        ).strip()

        if chat_id is None or user_id is None:

            return

        http_client = registry.get(
            "http_client"
        )

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

        reply_text = str(
            result
        )

        telegram_text = format_telegram_response(
            reply_text
        )

        logger.info(
            "[Telegram] Final reply text: %r",
            telegram_text,
        )

        await safe_delete_status(
            status
        )

        telegram_response = await http_client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": telegram_text,
                "parse_mode": "HTML",
            },
        )

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
async def health(
    req: Request,
):

    registry = req.app.state.registry

    if not registry.has(
        "health_checker"
    ):

        return {
            "status": "healthy",
            "version": "12.0.0",
            "message": (
                "Health checker not registered."
            ),
        }

    checker = registry.get(
        "health_checker"
    )

    base_health = await checker.check_readiness()

    extended_status = {
        **base_health,
        "subsystems": {
            "memory_engine": registry.has(
                "memory_engine"
            ),
            "skill_manager": registry.has(
                "skill_manager"
            ),
            "action_manager": registry.has(
                "action_manager"
            ),
            "plugin_manager": registry.has(
                "plugin_manager"
            ),
            "scheduler": registry.has(
                "scheduler"
            ),
            "http_client": registry.has(
                "http_client"
            ),
        },
        "plugins_loaded": (
            list(
                registry.get(
                    "plugin_manager"
                ).plugins.keys()
            )
            if registry.has(
                "plugin_manager"
            )
            else []
        ),
        "version": "12.0.0",
    }

    return extended_status


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
# WEB CHAT
# =========================================================

class ChatRequest(BaseModel):

    message: str

    session_id: str = "web"


class ChatResponse(BaseModel):

    success: bool

    reply: str


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