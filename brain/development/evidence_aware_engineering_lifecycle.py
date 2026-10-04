from __future__ import annotations

"""
ARIA — Evidence-Aware Engineering Lifecycle

Step 32
-------

Connects the authoritative EngineeringLifecycle to the authoritative
EngineeringEvidenceRecorder.

The lifecycle remains responsible for state transitions.

The evidence recorder remains responsible for the engineering history.

This class makes them one coherent runtime boundary:

    lifecycle transition
          ↓
    evidence recorded
          ↓
    session checkpoint

Important rules:

    - A lifecycle transition is recorded only after the transition succeeds.
    - Failed transitions are recorded as failure evidence.
    - Evidence never changes lifecycle state by itself.
    - Persistence failures do not convert engineering success into failure.
    - Engineering failures remain explicit evidence.
    - No GitHub, deployment, shell, or production-write capability is added.
"""

import inspect
import logging
from typing import Any, Mapping

from .authoritative_engineering_evidence import (
    EngineeringEvidenceRecorder,
)
from .engineering_lifecycle import (
    EngineeringLifecycle,
)
from .contracts.engineering_session import (
    EngineeringSession,
)


logger = logging.getLogger("aria")


class EvidenceAwareEngineeringLifecycle:
    """
    Authoritative lifecycle facade with automatic evidence recording.

    This class deliberately wraps the existing EngineeringLifecycle instead
    of replacing it. That preserves the transition rules already established
    in Step 4 while making every successful transition observable.
    """

    def __init__(
        self,
        session: EngineeringSession,
        *,
        lifecycle: EngineeringLifecycle | None = None,
        persistence: Any | None = None,
        evidence_recorder: EngineeringEvidenceRecorder | None = None,
        auto_persist: bool = True,
    ) -> None:
        if session is None:
            raise ValueError(
                "EvidenceAwareEngineeringLifecycle requires a session."
            )

        self.session = session

        self.lifecycle = (
            lifecycle
            if lifecycle is not None
            else EngineeringLifecycle(
                session=session
            )
        )

        self.evidence = (
            evidence_recorder
            if evidence_recorder is not None
            else EngineeringEvidenceRecorder(
                session,
                persistence=persistence,
                auto_persist=auto_persist,
                source="EvidenceAwareEngineeringLifecycle",
            )
        )

        self.persistence = persistence
        self.auto_persist = bool(auto_persist)

    # ============================================================
    # State
    # ============================================================

    @property
    def state(self) -> Any:
        return getattr(
            self.lifecycle,
            "state",
            getattr(
                self.session,
                "state",
                None,
            ),
        )

    @property
    def phase(self) -> Any:
        value = getattr(
            self.lifecycle,
            "phase",
            None,
        )

        if value is not None:
            return value

        return getattr(
            self.session,
            "phase",
            None,
        )

    @property
    def session_id(self) -> str:
        return str(
            getattr(
                self.session,
                "session_id",
                getattr(
                    self.session,
                    "id",
                    "",
                ),
            )
        )

    # ============================================================
    # Generic transition
    # ============================================================

    def transition(
        self,
        target: Any,
        *,
        summary: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        """
        Execute one authoritative lifecycle transition.

        The transition is performed by EngineeringLifecycle.

        Evidence is recorded only after the transition succeeds.
        """

        previous_phase = self._phase_text()

        try:
            result = self._invoke_transition(
                target
            )

        except Exception as exc:
            self.evidence.record_failure(
                phase=previous_phase or "unknown",
                summary=(
                    "Lifecycle transition failed."
                ),
                error=str(exc),
                metadata={
                    "target_phase": self._phase_text(
                        target
                    ),
                    **dict(metadata or {}),
                },
            )

            self._checkpoint()

            raise

        current_phase = self._phase_text()

        self.evidence.record_lifecycle(
            phase=current_phase,
            summary=(
                summary
                or (
                    "Engineering lifecycle transitioned "
                    f"from '{previous_phase}' to "
                    f"'{current_phase}'."
                )
            ),
            previous_phase=previous_phase,
            metadata={
                "target_phase": current_phase,
                **dict(metadata or {}),
            },
        )

        self._checkpoint()

        return result

    # ============================================================
    # Canonical lifecycle helpers
    # ============================================================

    def mark_created(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "created",
            "Engineering session created.",
            metadata,
        )

    def mark_understanding(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "understanding",
            "Engineering session entered repository and requirement understanding.",
            metadata,
        )

    def mark_planning(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "planning",
            "Engineering session entered adaptive planning.",
            metadata,
        )

    def mark_graph_ready(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "graph_ready",
            "Engineering task graph is ready for execution.",
            metadata,
        )

    def mark_implementing(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "implementing",
            "Engineering session entered autonomous implementation.",
            metadata,
        )

    def mark_verifying(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "verifying",
            "Engineering session entered verification.",
            metadata,
        )

    def mark_testing(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "testing",
            "Engineering session entered testing.",
            metadata,
        )

    def mark_diagnosing(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "diagnosing",
            "Engineering session entered root-cause diagnosis.",
            metadata,
        )

    def mark_recovering(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "recovering",
            "Engineering session entered autonomous recovery.",
            metadata,
        )

    def mark_retesting(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "retesting",
            "Engineering session entered retesting.",
            metadata,
        )

    def mark_reassessing(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "reassessing",
            "Engineering session is reassessing the engineering outcome.",
            metadata,
        )

    def mark_accepting(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "accepting",
            "Engineering session entered acceptance judgment.",
            metadata,
        )

    def mark_accepted(
        self,
        **metadata: Any,
    ) -> Any:
        return self._mark(
            "accepted",
            "Engineering session reached accepted state.",
            metadata,
        )

    def mark_blocked(
        self,
        *,
        reason: str | None = None,
        **metadata: Any,
    ) -> Any:
        details = dict(metadata)

        if reason:
            details["reason"] = reason

        return self._mark(
            "blocked",
            (
                "Engineering session was blocked."
                if not reason
                else f"Engineering session was blocked: {reason}"
            ),
            details,
        )

    def mark_failed(
        self,
        *,
        reason: str | None = None,
        **metadata: Any,
    ) -> Any:
        details = dict(metadata)

        if reason:
            details["reason"] = reason

        return self._mark(
            "failed",
            (
                "Engineering session failed."
                if not reason
                else f"Engineering session failed: {reason}"
            ),
            details,
        )

    # ============================================================
    # Task evidence
    # ============================================================

    def task_started(
        self,
        task_id: str,
        *,
        phase: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.evidence.record_task(
            phase=(
                phase
                or self._phase_text()
            ),
            summary=(
                f"Engineering task '{task_id}' started."
            ),
            task_id=str(task_id),
            metadata=metadata,
        )

        self._checkpoint()

    def task_completed(
        self,
        task_id: str,
        *,
        success: bool,
        phase: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.evidence.record_task(
            phase=(
                phase
                or self._phase_text()
            ),
            summary=(
                f"Engineering task '{task_id}' "
                f"{'completed successfully' if success else 'failed'}."
            ),
            task_id=str(task_id),
            success=bool(success),
            metadata=metadata,
        )

        self._checkpoint()

    # ============================================================
    # Domain evidence shortcuts
    # ============================================================

    def record_implementation(
        self,
        *,
        summary: str,
        success: bool | None,
        task_id: str | None = None,
        paths: list[str] | tuple[str, ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        result = self.evidence.record_implementation(
            summary=summary,
            success=success,
            task_id=task_id,
            paths=paths,
            metadata=metadata,
        )

        self._checkpoint()

        return result

    def record_test(
        self,
        *,
        summary: str,
        success: bool | None,
        command: str | None = None,
        exit_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        duration_seconds: float | None = None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        result = self.evidence.record_test(
            summary=summary,
            success=success,
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration_seconds,
            task_id=task_id,
            metadata=metadata,
        )

        self._checkpoint()

        return result

    def record_verification(
        self,
        *,
        summary: str,
        success: bool | None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        result = self.evidence.record_verification(
            summary=summary,
            success=success,
            task_id=task_id,
            metadata=metadata,
        )

        self._checkpoint()

        return result

    def record_diagnosis(
        self,
        *,
        summary: str,
        success: bool | None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        result = self.evidence.record_diagnosis(
            summary=summary,
            success=success,
            task_id=task_id,
            metadata=metadata,
        )

        self._checkpoint()

        return result

    def record_recovery(
        self,
        *,
        summary: str,
        success: bool | None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        result = self.evidence.record_recovery(
            summary=summary,
            success=success,
            task_id=task_id,
            metadata=metadata,
        )

        self._checkpoint()

        return result

    def record_retest(
        self,
        *,
        summary: str,
        success: bool | None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        result = self.evidence.record_retest(
            summary=summary,
            success=success,
            task_id=task_id,
            metadata=metadata,
        )

        self._checkpoint()

        return result

    def record_acceptance(
        self,
        *,
        summary: str,
        success: bool,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        result = self.evidence.record_acceptance(
            summary=summary,
            success=success,
            task_id=task_id,
            metadata=metadata,
        )

        self._checkpoint()

        return result

    # ============================================================
    # Failure handling
    # ============================================================

    def record_failure(
        self,
        *,
        phase: str | None = None,
        summary: str,
        error: str | None = None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        result = self.evidence.record_failure(
            phase=(
                phase
                or self._phase_text()
                or "unknown"
            ),
            summary=summary,
            error=error,
            task_id=task_id,
            metadata=metadata,
        )

        self._checkpoint()

        return result

    # ============================================================
    # Evidence access
    # ============================================================

    @property
    def evidence_records(self) -> tuple[Any, ...]:
        return self.evidence.records

    def evidence_snapshot(self) -> dict[str, Any]:
        return self.evidence.snapshot()

    def latest_evidence(self) -> Any | None:
        return self.evidence.latest()

    # ============================================================
    # Snapshot
    # ============================================================

    def snapshot(self) -> dict[str, Any]:
        lifecycle_snapshot = {}

        snapshot_method = getattr(
            self.lifecycle,
            "snapshot",
            None,
        )

        if callable(snapshot_method):
            try:
                lifecycle_snapshot = (
                    snapshot_method()
                )
            except Exception:
                lifecycle_snapshot = {}

        return {
            "session_id": self.session_id,
            "lifecycle": lifecycle_snapshot,
            "evidence": self.evidence.snapshot(),
        }

    # ============================================================
    # Internal transition compatibility
    # ============================================================

    def _mark(
        self,
        target: str,
        summary: str,
        metadata: Mapping[str, Any],
    ) -> Any:
        return self.transition(
            target,
            summary=summary,
            metadata=metadata,
        )

    def _invoke_transition(
        self,
        target: Any,
    ) -> Any:
        """
        Compatibility dispatcher for EngineeringLifecycle versions.

        Prefer the lifecycle's canonical transition() method.

        If the lifecycle exposes a dedicated method instead, use that.

        No transition is silently swallowed.
        """

        transition_method = getattr(
            self.lifecycle,
            "transition",
            None,
        )

        if callable(transition_method):
            attempts = (
                lambda: transition_method(
                    target
                ),
                lambda: transition_method(
                    target_phase=target
                ),
                lambda: transition_method(
                    phase=target
                ),
            )

            last_type_error: Exception | None = None

            for attempt in attempts:
                try:
                    return attempt()
                except TypeError as exc:
                    last_type_error = exc
                    continue

            if last_type_error is not None:
                raise last_type_error

        normalized = (
            str(target)
            .strip()
            .lower()
        )

        if "." in normalized:
            normalized = normalized.rsplit(
                ".",
                1,
            )[-1]

        candidates = (
            f"mark_{normalized}",
            normalized,
        )

        for name in candidates:
            method = getattr(
                self.lifecycle,
                name,
                None,
            )

            if not callable(method):
                continue

            return method()

        raise AttributeError(
            "EngineeringLifecycle does not expose a compatible "
            f"transition method for '{target}'."
        )

    # ============================================================
    # Phase normalization
    # ============================================================

    def _phase_text(
        self,
        value: Any | None = None,
    ) -> str:
        if value is None:
            value = self.phase

        if value is None:
            return ""

        raw = getattr(
            value,
            "value",
            value,
        )

        raw = str(
            raw
        ).strip()

        if "." in raw:
            raw = raw.rsplit(
                ".",
                1,
            )[-1]

        return raw.lower()

    # ============================================================
    # Persistence
    # ============================================================

    def _checkpoint(self) -> None:
        """
        Persist the complete authoritative session when possible.

        Evidence recording already attempts persistence itself.

        This additional checkpoint keeps lifecycle state and evidence
        synchronized when an existing persistence implementation supports
        session checkpoints.
        """

        if not self.auto_persist:
            return

        if self.persistence is None:
            return

        for method_name in (
            "checkpoint",
            "save",
            "persist",
        ):
            method = getattr(
                self.persistence,
                method_name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                lambda: method(
                    self.session
                ),
                lambda: method(
                    session=self.session
                ),
                lambda: method(
                    self.session_id,
                    self.session,
                ),
                lambda: method(
                    session_id=self.session_id,
                    session=self.session,
                ),
            )

            for attempt in attempts:
                try:
                    result = attempt()

                    if inspect.isawaitable(
                        result
                    ):
                        logger.warning(
                            "[EvidenceLifecycle] "
                            "Persistence returned awaitable; "
                            "synchronous checkpoint skipped."
                        )

                    return

                except TypeError:
                    continue

                except Exception as exc:
                    logger.warning(
                        "[EvidenceLifecycle] "
                        "Checkpoint failed | "
                        "method=%s | error=%s",
                        method_name,
                        exc,
                    )
                    return


__all__ = [
    "EvidenceAwareEngineeringLifecycle",
]