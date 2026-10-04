from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


logger = logging.getLogger("aria")


class EvidenceAuthority(str, Enum):
    """
    Authority level for engineering evidence.

    Current execution evidence is stronger than historical
    assumptions or inferred information.
    """

    USER = "user"
    EXECUTION = "execution"
    REPOSITORY = "repository"
    VERIFICATION = "verification"
    TEST = "test"
    DIAGNOSIS = "diagnosis"
    RECOVERY = "recovery"
    ACCEPTANCE = "acceptance"
    HISTORICAL = "historical"
    INFERENCE = "inference"


@dataclass(frozen=True)
class EvidenceRecord:
    """
    Immutable engineering evidence record.
    """

    evidence_id: str
    kind: str
    summary: str
    details: Any = None
    source: str = "unknown"
    authority: EvidenceAuthority = (
        EvidenceAuthority.EXECUTION
    )
    timestamp: str = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        ).isoformat()
    )
    session_id: str | None = None
    task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "summary": self.summary,
            "details": self._serialize(
                self.details
            ),
            "source": self.source,
            "authority": self.authority.value,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "task_id": self.task_id,
        }

    @staticmethod
    def _serialize(
        value: Any,
    ) -> Any:
        if value is None:
            return None

        if isinstance(value, Enum):
            return value.value

        if isinstance(value, dict):
            return {
                str(key): EvidenceRecord._serialize(
                    item
                )
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [
                EvidenceRecord._serialize(
                    item
                )
                for item in value
            ]

        to_dict = getattr(
            value,
            "to_dict",
            None,
        )

        if callable(to_dict):
            try:
                return to_dict()
            except Exception:
                pass

        if hasattr(value, "__dict__"):
            try:
                return {
                    str(key): EvidenceRecord._serialize(
                        item
                    )
                    for key, item in vars(value).items()
                    if not str(key).startswith("_")
                }
            except Exception:
                pass

        return value


class EngineeringEvidenceRecorder:
    """
    Central evidence ledger for an engineering session.

    Responsibilities:

        requirement evidence
        repository evidence
        plan evidence
        task evidence
        implementation evidence
        command evidence
        verification evidence
        test evidence
        diagnosis evidence
        recovery evidence
        retest evidence
        acceptance evidence
        failure evidence
        authorization evidence

    The recorder is deliberately passive.

    It does not:
        - execute shell commands
        - modify source files
        - push GitHub
        - deploy
        - bypass permissions

    It records what the engineering system actually observed.
    """

    def __init__(
        self,
        session: Any | None = None,
        *,
        session_id: str | None = None,
        persistence: Any | None = None,
        records: list[EvidenceRecord] | None = None,
        **kwargs: Any,
    ) -> None:
        self.session = session
        self.session_id = (
            session_id
            or getattr(
                session,
                "session_id",
                None,
            )
        )

        self.persistence = persistence

        self._records: list[
            EvidenceRecord
        ] = list(
            records or []
        )

        self._counter = len(
            self._records
        )

        self.metadata = dict(
            kwargs
        )

    # ==========================================================
    # Basic access
    # ==========================================================

    @property
    def records(
        self,
    ) -> tuple[EvidenceRecord, ...]:
        return tuple(
            self._records
        )

    @property
    def evidence(
        self,
    ) -> tuple[EvidenceRecord, ...]:
        return self.records

    def __len__(
        self,
    ) -> int:
        return len(
            self._records
        )

    def __iter__(
        self,
    ):
        return iter(
            self._records
        )

    # ==========================================================
    # ID / authority helpers
    # ==========================================================

    def _next_id(
        self,
    ) -> str:
        self._counter += 1

        prefix = (
            self.session_id
            or "engineering"
        )

        return (
            f"{prefix}:evidence:"
            f"{self._counter}"
        )

    @staticmethod
    def _normalize_authority(
        authority: Any,
        kind: str,
    ) -> EvidenceAuthority:
        if isinstance(
            authority,
            EvidenceAuthority,
        ):
            return authority

        if authority is not None:
            try:
                return EvidenceAuthority(
                    str(authority).lower()
                )
            except Exception:
                pass

        normalized = str(
            kind
        ).lower()

        if (
            "accept" in normalized
        ):
            return EvidenceAuthority.ACCEPTANCE

        if (
            "diagnos" in normalized
        ):
            return EvidenceAuthority.DIAGNOSIS

        if (
            "recover" in normalized
            or "repair" in normalized
        ):
            return EvidenceAuthority.RECOVERY

        if (
            "test" in normalized
        ):
            return EvidenceAuthority.TEST

        if (
            "verif" in normalized
        ):
            return EvidenceAuthority.VERIFICATION

        if (
            "repository" in normalized
        ):
            return EvidenceAuthority.REPOSITORY

        if (
            "requirement" in normalized
        ):
            return EvidenceAuthority.USER

        return EvidenceAuthority.EXECUTION

    # ==========================================================
    # Recording
    # ==========================================================

    def record(
        self,
        *,
        kind: str,
        summary: str,
        details: Any = None,
        source: str = "unknown",
        authority: Any = None,
        evidence_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        persist: bool = True,
        **kwargs: Any,
    ) -> EvidenceRecord:
        """
        Record one authoritative engineering observation.
        """

        record = EvidenceRecord(
            evidence_id=(
                evidence_id
                or self._next_id()
            ),
            kind=str(
                kind
            ),
            summary=str(
                summary
            ),
            details=details,
            source=str(
                source
            ),
            authority=(
                self._normalize_authority(
                    authority,
                    kind,
                )
            ),
            session_id=(
                session_id
                or self.session_id
            ),
            task_id=task_id,
        )

        self._records.append(
            record
        )

        self._attach_to_session(
            record
        )

        if persist:
            self._persist_record(
                record
            )

        return record

    def add(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            *args,
            **kwargs,
        )

    def append(
        self,
        record: EvidenceRecord,
        *,
        persist: bool = True,
    ) -> EvidenceRecord:
        if not isinstance(
            record,
            EvidenceRecord,
        ):
            raise TypeError(
                "append() requires an "
                "EvidenceRecord."
            )

        self._records.append(
            record
        )

        self._attach_to_session(
            record
        )

        if persist:
            self._persist_record(
                record
            )

        return record

    # ==========================================================
    # Convenience evidence methods
    # ==========================================================

    def requirement(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="requirement",
            summary=summary,
            details=details,
            authority=EvidenceAuthority.USER,
            **kwargs,
        )

    def repository(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="repository",
            summary=summary,
            details=details,
            authority=EvidenceAuthority.REPOSITORY,
            **kwargs,
        )

    def plan(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="plan",
            summary=summary,
            details=details,
            authority=EvidenceAuthority.EXECUTION,
            **kwargs,
        )

    def task(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="task",
            summary=summary,
            details=details,
            **kwargs,
        )

    def implementation(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="implementation",
            summary=summary,
            details=details,
            **kwargs,
        )

    def command(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="command",
            summary=summary,
            details=details,
            **kwargs,
        )

    def verification(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="verification",
            summary=summary,
            details=details,
            authority=EvidenceAuthority.VERIFICATION,
            **kwargs,
        )

    def test(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="test",
            summary=summary,
            details=details,
            authority=EvidenceAuthority.TEST,
            **kwargs,
        )

    def diagnosis(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="diagnosis",
            summary=summary,
            details=details,
            authority=EvidenceAuthority.DIAGNOSIS,
            **kwargs,
        )

    def recovery(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="recovery",
            summary=summary,
            details=details,
            authority=EvidenceAuthority.RECOVERY,
            **kwargs,
        )

    def retest(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="retest",
            summary=summary,
            details=details,
            authority=EvidenceAuthority.TEST,
            **kwargs,
        )

    def acceptance(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="acceptance",
            summary=summary,
            details=details,
            authority=EvidenceAuthority.ACCEPTANCE,
            **kwargs,
        )

    def failure(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="failure",
            summary=summary,
            details=details,
            **kwargs,
        )

    def authorization(
        self,
        summary: str,
        details: Any = None,
        **kwargs: Any,
    ) -> EvidenceRecord:
        return self.record(
            kind="authorization",
            summary=summary,
            details=details,
            authority=EvidenceAuthority.USER,
            **kwargs,
        )

    # ==========================================================
    # Session attachment
    # ==========================================================

    def _attach_to_session(
        self,
        record: EvidenceRecord,
    ) -> None:
        session = self.session

        if session is None:
            return

        methods = (
            "add_evidence",
            "record_evidence",
            "append_evidence",
        )

        for name in methods:
            method = getattr(
                session,
                name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                lambda: method(
                    record
                ),
                lambda: method(
                    record.to_dict()
                ),
                lambda: method(
                    evidence=record
                ),
                lambda: method(
                    evidence=record.to_dict()
                ),
            )

            for attempt in attempts:
                try:
                    result = attempt()

                    if inspect.isawaitable(
                        result
                    ):
                        # The session API should normally be
                        # synchronous. Do not create an event
                        # loop here; persistence remains handled
                        # separately.
                        logger.debug(
                            "[EngineeringEvidence] "
                            "Session evidence method returned "
                            "an awaitable | method=%s",
                            name,
                        )

                    return

                except TypeError:
                    continue

                except Exception:
                    logger.exception(
                        "[EngineeringEvidence] "
                        "Could not attach evidence to session | "
                        "method=%s",
                        name,
                    )
                    return

    # ==========================================================
    # Persistence
    # ==========================================================

    def _persist_record(
        self,
        record: EvidenceRecord,
    ) -> None:
        persistence = self.persistence

        if persistence is None:
            self._checkpoint_session()
            return

        methods = (
            "append_evidence",
            "record_evidence",
            "save_evidence",
            "persist_evidence",
        )

        payload = record.to_dict()

        for name in methods:
            method = getattr(
                persistence,
                name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                lambda: method(
                    payload
                ),
                lambda: method(
                    evidence=payload
                ),
                lambda: method(
                    record
                ),
                lambda: method(
                    session_id=self.session_id,
                    evidence=payload,
                ),
            )

            for attempt in attempts:
                try:
                    result = attempt()

                    if inspect.isawaitable(
                        result
                    ):
                        logger.debug(
                            "[EngineeringEvidence] "
                            "Persistence method returned "
                            "an awaitable | method=%s",
                            name,
                        )

                    return

                except TypeError:
                    continue

                except Exception:
                    logger.exception(
                        "[EngineeringEvidence] "
                        "Could not persist evidence | "
                        "method=%s",
                        name,
                    )
                    return

        self._checkpoint_session()

    def _checkpoint_session(
        self,
    ) -> None:
        session = self.session

        if session is None:
            return

        for name in (
            "checkpoint",
            "save",
            "persist",
        ):
            method = getattr(
                session,
                name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method()

                if inspect.isawaitable(
                    result
                ):
                    logger.debug(
                        "[EngineeringEvidence] "
                        "Session checkpoint returned "
                        "an awaitable | method=%s",
                        name,
                    )

                return

            except TypeError:
                continue

            except Exception:
                logger.exception(
                    "[EngineeringEvidence] "
                    "Session checkpoint failed | "
                    "method=%s",
                    name,
                )
                return

    # ==========================================================
    # Queries
    # ==========================================================

    def latest(
        self,
        count: int = 1,
    ) -> list[EvidenceRecord]:
        if count <= 0:
            return []

        return list(
            self._records[-count:]
        )

    def by_kind(
        self,
        kind: str,
    ) -> list[EvidenceRecord]:
        normalized = str(
            kind
        ).lower()

        return [
            item
            for item in self._records
            if item.kind.lower()
            == normalized
        ]

    def find(
        self,
        evidence_id: str,
    ) -> EvidenceRecord | None:
        for item in self._records:
            if (
                item.evidence_id
                == evidence_id
            ):
                return item

        return None

    def has_kind(
        self,
        kind: str,
    ) -> bool:
        return bool(
            self.by_kind(kind)
        )

    def has_acceptance_evidence(
        self,
    ) -> bool:
        return self.has_kind(
            "acceptance"
        )

    def has_verification_evidence(
        self,
    ) -> bool:
        return self.has_kind(
            "verification"
        )

    def has_test_evidence(
        self,
    ) -> bool:
        return self.has_kind(
            "test"
        )

    # ==========================================================
    # Export / restore
    # ==========================================================

    def snapshot(
        self,
    ) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "count": len(
                self._records
            ),
            "records": [
                item.to_dict()
                for item in self._records
            ],
            "metadata": dict(
                self.metadata
            ),
        }

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return self.snapshot()

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Any,
        *,
        session: Any | None = None,
        persistence: Any | None = None,
    ) -> "EngineeringEvidenceRecorder":
        if isinstance(
            snapshot,
            cls,
        ):
            return snapshot

        if not isinstance(
            snapshot,
            dict,
        ):
            return cls(
                session=session,
                persistence=persistence,
            )

        raw_records = snapshot.get(
            "records",
            [],
        )

        records: list[
            EvidenceRecord
        ] = []

        for raw in raw_records:
            if isinstance(
                raw,
                EvidenceRecord,
            ):
                records.append(
                    raw
                )
                continue

            if not isinstance(
                raw,
                dict,
            ):
                continue

            authority_raw = raw.get(
                "authority",
                EvidenceAuthority.EXECUTION.value,
            )

            try:
                authority = (
                    EvidenceAuthority(
                        str(
                            authority_raw
                        ).lower()
                    )
                )
            except Exception:
                authority = (
                    EvidenceAuthority.EXECUTION
                )

            records.append(
                EvidenceRecord(
                    evidence_id=str(
                        raw.get(
                            "evidence_id",
                            "",
                        )
                    ),
                    kind=str(
                        raw.get(
                            "kind",
                            "unknown",
                        )
                    ),
                    summary=str(
                        raw.get(
                            "summary",
                            "",
                        )
                    ),
                    details=raw.get(
                        "details"
                    ),
                    source=str(
                        raw.get(
                            "source",
                            "unknown",
                        )
                    ),
                    authority=authority,
                    timestamp=str(
                        raw.get(
                            "timestamp",
                            datetime.now(
                                timezone.utc
                            ).isoformat(),
                        )
                    ),
                    session_id=raw.get(
                        "session_id"
                    ),
                    task_id=raw.get(
                        "task_id"
                    ),
                )
            )

        return cls(
            session=session,
            session_id=(
                snapshot.get(
                    "session_id"
                )
            ),
            persistence=persistence,
            records=records,
            **(
                snapshot.get(
                    "metadata",
                    {},
                )
                if isinstance(
                    snapshot.get(
                        "metadata",
                        {},
                    ),
                    dict,
                )
                else {}
            ),
        )

    @classmethod
    def restore(
        cls,
        snapshot: Any,
        *,
        session: Any | None = None,
        persistence: Any | None = None,
    ) -> "EngineeringEvidenceRecorder":
        return cls.from_snapshot(
            snapshot,
            session=session,
            persistence=persistence,
        )

    # ==========================================================
    # Health
    # ==========================================================

    def health(
        self,
    ) -> dict[str, Any]:
        return {
            "healthy": True,
            "session_id": self.session_id,
            "evidence_count": len(
                self._records
            ),
            "persistent": (
                self.persistence is not None
            ),
            "authoritative": True,
        }