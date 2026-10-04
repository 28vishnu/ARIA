"""Authoritative autonomous recovery engine for ARIA.

Step 14 connects diagnosis to repair and fresh retesting.

The engine deliberately does not claim that a repair succeeded merely
because a repair service returned successfully.

The lifecycle is:

    Diagnose
        ↓
    Decide repairability
        ↓
    Create repair request
        ↓
    Existing repair service
        ↓
    Create fresh retest request
        ↓
    Verification
        ↓
    Reassessment

A successful repair operation is not equivalent to a recovered system.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from .contracts.engineering_recovery import (
    RecoveryAction,
    RecoveryDecision,
    RecoveryRequest,
    RecoveryResult,
    RecoveryStatus,
    RepairRequest,
    RetestRequest,
)


class AuthoritativeRecoveryEngine:
    """Adapter connecting diagnosis, repair, and retest."""

    VERSION = "PHASE1-AUTHORITATIVE-RECOVERY-20261004"

    def __init__(
        self,
        repair_engine: Any | None = None,
    ) -> None:
        self.repair_engine = repair_engine

    async def recover(
        self,
        request: RecoveryRequest,
    ) -> RecoveryResult:
        """Determine and, when possible, initiate recovery."""

        if not isinstance(
            request,
            RecoveryRequest,
        ):
            raise TypeError(
                "request must be a RecoveryRequest."
            )

        diagnosis = dict(
            request.diagnosis
        )

        primary = self._primary_diagnosis(
            diagnosis
        )

        if primary is None:
            return self._needs_evidence_result(
                request,
                "No sufficiently supported root cause is available.",
            )

        confidence = self._confidence(
            primary
        )

        needs_more = bool(
            diagnosis.get(
                "needs_more_evidence",
                False,
            )
        )

        if needs_more:
            return self._needs_evidence_result(
                request,
                "Root-cause diagnosis requires additional evidence.",
                confidence=confidence,
            )

        repair_direction = str(
            primary.get(
                "repair_direction",
                "",
            )
        ).strip()

        if not repair_direction:
            return self._blocked_result(
                request,
                (
                    "The diagnosis does not provide a safe "
                    "repair direction."
                ),
                confidence=confidence,
            )

        repair_request = RepairRequest(
            session_id=request.session_id,
            task_id=request.task_id,
            objective=(
                f"Recover task '{request.task_id}' by resolving "
                f"the diagnosed engineering failure."
            ),
            repair_direction=repair_direction,
            affected_paths=(
                request.affected_paths
            ),
            protected_paths=(
                self._protected_paths(
                    request.diagnosis
                )
            ),
            constraints=(
                request.constraints
            ),
            evidence_required=(
                "fresh verification after repair",
                "comparison against original failure",
                "changed-path evidence",
            ),
            workspace_id=request.workspace_id,
            metadata={
                "recovery_version": self.VERSION,
                "diagnosis_category": primary.get(
                    "category",
                    "unknown",
                ),
            },
        )

        if self.repair_engine is None:
            return self._repair_ready_result(
                request,
                repair_request,
                confidence,
            )

        repair_attempt_id = self._new_attempt_id(
            request
        )

        try:
            raw_repair = await self._invoke_repair(
                request,
                repair_request,
            )

        except Exception as exc:
            return self._repair_failure_result(
                request,
                repair_request,
                repair_attempt_id,
                exc,
            )

        repair_success = self._repair_success(
            raw_repair
        )

        if not repair_success:
            return self._repair_failure_result(
                request,
                repair_request,
                repair_attempt_id,
                self._repair_error(
                    raw_repair
                ),
            )

        retest = RetestRequest(
            session_id=request.session_id,
            task_id=request.task_id,
            requirement=request.requirement,
            acceptance_criteria=(
                request.acceptance_criteria
            ),
            original_failure=request.failure,
            repair_attempt_id=repair_attempt_id,
            changed_paths=(
                request.affected_paths
            ),
            workspace_id=request.workspace_id,
            verification_methods=(
                "repeat the narrowest failed verification",
                "verify the repaired affected paths",
                "recheck acceptance criteria",
            ),
            metadata={
                "recovery_version": self.VERSION,
                "fresh_evidence_required": True,
            },
        )

        decision = RecoveryDecision(
            status=RecoveryStatus.RETESTING,
            action=RecoveryAction.RETEST,
            confidence=confidence,
            reason=(
                "Repair operation completed; fresh verification "
                "is mandatory before recovery can be accepted."
            ),
            repair_request=repair_request,
            retest_required=True,
            additional_evidence=(
                "fresh verification result",
                "fresh test output",
                "post-repair affected-path evidence",
            ),
            metadata={
                "recovery_version": self.VERSION,
                "repair_operation_success": True,
            },
        )

        return RecoveryResult(
            session_id=request.session_id,
            task_id=request.task_id,
            decision=decision,
            repair_attempt_id=repair_attempt_id,
            retest_request=retest,
            metadata={
                "recovery_version": self.VERSION,
            },
        )

    async def _invoke_repair(
        self,
        request: RecoveryRequest,
        repair_request: RepairRequest,
    ) -> Any:
        """Invoke the existing repair service through a compatibility boundary."""

        service = self.repair_engine

        method = getattr(
            service,
            "repair",
            None,
        )

        if method is None:
            method = getattr(
                service,
                "execute",
                None,
            )

        if method is None:
            method = getattr(
                service,
                "run",
                None,
            )

        if method is None:
            raise AttributeError(
                "Repair service does not expose repair(), "
                "execute(), or run()."
            )

        try:
            result = method(
                repair_request
            )
        except TypeError:
            try:
                result = method(
                    request.failure,
                    repair_direction=(
                        repair_request.repair_direction
                    ),
                    affected_paths=(
                        repair_request.affected_paths
                    ),
                )
            except TypeError:
                result = method(
                    request.failure
                )

        if hasattr(
            result,
            "__await__",
        ):
            return await result

        return result

    @staticmethod
    def _primary_diagnosis(
        diagnosis: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        raw = diagnosis.get(
            "primary"
        )

        if isinstance(
            raw,
            Mapping,
        ):
            return dict(
                raw
            )

        if raw is not None:
            result: dict[str, Any] = {}

            for name in (
                "category",
                "statement",
                "confidence",
                "repair_direction",
                "evidence_ids",
            ):
                value = getattr(
                    raw,
                    name,
                    None,
                )

                if value is not None:
                    result[
                        name
                    ] = value

            return result or None

        return None

    @staticmethod
    def _confidence(
        primary: Mapping[str, Any],
    ) -> float:
        try:
            return max(
                0.0,
                min(
                    1.0,
                    float(
                        primary.get(
                            "confidence",
                            0.0,
                        )
                    ),
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            return 0.0

    @staticmethod
    def _protected_paths(
        diagnosis: Mapping[str, Any],
    ) -> tuple[str, ...]:
        raw = diagnosis.get(
            "protected_paths",
            (),
        )

        if isinstance(
            raw,
            str,
        ):
            return (
                raw,
            )

        if isinstance(
            raw,
            (list, tuple, set),
        ):
            return tuple(
                str(item)
                for item in raw
                if str(item).strip()
            )

        return ()

    def _repair_ready_result(
        self,
        request: RecoveryRequest,
        repair_request: RepairRequest,
        confidence: float,
    ) -> RecoveryResult:
        """Return a repair request when no repair service is attached."""

        decision = RecoveryDecision(
            status=RecoveryStatus.ANALYZING,
            action=RecoveryAction.REPAIR,
            confidence=confidence,
            reason=(
                "Diagnosis supports a repair direction, but no "
                "repair service is attached to execute it."
            ),
            repair_request=repair_request,
            retest_required=True,
            blockers=(
                "repair_service_unavailable",
            ),
            metadata={
                "recovery_version": self.VERSION,
            },
        )

        return RecoveryResult(
            session_id=request.session_id,
            task_id=request.task_id,
            decision=decision,
            metadata={
                "recovery_version": self.VERSION,
            },
        )

    def _needs_evidence_result(
        self,
        request: RecoveryRequest,
        reason: str,
        *,
        confidence: float = 0.0,
    ) -> RecoveryResult:
        decision = RecoveryDecision(
            status=RecoveryStatus.ANALYZING,
            action=RecoveryAction.GATHER_EVIDENCE,
            confidence=confidence,
            reason=reason,
            retest_required=False,
            additional_evidence=(
                "exact failing command",
                "exit code",
                "complete stdout",
                "complete stderr",
                "first meaningful failure location",
                "targeted discriminating verification",
            ),
            metadata={
                "recovery_version": self.VERSION,
            },
        )

        return RecoveryResult(
            session_id=request.session_id,
            task_id=request.task_id,
            decision=decision,
            metadata={
                "recovery_version": self.VERSION,
            },
        )

    def _blocked_result(
        self,
        request: RecoveryRequest,
        reason: str,
        *,
        confidence: float = 0.0,
    ) -> RecoveryResult:
        decision = RecoveryDecision(
            status=RecoveryStatus.BLOCKED,
            action=RecoveryAction.BLOCK,
            confidence=confidence,
            reason=reason,
            blockers=(
                "unsafe_or_unsupported_repair_direction",
            ),
            metadata={
                "recovery_version": self.VERSION,
            },
        )

        return RecoveryResult(
            session_id=request.session_id,
            task_id=request.task_id,
            decision=decision,
            metadata={
                "recovery_version": self.VERSION,
            },
        )

    def _repair_failure_result(
        self,
        request: RecoveryRequest,
        repair_request: RepairRequest,
        repair_attempt_id: str,
        error: Any,
    ) -> RecoveryResult:
        message = str(
            error
        )

        decision = RecoveryDecision(
            status=RecoveryStatus.FAILED,
            action=RecoveryAction.REASSESS,
            confidence=0.0,
            reason=(
                "Repair execution failed. The original failure "
                "must not be treated as recovered."
            ),
            repair_request=repair_request,
            retest_required=False,
            blockers=(
                message,
            ),
            metadata={
                "recovery_version": self.VERSION,
                "repair_attempt_failed": True,
            },
        )

        return RecoveryResult(
            session_id=request.session_id,
            task_id=request.task_id,
            decision=decision,
            repair_attempt_id=repair_attempt_id,
            metadata={
                "recovery_version": self.VERSION,
            },
        )

    @staticmethod
    def _repair_success(
        result: Any,
    ) -> bool:
        if isinstance(
            result,
            bool,
        ):
            return result

        if isinstance(
            result,
            Mapping,
        ):
            success = result.get(
                "success"
            )

            if isinstance(
                success,
                bool,
            ):
                return success

            status = str(
                result.get(
                    "status",
                    "",
                )
            ).lower()

            return status in {
                "success",
                "completed",
                "repaired",
                "accepted",
            }

        success = getattr(
            result,
            "success",
            None,
        )

        if isinstance(
            success,
            bool,
        ):
            return success

        status = str(
            getattr(
                result,
                "status",
                "",
            )
        ).lower()

        return status in {
            "success",
            "completed",
            "repaired",
            "accepted",
        }

    @staticmethod
    def _repair_error(
        result: Any,
    ) -> str:
        if isinstance(
            result,
            Mapping,
        ):
            return str(
                result.get(
                    "error",
                    result.get(
                        "message",
                        "Repair service reported failure.",
                    ),
                )
            )

        return str(
            getattr(
                result,
                "error",
                getattr(
                    result,
                    "message",
                    "Repair service reported failure.",
                ),
            )
        )

    @staticmethod
    def _new_attempt_id(
        request: RecoveryRequest,
    ) -> str:
        return (
            f"{request.session_id}:"
            f"{request.task_id}:repair:"
            f"{uuid.uuid4().hex[:12]}"
        )


__all__ = [
    "AuthoritativeRecoveryEngine",
]