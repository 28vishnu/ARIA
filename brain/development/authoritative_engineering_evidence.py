from __future__ import annotations

"""
ARIA — Authoritative Engineering Evidence Runtime

Step 31
-------

Provides one authoritative evidence ledger for an engineering session.

Design goals:
    - Every important engineering action can be recorded here.
    - Evidence belongs to exactly one EngineeringSession.
    - Evidence is preserved across lifecycle transitions.
    - Evidence can be persisted immediately through the existing
      engineering persistence layer.
    - Evidence is append-only from the engineering runtime's point of view.
    - Current execution evidence has priority over historical/advisory data.
    - Recording evidence must never silently turn a failed operation into
      success.
    - The recorder is deliberately tolerant of small compatibility
      differences between existing session/evidence implementations.

This module does NOT:
    - execute shell commands
    - modify production files
    - push GitHub
    - deploy
    - bypass approval gates
"""

import inspect
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


logger = logging.getLogger("aria")


try:
    from .contracts.engineering_evidence import (
        EngineeringEvidence,
        EvidenceKind,
    )
except Exception:  # pragma: no cover
    EngineeringEvidence = None  # type: ignore[assignment]
    EvidenceKind = None  # type: ignore[assignment]


@dataclass(frozen=True)
class EvidenceRecord:
    """
    Normalized evidence representation used by the authoritative recorder.

    This is intentionally independent from the concrete EngineeringEvidence
    implementation so the recorder remains compatible with older Phase 1
    components.
    """

    evidence_id: str
    session_id: str
    timestamp: str

    kind: str
    phase: str
    source: str

    summary: str

    task_id: str | None = None

    success: bool | None = None

    command: str | None = None
    exit_code: int | None = None

    stdout: str = ""
    stderr: str = ""

    duration_seconds: float | None = None

    paths: tuple[str, ...] = ()

    authoritative: bool = True

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "kind": self.kind,
            "phase": self.phase,
            "source": self.source,
            "summary": self.summary,
            "task_id": self.task_id,
            "success": self.success,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "paths": list(self.paths),
            "authoritative": self.authoritative,
            "metadata": dict(self.metadata),
        }


class EvidenceAuthority(str, Enum):
    """
    Authority levels for evidence.

    Current execution evidence is authoritative.
    Historical/advisory information must never override it.
    """

    AUTHORITATIVE = "authoritative"
    ADVISORY = "advisory"


