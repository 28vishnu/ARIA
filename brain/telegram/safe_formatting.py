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
    """Split text into ordered chunks without dropping or reordering characters.

    Paragraph, line, and word boundaries are preferred. Whitespace separators
    remain in the preceding chunk so ``"".join(chunks)`` equals the input.
    A single unbroken token longer than the limit is split hard.
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
        # Prefer the latest boundary in the allowed window. Include the full
        # separator in the emitted chunk to preserve every original character.
        paragraph = remaining.rfind("\n\n", 0, limit + 1)
        newline = remaining.rfind("\n", 0, limit + 1)
        space = remaining.rfind(" ", 0, limit + 1)
        candidates = [(paragraph, 2), (newline, 1), (space, 1)]
        boundary, separator_length = max(candidates, key=lambda item: item[0] + item[1] if item[0] >= 0 else -1)
        if boundary < int(limit * 0.5):
            cut = limit
        else:
            cut = boundary + separator_length
        if cut <= 0 or cut > limit:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        chunks.append(remaining)
    return chunks


def format_plain_text(value: object) -> str:
    """Normalize only outer whitespace; preserve the response's content."""
    return str(value or "").strip()
