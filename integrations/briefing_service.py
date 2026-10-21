"""Provider-agnostic orchestration for ARIA's approval-gated briefings.

No provider API is called here directly. The application injects authorized,
read-only async collectors for Gmail, Calendar, GitHub and Drive. This avoids
assuming method names or authentication behavior from integrations not present
in this module. Preparing a briefing never sends it.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from integrations.briefing_workflow import BriefingWorkflow

_LOG = logging.getLogger(__name__)
Collector = Callable[[], Awaitable[Sequence[Mapping[str, Any]]]]
ALLOWED_SOURCES = {"gmail", "calendar", "github", "drive", "system"}


class BriefingService:
    """Collect read-only provider results and persist a preview for approval."""

    def __init__(
        self,
        workflow: BriefingWorkflow,
        collectors: Mapping[str, Collector],
        *,
        timeout_seconds: float = 20.0,
        max_items_per_source: int = 50,
    ) -> None:
        self.workflow = workflow
        self.collectors = dict(collectors)
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 60.0))
        self.max_items_per_source = max(1, min(int(max_items_per_source), 100))
        unknown = set(self.collectors) - ALLOWED_SOURCES
        if unknown:
            raise ValueError(f"Unsupported briefing source(s): {', '.join(sorted(unknown))}")
        for name, collector in self.collectors.items():
            if not callable(collector):
                raise TypeError(f"Collector for {name} must be callable")

    async def _collect_one(self, source: str, collector: Collector) -> tuple[str, list[dict[str, Any]], str | None]:
        try:
            result = collector()
            if not inspect.isawaitable(result):
                raise TypeError("collector must return an awaitable")
            raw_items = await asyncio.wait_for(result, timeout=self.timeout_seconds)
            if not isinstance(raw_items, (list, tuple)):
                raise TypeError("collector result must be a list or tuple")
            normalized: list[dict[str, Any]] = []
            for raw in raw_items[: self.max_items_per_source]:
                if not isinstance(raw, Mapping):
                    continue
                item = dict(raw)
                # The configured collector is the source of truth. Ignore a
                # mismatched source label returned by the provider adapter.
                item["source"] = source
                normalized.append(item)
            return source, normalized, None
        except Exception as exc:
            _LOG.warning("Briefing collector %s failed: %s", source, type(exc).__name__)
            return source, [], type(exc).__name__

    async def prepare(self, *, period: str = "daily") -> dict[str, Any]:
        """Collect available sources and save a preview; never sends anything."""
        results = await asyncio.gather(
            *(self._collect_one(source, collector) for source, collector in self.collectors.items())
        )
        items: list[dict[str, Any]] = []
        source_status: dict[str, str] = {}
        for source, source_items, error in results:
            items.extend(source_items)
            source_status[source] = "ok" if error is None else f"unavailable ({error})"
        preview = self.workflow.prepare(items, period=period)
        preview["sources"] = source_status
        preview["sent"] = False
        preview["requires_owner_approval"] = True
        return preview

    async def prepare_morning(self) -> dict[str, Any]:
        return await self.prepare(period="morning")

    async def prepare_evening(self) -> dict[str, Any]:
        return await self.prepare(period="evening")
