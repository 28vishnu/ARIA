"""Safe, deterministic Telegram response formatting helpers.

These helpers do not send messages or change the meaning of answers.
They split long plain-text responses below Telegram's message limit and
escape untrusted text when an HTML parse mode is explicitly requested.
"""
from __future__ import annotations

import html
from typing import Iterable

TELEGRAM_SAFE_TEXT_LIMIT = 3900  # leaves headroom below Telegram's 4096 limit


def escape_html_text(value: object) -> str:
    """Escape text for Telegram parse_mode='HTML'."""
    return html.escape(str(value), quote=False)


def split_telegram_text(text: object, limit: int = TELEGRAM_SAFE_TEXT_LIMIT) -> list[str]:
    """Split text into ordered chunks, preferring paragraph/line/word boundaries.

    A single unbroken token longer than the limit is split hard. Empty input
    returns one empty string so callers can handle it consistently.
    """
    value = str(text or "")
    if limit < 1 or limit > 4096:
        raise ValueError("limit must be between 1 and 4096")
    if not value:
        return [""]
    if len(value) <= limit:
        return [value]

    chunks: list[str] = []
    remaining = value
    while len(remaining) > limit:
        boundary = max(
            remaining.rfind("\n\n", 0, limit + 1),
            remaining.rfind("\n", 0, limit + 1),
            remaining.rfind(" ", 0, limit + 1),
        )
        # Avoid tiny chunks when the only boundary is very early.
        if boundary < int(limit * 0.5):
            boundary = limit
        else:
            # Keep separators with the preceding chunk when possible.
            if remaining[boundary:boundary + 2] == "\n\n":
                boundary += 2
            else:
                boundary += 1
        chunk = remaining[:boundary].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            boundary = limit
        chunks.append(chunk)
        remaining = remaining[boundary:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def format_plain_text(value: object) -> str:
    """Normalize only outer whitespace; preserve the response's content."""
    return str(value or "").strip()
