"""Deterministic, read-only briefing builder for ARIA integrations.

This module deliberately does not fetch provider data or send messages. Existing
Gmail, Calendar, GitHub and Drive adapters should pass normalized items to
build_briefing(); the caller remains responsible for owner authorization and
Telegram delivery/approval policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

_ALLOWED_SOURCES = {"gmail", "calendar", "github", "drive", "system"}
_MAX_ITEMS = 30
_MAX_TITLE = 180
_MAX_DETAIL = 360


@dataclass(frozen=True)
class BriefingItem:
    source: str
    title: str
    detail: str = ""
    priority: str = "normal"
    occurred_at: str | None = None
    url: str | None = None


def _clean(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    # Avoid control characters and unbounded content in notifications.
    value = " ".join("".join(ch if ch >= " " or ch in "\t\n\r" else " " for ch in value).split())
    return value[:limit]


def _normalize(raw: Mapping[str, Any]) -> BriefingItem | None:
    source = _clean(raw.get("source"), 20).lower()
    title = _clean(raw.get("title"), _MAX_TITLE)
    if source not in _ALLOWED_SOURCES or not title:
        return None
    priority = _clean(raw.get("priority", "normal"), 20).lower()
    if priority not in {"urgent", "high", "normal", "low"}:
        priority = "normal"
    occurred_at = _clean(raw.get("occurred_at"), 40) or None
    url = _clean(raw.get("url"), 500) or None
    # Only permit conventional web links; never render arbitrary schemes.
    if url and not url.startswith(("https://", "http://")):
        url = None
    return BriefingItem(
        source=source,
        title=title,
        detail=_clean(raw.get("detail", ""), _MAX_DETAIL),
        priority=priority,
        occurred_at=occurred_at,
        url=url,
    )


def build_briefing(
    items: Iterable[Mapping[str, Any]],
    *,
    period: str = "daily",
    now: datetime | None = None,
    max_items: int = _MAX_ITEMS,
) -> dict[str, Any]:
    """Build a compact, deterministic briefing from already-authorized data.

    `period` is presentation metadata, not a promise that the inputs cover that
    time window. The caller must query providers for the intended time range.
    """
    period_clean = _clean(period, 30) or "daily"
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    safe_max = max(1, min(int(max_items), _MAX_ITEMS))

    normalized: list[BriefingItem] = []
    for raw in items:
        if not isinstance(raw, Mapping):
            continue
        item = _normalize(raw)
        if item is not None:
            normalized.append(item)
        if len(normalized) >= 500:
            break

    rank = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    normalized.sort(key=lambda item: (rank[item.priority], item.source, item.title.casefold()))
    selected = normalized[:safe_max]
    counts = {source: 0 for source in sorted(_ALLOWED_SOURCES)}
    for item in normalized:
        counts[item.source] += 1

    rendered = []
    for item in selected:
        line = f"[{item.priority.upper()}] {item.source.upper()}: {item.title}"
        if item.detail:
            line += f" — {item.detail}"
        if item.url:
            line += f" ({item.url})"
        rendered.append(line)

    heading = f"ARIA {period_clean.title()} Briefing — {timestamp.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    if not rendered:
        body = f"{heading}\nNo items were supplied for this briefing."
    else:
        body = heading + "\n" + "\n".join(f"• {line}" for line in rendered)
        remaining = max(0, len(normalized) - len(selected))
        if remaining:
            body += f"\n…and {remaining} more item(s) omitted."

    return {
        "period": period_clean,
        "generated_at": timestamp.astimezone(timezone.utc).isoformat(),
        "total_items": len(normalized),
        "included_items": len(selected),
        "omitted_items": max(0, len(normalized) - len(selected)),
        "counts_by_source": counts,
        "items": [item.__dict__ for item in selected],
        "text": body,
        "requires_approval_to_send": True,
        "read_only": True,
    }
