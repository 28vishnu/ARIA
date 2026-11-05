import logging
import sys
import json
import re
from datetime import datetime, timezone


_SECRET_PATTERNS = (
    (re.compile(r"(https?://api\.telegram\.org/(?:file/)?bot)[^/\s?]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [REDACTED]"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization|client_secret)"
            r"(\s*[:=]\s*)([^\s,;&\"']+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,})\b"),
        "[REDACTED]",
    ),
)


def _redact(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = _redact(record.getMessage())
        exception_text = ""
        if record.exc_info:
            exception_text = _redact(self.formatException(record.exc_info))

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "module": record.module,
            "line": record.lineno
        }
        if exception_text:
            log_entry["exception"] = exception_text
        if hasattr(record, "session_id"):
            log_entry["session_id"] = getattr(record, "session_id")
        return json.dumps(log_entry)

def setup_logging(level: str = "INFO"):
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
