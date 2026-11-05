from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    operation: str
    reason: str
    risk_level: str
    created_at: str
    expires_at: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "operation": self.operation,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "metadata": dict(
                self.metadata or {}
            ),
        }


@dataclass(frozen=True)
class ApprovalDecision:
    request_id: str
    approved: bool
    decided_at: str
    decided_by: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approved": self.approved,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "reason": self.reason,
        }


class ApprovalManager:
    """
    Manages human approval requests.

    This component intentionally does not automatically approve
    production operations.

    A future Telegram/UI integration can call approve() or
    reject() after the Master reviews the request.
    """

    def __init__(
        self,
        *,
        request_timeout_seconds: float = 1800.0,
    ) -> None:

        if request_timeout_seconds <= 0:
            raise ValueError(
                "request_timeout_seconds must be positive."
            )

        self.request_timeout_seconds = float(
            request_timeout_seconds
        )

        self._counter = 0

        self._pending: dict[
            str,
            ApprovalRequest,
        ] = {}

        self._decisions: dict[
            str,
            ApprovalDecision,
        ] = {}

        self._events: dict[
            str,
            asyncio.Event,
        ] = {}

    def _next_id(self) -> str:
        self._counter += 1

        timestamp = datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%d%H%M%S"
        )

        return (
            f"approval-"
            f"{timestamp}-"
            f"{self._counter:04d}"
        )

    def create_request(
        self,
        *,
        operation: str,
        reason: str,
        risk_level: str,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:

        operation = operation.strip()
        reason = reason.strip()
        risk_level = risk_level.strip().lower()

        if not operation:
            raise ValueError(
                "operation cannot be empty."
            )

        if not reason:
            raise ValueError(
                "reason cannot be empty."
            )

        if risk_level not in {
            "low",
            "medium",
            "high",
            "critical",
        }:
            raise ValueError(
                "Invalid risk level."
            )

        request_id = self._next_id()

        request = ApprovalRequest(
            request_id=request_id,
            operation=operation,
            reason=reason,
            risk_level=risk_level,
            created_at=_utc_now(),
            metadata=dict(
                metadata or {}
            ),
        )

        self._pending[
            request_id
        ] = request

        self._events[
            request_id
        ] = asyncio.Event()

        return request

    def approve(
        self,
        request_id: str,
        *,
        decided_by: str = "Master",
        reason: str = "Approved by Master.",
    ) -> ApprovalDecision:

        return self._decide(
            request_id,
            approved=True,
            decided_by=decided_by,
            reason=reason,
        )

    def reject(
        self,
        request_id: str,
        *,
        decided_by: str = "Master",
        reason: str = "Rejected by Master.",
    ) -> ApprovalDecision:

        return self._decide(
            request_id,
            approved=False,
            decided_by=decided_by,
            reason=reason,
        )

    def _decide(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str,
        reason: str,
    ) -> ApprovalDecision:

        if request_id not in self._pending:
            existing = self._decisions.get(
                request_id
            )

            if existing:
                return existing

            raise KeyError(
                f"Unknown approval request: "
                f"{request_id}"
            )

        decision = ApprovalDecision(
            request_id=request_id,
            approved=approved,
            decided_at=_utc_now(),
            decided_by=decided_by,
            reason=reason.strip()
            or (
                "No reason provided."
            ),
        )

        self._decisions[
            request_id
        ] = decision

        self._pending.pop(
            request_id,
            None,
        )

        event = self._events.get(
            request_id
        )

        if event:
            event.set()

        return decision

    async def wait_for_decision(
        self,
        request_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ApprovalDecision | None:

        if request_id in self._decisions:
            return self._decisions[
                request_id
            ]

        if request_id not in self._pending:
            raise KeyError(
                f"Unknown approval request: "
                f"{request_id}"
            )

        event = self._events[
            request_id
        ]

        timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else self.request_timeout_seconds
        )

        if timeout <= 0:
            raise ValueError(
                "timeout_seconds must be positive."
            )

        try:
            await asyncio.wait_for(
                event.wait(),
                timeout=timeout,
            )

        except asyncio.TimeoutError:
            return None

        return self._decisions.get(
            request_id
        )

    def pending_requests(
        self,
    ) -> list[ApprovalRequest]:

        return list(
            self._pending.values()
        )

    def get_request(
        self,
        request_id: str,
    ) -> ApprovalRequest | None:

        return self._pending.get(
            request_id
        )

    def get_decision(
        self,
        request_id: str,
    ) -> ApprovalDecision | None:

        return self._decisions.get(
            request_id
        )

    def status(self) -> dict[str, Any]:
        return {
            "pending": [
                request.to_dict()
                for request in self._pending.values()
            ],
            "decisions": [
                decision.to_dict()
                for decision in self._decisions.values()
            ],
        }