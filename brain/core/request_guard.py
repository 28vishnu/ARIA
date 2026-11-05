"""In-flight request coalescing and bounded request execution.

The guard prevents two identical requests for the same conversation from
running the cognitive pipeline at the same time. A duplicate waits for the
original result instead of executing the same expensive work again.

It intentionally does not cache completed answers. An intentional repeated
question therefore still runs normally once the previous request is done.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("aria")


class RequestGuard:
    """Coalesce identical in-flight requests and enforce a hard timeout."""

    VERSION = "1.0.0"

    def __init__(
        self,
        default_timeout: float = 120.0,
        max_pending_duplicates: int = 32,
    ) -> None:
        self.default_timeout = max(1.0, float(default_timeout))
        self.max_pending_duplicates = max(1, int(max_pending_duplicates))
        self._inflight: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def make_key(
        session_id: Any,
        text: Any,
    ) -> str:
        normalized = " ".join(
            str(text or "").strip().casefold().split()
        )
        digest = hashlib.sha256(
            normalized.encode("utf-8", errors="replace")
        ).hexdigest()[:24]
        return f"{str(session_id or '')}:{digest}"

    async def run(
        self,
        key: str,
        operation: Callable[[], Awaitable[Any]],
        timeout: Optional[float] = None,
    ) -> Any:
        """Run ``operation`` once per key and share its result with duplicates."""

        effective_timeout = (
            self.default_timeout
            if timeout is None
            else max(1.0, float(timeout))
        )

        owner = False
        future: asyncio.Future

        async with self._lock:
            existing = self._inflight.get(key)
            if existing is not None and not existing.done():
                future = existing
            else:
                future = asyncio.get_running_loop().create_future()
                self._inflight[key] = future
                owner = True

        if not owner:
            logger.info(
                "[RequestGuard] Coalesced duplicate in-flight request."
            )
            # Duplicates share the owner's result. Allow a little extra time so
            # the owner's own timeout/error handling wins the race.
            return await asyncio.wait_for(
                asyncio.shield(future),
                timeout=effective_timeout + 5.0,
            )

        # Ensure an exception stored on the future is considered retrieved even
        # when this is the only waiter.
        future.add_done_callback(
            lambda done: (
                None
                if done.cancelled()
                else done.exception()
            )
        )

        try:
            result = await asyncio.wait_for(
                operation(),
                timeout=effective_timeout,
            )
            if not future.done():
                future.set_result(result)
            return result

        except asyncio.CancelledError:
            if not future.done():
                future.cancel()
            raise

        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
            raise

        finally:
            async with self._lock:
                if self._inflight.get(key) is future:
                    self._inflight.pop(key, None)

    def pending_count(self) -> int:
        return len(self._inflight)

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "version": self.VERSION,
            "inflight_requests": len(self._inflight),
            "default_timeout": self.default_timeout,
        }


def normalize_request_timeout(value: Any, default: float = 120.0) -> float:
    """Parse a timeout in seconds, bounded to a safe range."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed != parsed:  # NaN
        parsed = default
    return max(5.0, min(parsed, 900.0))


def is_duplicate_response_text(text: Any) -> bool:
    """Compatibility helper for callers that need a lightweight check."""
    return bool(
        re.search(
            r"\b(?:already working|duplicate request)\b",
            str(text or ""),
            re.IGNORECASE,
        )
    )
