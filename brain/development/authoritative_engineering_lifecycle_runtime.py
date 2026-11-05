from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .evidence_aware_engineering_lifecycle import (
    EvidenceAwareEngineeringLifecycle,
)
from .engineering_evidence import EngineeringEvidenceRecorder
from .engineering_session import EngineeringSession


logger = logging.getLogger("aria")


class AuthoritativeEngineeringLifecycleRuntime:
    """
    Authoritative runtime boundary for ARIA's engineering lifecycle.

    Responsibilities:
        - own the EngineeringSession
        - own the evidence-aware lifecycle
        - make lifecycle transitions authoritative
        - persist checkpoints through the configured persistence layer
        - expose compatibility transition methods
        - never infer ACCEPTED merely from execution success

    Important:
        execution success != requirement acceptance.

    ACCEPTED may only be reached through an explicit acceptance
    decision/evidence path.
    """

    def __init__(
        self,
        *,
        session: EngineeringSession | None = None,
        persistence: Any | None = None,
        session_id: str | None = None,
        requirement: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.persistence = persistence

        self.session = (
            session
            if session is not None
            else self._create_session(
                session_id=session_id,
                requirement=requirement,
                metadata=metadata,
            )
        )

        self.session_id = self._resolve_session_id(
            self.session,
            session_id,
        )

        self.evidence = EngineeringEvidenceRecorder(
            self.session
        )

        self.lifecycle = EvidenceAwareEngineeringLifecycle(
            self.session,
            evidence_recorder=self.evidence,
        )

        self.created_at = datetime.now(
            timezone.utc
        ).isoformat()

        self._checkpoint()

    # ============================================================
    # Session creation / compatibility
    # ============================================================

    @staticmethod
    def _resolve_session_id(
        session: Any,
        fallback: str | None,
    ) -> str:
        value = getattr(
            session,
            "session_id",
            None,
        )

        if value:
            return str(value)

        if fallback:
            return str(fallback)

        return "engineering-session"

    @staticmethod
    def _create_session(
        *,
        session_id: str | None,
        requirement: Any | None,
        metadata: dict[str, Any] | None,
    ) -> EngineeringSession:
        """
        Create an EngineeringSession while remaining compatible with
        the session constructor used by the current repository.
        """

        candidates: list[dict[str, Any]] = []

        if session_id is not None:
            candidates.append(
                {
                    "session_id": session_id,
                    "requirement": requirement,
                    "metadata": metadata or {},
                }
            )

            candidates.append(
                {
                    "session_id": session_id,
                    "requirement": requirement,
                }
            )

            candidates.append(
                {
                    "session_id": session_id,
                }
            )

        if requirement is not None:
            candidates.append(
                {
                    "requirement": requirement,
                    "metadata": metadata or {},
                }
            )

            candidates.append(
                {
                    "requirement": requirement,
                }
            )

        candidates.append(
            {
                "metadata": metadata or {},
            }
        )

        candidates.append({})

        last_error: Exception | None = None

        for kwargs in candidates:
            try:
                return EngineeringSession(
                    **kwargs
                )
            except TypeError as exc:
                last_error = exc
                continue

        raise RuntimeError(
            "Unable to construct EngineeringSession "
            f"with the available compatibility signatures: "
            f"{last_error}"
        )

    # ============================================================
    # Persistence
    # ============================================================

    def _checkpoint(self) -> Any:
        """
        Persist the complete authoritative session state.

        The persistence implementation has changed during Phase 1,
        so this method intentionally supports the known save/checkpoint
        compatibility forms.
        """

        persistence = self.persistence

        if persistence is None:
            return None

        snapshot = self.snapshot()

        methods = (
            "checkpoint",
            "save",
            "persist",
        )

        for method_name in methods:
            method = getattr(
                persistence,
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
                    self.session_id,
                    snapshot,
                ),
                lambda: method(
                    snapshot
                ),
                lambda: method(
                    session_id=self.session_id,
                    snapshot=snapshot,
                ),
                lambda: method(
                    session=self.session
                ),
            )

            for attempt in attempts:
                try:
                    return attempt()
                except TypeError:
                    continue
                except Exception:
                    logger.exception(
                        "[AuthoritativeLifecycle] "
                        "Persistence operation failed | method=%s",
                        method_name,
                    )
                    return None

        return None

    # ============================================================
    # Canonical lifecycle transitions
    # ============================================================

    def mark_created(
        self,
        *,
        reason: str = "Engineering session created.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_created(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_understanding(
        self,
        *,
        reason: str = "Requirement and repository understanding completed.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_understanding(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_planning(
        self,
        *,
        reason: str = "Engineering planning started.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_planning(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_graph_ready(
        self,
        *,
        reason: str = "Engineering task graph is ready.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_graph_ready(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_implementing(
        self,
        *,
        reason: str = "Implementation started in the isolated workspace.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_implementing(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_verifying(
        self,
        *,
        reason: str = "Implementation verification started.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_verifying(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_testing(
        self,
        *,
        reason: str = "Testing started.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_testing(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_diagnosing(
        self,
        *,
        reason: str = "Failure diagnosis started.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_diagnosing(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_recovering(
        self,
        *,
        reason: str = "Recovery/repair started.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_recovering(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_retesting(
        self,
        *,
        reason: str = "Retesting started after recovery.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_retesting(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_reassessing(
        self,
        *,
        reason: str = "Engineering result is being reassessed.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_reassessing(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_accepting(
        self,
        *,
        reason: str = "Acceptance evaluation started.",
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_accepting(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_accepted(
        self,
        *,
        reason: str = "Requirement explicitly accepted.",
        evidence: Any | None = None,
    ) -> Any:
        """
        Explicit acceptance boundary.

        This method is intentionally NOT called automatically when
        an underlying development runtime merely reports success.

        The caller must supply the acceptance evidence/decision.
        """

        if evidence is None:
            raise ValueError(
                "ACCEPTED requires explicit acceptance evidence. "
                "Execution success alone is insufficient."
            )

        result = self.lifecycle.mark_accepted(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_blocked(
        self,
        *,
        reason: str,
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_blocked(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def mark_failed(
        self,
        *,
        reason: str,
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.mark_failed(
            reason=reason,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    # ============================================================
    # Task lifecycle
    # ============================================================

    def task_started(
        self,
        task_id: str,
        *,
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.task_started(
            task_id,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    def task_completed(
        self,
        task_id: str,
        *,
        evidence: Any | None = None,
    ) -> Any:
        result = self.lifecycle.task_completed(
            task_id,
            evidence=evidence,
        )
        self._checkpoint()
        return result

    # ============================================================
    # Evidence
    # ============================================================

    def record_evidence(
        self,
        kind: Any,
        *,
        summary: str,
        details: Any | None = None,
        authority: Any | None = None,
        source: str | None = None,
    ) -> Any:
        result = self.evidence.record(
            kind=kind,
            summary=summary,
            details=details,
            authority=authority,
            source=source,
        )
        self._checkpoint()
        return result

    def record_failure(
        self,
        *,
        summary: str,
        details: Any | None = None,
        source: str | None = None,
    ) -> Any:
        result = self.evidence.record_failure(
            summary=summary,
            details=details,
            source=source,
        )
        self._checkpoint()
        return result

    def evidence_snapshot(self) -> list[dict[str, Any]]:
        return self.evidence.snapshot()

    # ============================================================
    # Status / health
    # ============================================================

    @property
    def state(self) -> Any:
        return getattr(
            self.session,
            "state",
            None,
        )

    @property
    def phase(self) -> Any:
        return getattr(
            self.session,
            "phase",
            None,
        )

    @property
    def status(self) -> dict[str, Any]:
        session_status = None

        status_method = getattr(
            self.session,
            "status",
            None,
        )

        if callable(status_method):
            try:
                session_status = status_method()
            except Exception:
                session_status = None

        if session_status is None:
            session_status = {
                "session_id": self.session_id,
                "phase": str(
                    getattr(
                        self.session,
                        "phase",
                        "unknown",
                    )
                ),
                "state": str(
                    getattr(
                        self.session,
                        "state",
                        "unknown",
                    )
                ),
            }

        return {
            "session_id": self.session_id,
            "session": session_status,
            "evidence_count": len(
                self.evidence_snapshot()
            ),
            "lifecycle": self.lifecycle.snapshot(),
        }

    def health(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "authoritative": True,
            "session_id": self.session_id,
            "evidence_aware": True,
            "lifecycle": self.lifecycle.snapshot(),
        }

    # ============================================================
    # Snapshot / restore
    # ============================================================

    def snapshot(self) -> dict[str, Any]:
        session_snapshot: Any = None

        snapshot_method = getattr(
            self.session,
            "snapshot",
            None,
        )

        if callable(snapshot_method):
            try:
                session_snapshot = snapshot_method()
            except Exception:
                session_snapshot = None

        if session_snapshot is None:
            to_dict = getattr(
                self.session,
                "to_dict",
                None,
            )

            if callable(to_dict):
                try:
                    session_snapshot = to_dict()
                except Exception:
                    session_snapshot = None

        if session_snapshot is None:
            session_snapshot = {
                "session_id": self.session_id,
                "phase": str(
                    getattr(
                        self.session,
                        "phase",
                        "unknown",
                    )
                ),
                "state": str(
                    getattr(
                        self.session,
                        "state",
                        "unknown",
                    )
                ),
            }

        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "session": session_snapshot,
            "evidence": self.evidence_snapshot(),
            "lifecycle": self.lifecycle.snapshot(),
            "runtime": {
                "authoritative": True,
                "evidence_aware": True,
                "acceptance_requires_explicit_evidence": True,
            },
        }

    # ============================================================
    # Compatibility aliases
    # ============================================================

    def transition(
        self,
        target: Any,
        *,
        reason: str = "",
        evidence: Any | None = None,
    ) -> Any:
        """
        Compatibility transition entry point.

        New code should prefer the explicit mark_* methods.
        """

        transition = getattr(
            self.lifecycle,
            "transition",
            None,
        )

        if not callable(transition):
            raise RuntimeError(
                "Evidence-aware lifecycle does not expose "
                "a generic transition method."
            )

        result = transition(
            target,
            reason=reason,
            evidence=evidence,
        )

        self._checkpoint()
        return result

    def checkpoint(self) -> Any:
        return self._checkpoint()

    def save(self) -> Any:
        return self._checkpoint()

    def persist(self) -> Any:
        return self._checkpoint()


# Backward-compatible alias used by integrations that refer to the
# runtime as the authoritative engineering lifecycle.
AuthoritativeEngineeringLifecycle = (
    AuthoritativeEngineeringLifecycleRuntime
)