class EngineeringEvidenceRecorder:
    """
    Central evidence recorder for the authoritative EngineeringSession.

    The recorder owns no engineering decision.

    It only records what actually happened.

    Typical usage:

        recorder = EngineeringEvidenceRecorder(
            session=session,
            persistence=persistence,
        )

        recorder.record(
            kind="implementation",
            phase="implementing",
            source="DevelopmentController",
            summary="Generated changes applied",
            success=True,
            paths=["example.py"],
        )

    The same recorder instance should remain attached to the engineering
    session for the complete lifecycle.
    """

    def __init__(
        self,
        session: Any,
        *,
        persistence: Any | None = None,
        source: str = "EngineeringEvidenceRecorder",
        auto_persist: bool = True,
    ) -> None:
        if session is None:
            raise ValueError(
                "EngineeringEvidenceRecorder requires an active session."
            )

        self.session = session
        self.persistence = persistence
        self.source = str(source)
        self.auto_persist = bool(auto_persist)

        self._records: list[EvidenceRecord] = []

    # ============================================================
    # Session identity
    # ============================================================

    @property
    def session_id(self) -> str:
        value = getattr(
            self.session,
            "session_id",
            None,
        )

        if value:
            return str(value)

        value = getattr(
            self.session,
            "id",
            None,
        )

        if value:
            return str(value)

        raise RuntimeError(
            "Authoritative EngineeringSession does not expose a session ID."
        )

    # ============================================================
    # Public evidence access
    # ============================================================

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records)

    def latest(self) -> EvidenceRecord | None:
        if not self._records:
            return None

        return self._records[-1]

    def count(self) -> int:
        return len(self._records)

    # ============================================================
    # Main recording API
    # ============================================================

    def record(
        self,
        *,
        kind: str | Any,
        phase: str | Any,
        source: str | None = None,
        summary: str,
        task_id: str | None = None,
        success: bool | None = None,
        command: str | None = None,
        exit_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        duration_seconds: float | None = None,
        paths: list[str] | tuple[str, ...] | None = None,
        authoritative: bool = True,
        metadata: Mapping[str, Any] | None = None,
        persist: bool | None = None,
    ) -> EvidenceRecord:
        """
        Record one authoritative engineering event.

        IMPORTANT:
            Recording evidence does not modify lifecycle state.

            A failed event remains failed evidence.
            An inconclusive event remains inconclusive evidence.
            The recorder never upgrades an outcome.
        """

        evidence_id = (
            f"evidence-{uuid.uuid4().hex}"
        )

        timestamp = (
            datetime.now(timezone.utc)
            .isoformat()
        )

        normalized_kind = self._normalize_enum(
            kind
        )

        normalized_phase = self._normalize_enum(
            phase
        )

        normalized_source = (
            str(
                source
                or self.source
            ).strip()
            or self.source
        )

        normalized_summary = (
            str(summary).strip()
        )

        if not normalized_summary:
            normalized_summary = (
                "Engineering event recorded."
            )

        normalized_stdout = (
            ""
            if stdout is None
            else str(stdout)
        )

        normalized_stderr = (
            ""
            if stderr is None
            else str(stderr)
        )

        normalized_paths = tuple(
            self._normalize_paths(paths)
        )

        record = EvidenceRecord(
            evidence_id=evidence_id,
            session_id=self.session_id,
            timestamp=timestamp,
            kind=normalized_kind,
            phase=normalized_phase,
            source=normalized_source,
            summary=normalized_summary,
            task_id=(
                str(task_id)
                if task_id is not None
                else None
            ),
            success=success,
            command=(
                str(command)
                if command is not None
                else None
            ),
            exit_code=exit_code,
            stdout=normalized_stdout,
            stderr=normalized_stderr,
            duration_seconds=(
                float(duration_seconds)
                if duration_seconds is not None
                else None
            ),
            paths=normalized_paths,
            authoritative=bool(authoritative),
            metadata=dict(metadata or {}),
        )

        self._records.append(record)

        self._attach_to_session(
            record
        )

        should_persist = (
            self.auto_persist
            if persist is None
            else bool(persist)
        )

        if should_persist:
            self._persist(
                record
            )

        logger.info(
            "[EngineeringEvidence] recorded | "
            "session=%s | kind=%s | phase=%s | "
            "success=%s | source=%s",
            self.session_id,
            record.kind,
            record.phase,
            record.success,
            record.source,
        )

        return record

    # ============================================================
    # Specialized recording helpers
    # ============================================================

    def record_lifecycle(
        self,
        *,
        phase: str,
        summary: str,
        previous_phase: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        details = dict(
            metadata or {}
        )

        if previous_phase is not None:
            details[
                "previous_phase"
            ] = str(previous_phase)

        return self.record(
            kind="lifecycle",
            phase=phase,
            source="EngineeringLifecycle",
            summary=summary,
            metadata=details,
        )

    def record_requirement(
        self,
        *,
        phase: str = "understanding",
        summary: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="requirement",
            phase=phase,
            source="EngineeringRequirement",
            summary=summary,
            metadata=metadata,
        )

    def record_repository(
        self,
        *,
        phase: str = "understanding",
        summary: str,
        paths: list[str] | tuple[str, ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="repository",
            phase=phase,
            source="RepositoryModel",
            summary=summary,
            paths=paths,
            metadata=metadata,
        )

    def record_plan(
        self,
        *,
        phase: str = "planning",
        summary: str,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="plan",
            phase=phase,
            source="AdaptiveEngineeringPlan",
            summary=summary,
            task_id=task_id,
            metadata=metadata,
        )

    def record_task(
        self,
        *,
        phase: str,
        summary: str,
        task_id: str,
        success: bool | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="task",
            phase=phase,
            source="EngineeringTaskGraph",
            summary=summary,
            task_id=task_id,
            success=success,
            metadata=metadata,
        )

    def record_implementation(
        self,
        *,
        summary: str,
        success: bool | None,
        task_id: str | None = None,
        paths: list[str] | tuple[str, ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="implementation",
            phase="implementing",
            source="AuthoritativeImplementationEngine",
            summary=summary,
            task_id=task_id,
            success=success,
            paths=paths,
            metadata=metadata,
        )

    def record_command(
        self,
        *,
        phase: str,
        command: str,
        summary: str,
        success: bool | None = None,
        exit_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        duration_seconds: float | None = None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="command",
            phase=phase,
            source="EngineeringCommandExecution",
            summary=summary,
            task_id=task_id,
            success=success,
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration_seconds,
            metadata=metadata,
        )

    def record_verification(
        self,
        *,
        summary: str,
        success: bool | None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="verification",
            phase="verifying",
            source="AuthoritativeVerificationEngine",
            summary=summary,
            task_id=task_id,
            success=success,
            metadata=metadata,
        )

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
    ) -> EvidenceRecord:
        return self.record(
            kind="test",
            phase="testing",
            source="DevelopmentTestRunner",
            summary=summary,
            task_id=task_id,
            success=success,
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration_seconds,
            metadata=metadata,
        )

    def record_diagnosis(
        self,
        *,
        summary: str,
        success: bool | None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="diagnosis",
            phase="diagnosing",
            source="AuthoritativeDiagnosisEngine",
            summary=summary,
            task_id=task_id,
            success=success,
            metadata=metadata,
        )

    def record_recovery(
        self,
        *,
        summary: str,
        success: bool | None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="recovery",
            phase="recovering",
            source="AuthoritativeRecoveryEngine",
            summary=summary,
            task_id=task_id,
            success=success,
            metadata=metadata,
        )

    def record_retest(
        self,
        *,
        summary: str,
        success: bool | None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="retest",
            phase="retesting",
            source="AuthoritativeRecoveryEngine",
            summary=summary,
            task_id=task_id,
            success=success,
            metadata=metadata,
        )

    def record_acceptance(
        self,
        *,
        summary: str,
        success: bool,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="acceptance",
            phase="accepting",
            source="AuthoritativeAcceptanceEngine",
            summary=summary,
            task_id=task_id,
            success=bool(success),
            metadata=metadata,
        )

    def record_failure(
        self,
        *,
        phase: str,
        summary: str,
        error: str | None = None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        details = dict(
            metadata or {}
        )

        if error:
            details[
                "error"
            ] = str(error)

        return self.record(
            kind="failure",
            phase=phase,
            source="EngineeringRuntime",
            summary=summary,
            task_id=task_id,
            success=False,
            metadata=details,
        )

    def record_authorization(
        self,
        *,
        phase: str,
        summary: str,
        authorized: bool,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        return self.record(
            kind="authorization",
            phase=phase,
            source="EngineeringPermissionBoundary",
            summary=summary,
            success=bool(authorized),
            metadata=metadata,
        )

    # ============================================================
    # Evidence import / restore
    # ============================================================

    def restore_records(
        self,
        records: Any,
    ) -> int:
        """
        Restore already-persisted evidence into the in-memory ledger.

        Existing evidence IDs are not duplicated.
        """

        if not records:
            return 0

        existing_ids = {
            item.evidence_id
            for item in self._records
        }

        restored = 0

        for raw in records:
            if isinstance(
                raw,
                EvidenceRecord,
            ):
                record = raw

            elif isinstance(
                raw,
                Mapping,
            ):
                try:
                    record = EvidenceRecord(
                        evidence_id=str(
                            raw.get(
                                "evidence_id",
                                f"evidence-{uuid.uuid4().hex}",
                            )
                        ),
                        session_id=str(
                            raw.get(
                                "session_id",
                                self.session_id,
                            )
                        ),
                        timestamp=str(
                            raw.get(
                                "timestamp",
                                datetime.now(
                                    timezone.utc
                                ).isoformat(),
                            )
                        ),
                        kind=str(
                            raw.get(
                                "kind",
                                "unknown",
                            )
                        ),
                        phase=str(
                            raw.get(
                                "phase",
                                "unknown",
                            )
                        ),
                        source=str(
                            raw.get(
                                "source",
                                "restored",
                            )
                        ),
                        summary=str(
                            raw.get(
                                "summary",
                                "",
                            )
                        ),
                        task_id=(
                            str(
                                raw["task_id"]
                            )
                            if raw.get(
                                "task_id"
                            )
                            is not None
                            else None
                        ),
                        success=raw.get(
                            "success"
                        ),
                        command=(
                            str(
                                raw["command"]
                            )
                            if raw.get(
                                "command"
                            )
                            is not None
                            else None
                        ),
                        exit_code=raw.get(
                            "exit_code"
                        ),
                        stdout=str(
                            raw.get(
                                "stdout",
                                "",
                            )
                        ),
                        stderr=str(
                            raw.get(
                                "stderr",
                                "",
                            )
                        ),
                        duration_seconds=raw.get(
                            "duration_seconds"
                        ),
                        paths=tuple(
                            str(item)
                            for item in raw.get(
                                "paths",
                                [],
                            )
                        ),
                        authoritative=bool(
                            raw.get(
                                "authoritative",
                                True,
                            )
                        ),
                        metadata=dict(
                            raw.get(
                                "metadata",
                                {},
                            )
                            or {}
                        ),
                    )

                except Exception as exc:
                    logger.warning(
                        "[EngineeringEvidence] "
                        "Skipping malformed restored evidence | "
                        "error=%s",
                        exc,
                    )
                    continue

            else:
                continue

            if (
                record.evidence_id
                in existing_ids
            ):
                continue

            self._records.append(
                record
            )

            existing_ids.add(
                record.evidence_id
            )

            restored += 1

        self._records.sort(
            key=lambda item: item.timestamp
        )

        return restored

    # ============================================================
    # Session integration
    # ============================================================

    def _attach_to_session(
        self,
        record: EvidenceRecord,
    ) -> None:
        """
        Attach evidence to the authoritative EngineeringSession.

        Prefer the session's official add_evidence() method.

        Compatibility fallbacks exist only so Step 31 can integrate with
        already-created Phase 1 session implementations without duplicating
        state ownership.
        """

        payload = record.to_dict()

        add_evidence = getattr(
            self.session,
            "add_evidence",
            None,
        )

        if callable(add_evidence):
            try:
                evidence_object = (
                    self._build_contract_evidence(
                        record
                    )
                )

                if evidence_object is not None:
                    result = add_evidence(
                        evidence_object
                    )
                else:
                    result = add_evidence(
                        payload
                    )

                if inspect.isawaitable(
                    result
                ):
                    logger.warning(
                        "[EngineeringEvidence] "
                        "Session add_evidence returned awaitable; "
                        "synchronous recorder cannot await it."
                    )

                return

            except TypeError:
                try:
                    result = add_evidence(
                        payload
                    )

                    if inspect.isawaitable(
                        result
                    ):
                        logger.warning(
                            "[EngineeringEvidence] "
                            "Session add_evidence returned awaitable."
                        )

                    return

                except Exception as exc:
                    logger.warning(
                        "[EngineeringEvidence] "
                        "Session evidence attachment failed | "
                        "error=%s",
                        exc,
                    )

            except Exception as exc:
                logger.warning(
                    "[EngineeringEvidence] "
                    "Session evidence attachment failed | "
                    "error=%s",
                    exc,
                )

        # Compatibility fallback.
        for attribute in (
            "evidence",
            "evidence_records",
            "execution_evidence",
        ):
            collection = getattr(
                self.session,
                attribute,
                None,
            )

            if isinstance(
                collection,
                list,
            ):
                collection.append(
                    payload
                )
                return

    # ============================================================
    # Contract conversion
    # ============================================================

    def _build_contract_evidence(
        self,
        record: EvidenceRecord,
    ) -> Any | None:
        if EngineeringEvidence is None:
            return None

        payload = record.to_dict()

        enum_value = self._resolve_evidence_kind(
            record.kind
        )

        payload_candidates = [
            {
                **payload,
                "kind": enum_value,
            },
            payload,
        ]

        for candidate in payload_candidates:
            try:
                return EngineeringEvidence(
                    **candidate
                )
            except TypeError:
                continue
            except Exception:
                continue

        # Some compatibility implementations use a factory.
        factory = getattr(
            EngineeringEvidence,
            "from_dict",
            None,
        )

        if callable(factory):
            for candidate in payload_candidates:
                try:
                    return factory(
                        candidate
                    )
                except Exception:
                    continue

        return None

    # ============================================================
    # Persistence
    # ============================================================

    def _persist(
        self,
        record: EvidenceRecord,
    ) -> None:
        """
        Persist through the existing authoritative persistence service.

        No second persistence database is created here.
        """

        if self.persistence is None:
            return

        payload = record.to_dict()

        # Preferred: append_evidence(session_id, evidence).
        method = getattr(
            self.persistence,
            "append_evidence",
            None,
        )

        if callable(method):
            attempts = (
                lambda: method(
                    self.session_id,
                    payload,
                ),
                lambda: method(
                    session_id=self.session_id,
                    evidence=payload,
                ),
                lambda: method(
                    payload
                ),
            )

            for attempt in attempts:
                try:
                    result = attempt()

                    if inspect.isawaitable(
                        result
                    ):
                        logger.warning(
                            "[EngineeringEvidence] "
                            "Persistence returned awaitable."
                        )

                    return

                except TypeError:
                    continue

                except Exception as exc:
                    logger.warning(
                        "[EngineeringEvidence] "
                        "Evidence append failed | error=%s",
                        exc,
                    )
                    return

        # Fallback: persist the complete authoritative session.
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

            try:
                result = self._call_persistence_method(
                    method
                )

                if inspect.isawaitable(
                    result
                ):
                    logger.warning(
                        "[EngineeringEvidence] "
                        "Persistence returned awaitable."
                    )

                return

            except TypeError:
                continue

            except Exception as exc:
                logger.warning(
                    "[EngineeringEvidence] "
                    "Session persistence failed | "
                    "method=%s | error=%s",
                    method_name,
                    exc,
                )
                return

    def _call_persistence_method(
        self,
        method: Any,
    ) -> Any:
        """
        Compatibility dispatcher for existing persistence signatures.
        """

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
            lambda: method(
                self.session_id
            ),
        )

        last_error: Exception | None = None

        for attempt in attempts:
            try:
                return attempt()
            except TypeError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error

        return None

    # ============================================================
    # Normalization helpers
    # ============================================================

    @staticmethod
    def _normalize_enum(
        value: Any,
    ) -> str:
        if isinstance(
            value,
            Enum,
        ):
            return str(
                value.value
            )

        raw = str(
            value
        ).strip()

        if "." in raw:
            raw = raw.rsplit(
                ".",
                1,
            )[-1]

        return raw.lower()

    @staticmethod
    def _normalize_paths(
        paths: Any,
    ) -> list[str]:
        if paths is None:
            return []

        if isinstance(
            paths,
            str,
        ):
            paths = [
                paths
            ]

        result: list[str] = []

        for path in paths:
            value = (
                str(path)
                .strip()
                .replace("\\", "/")
            )

            if not value:
                continue

            if value not in result:
                result.append(
                    value
                )

        return result

    @staticmethod
    def _resolve_evidence_kind(
        value: str,
    ) -> Any:
        if EvidenceKind is None:
            return value

        normalized = str(
            value
        ).strip().lower()

        for member in EvidenceKind:
            member_value = str(
                getattr(
                    member,
                    "value",
                    member,
                )
            ).lower()

            member_name = str(
                getattr(
                    member,
                    "name",
                    "",
                )
            ).lower()

            if (
                normalized == member_value
                or normalized == member_name
            ):
                return member

        return value

    # ============================================================
    # Snapshot
    # ============================================================

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "source": self.source,
            "record_count": len(
                self._records
            ),
            "records": [
                record.to_dict()
                for record in self._records
            ],
        }

    def clear_local_cache(
        self,
    ) -> None:
        """
        Clear only the recorder's local cache.

        This never deletes persisted session evidence.
        """

        self._records.clear()


__all__ = [
    "EvidenceAuthority",
    "EvidenceRecord",
    "EngineeringEvidenceRecorder",
]