from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    EngineeringEvidence,
    EngineeringSession,
    EngineeringStore,
)

logger = logging.getLogger("aria.authoritative_engineering_persistence")


class EngineeringPersistenceError(RuntimeError):
    """Raised when authoritative engineering state cannot be persisted."""


class EngineeringPersistence:
    """
    Authoritative persistence boundary for autonomous engineering.

    Responsibilities
    ----------------
    - Persist complete engineering-session state.
    - Persist individual evidence records.
    - Restore interrupted sessions after process/restart failure.
    - Maintain crash-safe checkpoints.
    - Never treat persistence itself as engineering success.
    - Keep evidence separate from transient runtime objects.

    This class deliberately does not execute code, modify repositories,
    push GitHub changes, or deploy anything.
    """

    VERSION = "ENGINEERING-PERSISTENCE-V1"

    def __init__(
        self,
        store: EngineeringStore | None = None,
        *,
        root: str | Path | None = None,
        auto_checkpoint: bool = True,
    ) -> None:
        self.store = store
        self.auto_checkpoint = bool(auto_checkpoint)

        if root is None:
            root = Path(".aria_sessions")

        self.root = Path(root).expanduser().resolve()
        self.sessions_root = self.root / "sessions"
        self.evidence_root = self.root / "evidence"
        self.checkpoints_root = self.root / "checkpoints"

        self.sessions_root.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.evidence_root.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.checkpoints_root.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ==========================================================
    # Public session API
    # ==========================================================

    async def save_session(
        self,
        session: EngineeringSession,
        *,
        checkpoint: bool = False,
    ) -> bool:
        """
        Persist the authoritative engineering session.

        The canonical session snapshot is written atomically.

        If an existing EngineeringStore is connected, it is also used
        through a compatibility boundary.
        """

        snapshot = self._session_snapshot(session)

        session_id = self._session_id(session)

        if not session_id:
            raise EngineeringPersistenceError(
                "Cannot persist engineering session without session_id."
            )

        snapshot["persistence"] = {
            "version": self.VERSION,
            "saved_at": self._now(),
            "checkpoint": bool(checkpoint),
        }

        path = self._session_path(session_id)

        await asyncio.to_thread(
            self._atomic_json_write,
            path,
            snapshot,
        )

        if self.store is not None:
            await self._store_save(
                session,
                snapshot,
            )

        if checkpoint:
            checkpoint_path = (
                self.checkpoints_root
                / f"{session_id}.json"
            )

            await asyncio.to_thread(
                self._atomic_json_write,
                checkpoint_path,
                snapshot,
            )

        logger.info(
            "[EngineeringPersistence] "
            "Session persisted | session_id=%s | checkpoint=%s",
            session_id,
            checkpoint,
        )

        return True

    async def checkpoint(
        self,
        session: EngineeringSession,
    ) -> bool:
        """
        Create a durable engineering checkpoint.

        Checkpoints are safe restart boundaries, not acceptance boundaries.
        """

        return await self.save_session(
            session,
            checkpoint=True,
        )

    async def load_session(
        self,
        session_id: str,
    ) -> EngineeringSession | None:
        """
        Restore an engineering session.

        The newest canonical session snapshot is preferred.
        """

        normalized = self._normalize_session_id(
            session_id
        )

        path = self._session_path(normalized)

        snapshot: dict[str, Any] | None = None

        if path.exists():
            snapshot = await asyncio.to_thread(
                self._read_json,
                path,
            )

        if snapshot is None and self.store is not None:
            snapshot = await self._store_load(
                normalized
            )

        if snapshot is None:
            checkpoint = (
                self.checkpoints_root
                / f"{normalized}.json"
            )

            if checkpoint.exists():
                snapshot = await asyncio.to_thread(
                    self._read_json,
                    checkpoint,
                )

        if snapshot is None:
            return None

        session = self._restore_session(
            snapshot
        )

        if session is not None:
            logger.info(
                "[EngineeringPersistence] "
                "Session restored | session_id=%s",
                normalized,
            )

        return session

    async def has_session(
        self,
        session_id: str,
    ) -> bool:
        normalized = self._normalize_session_id(
            session_id
        )

        if self._session_path(normalized).exists():
            return True

        if (
            self.checkpoints_root
            / f"{normalized}.json"
        ).exists():
            return True

        if self.store is not None:
            loaded = await self._store_load(
                normalized
            )
            return loaded is not None

        return False

    # ==========================================================
    # Evidence API
    # ==========================================================

    async def append_evidence(
        self,
        session: EngineeringSession,
        evidence: EngineeringEvidence | Mapping[str, Any],
    ) -> bool:
        """
        Persist an evidence record independently from the session.

        Evidence is append-only at this boundary.

        This prevents important verification/test/diagnostic evidence
        from disappearing when an in-memory session is interrupted.
        """

        session_id = self._session_id(session)

        if not session_id:
            raise EngineeringPersistenceError(
                "Cannot persist evidence without session_id."
            )

        payload = self._serialize(
            evidence
        )

        evidence_id = (
            payload.get("evidence_id")
            or self._generated_evidence_id()
        )

        payload["evidence_id"] = evidence_id
        payload["session_id"] = session_id
        payload["persisted_at"] = self._now()
        payload["persistence_version"] = self.VERSION

        session_dir = (
            self.evidence_root
            / self._safe_component(session_id)
        )

        session_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        evidence_path = (
            session_dir
            / f"{self._safe_component(evidence_id)}.json"
        )

        await asyncio.to_thread(
            self._atomic_json_write,
            evidence_path,
            payload,
        )

        logger.debug(
            "[EngineeringPersistence] "
            "Evidence persisted | session_id=%s | evidence_id=%s",
            session_id,
            evidence_id,
        )

        if self.auto_checkpoint:
            try:
                await self.save_session(
                    session,
                    checkpoint=False,
                )
            except Exception:
                logger.exception(
                    "[EngineeringPersistence] "
                    "Session checkpoint after evidence failed"
                )

        return True

    async def load_evidence(
        self,
        session_id: str,
    ) -> tuple[dict[str, Any], ...]:
        """
        Load all persisted evidence for a session.
        """

        normalized = self._normalize_session_id(
            session_id
        )

        directory = (
            self.evidence_root
            / self._safe_component(normalized)
        )

        if not directory.exists():
            return ()

        records: list[dict[str, Any]] = []

        for path in sorted(
            directory.glob("*.json")
        ):
            try:
                payload = await asyncio.to_thread(
                    self._read_json,
                    path,
                )

                if isinstance(payload, dict):
                    records.append(payload)

            except Exception:
                logger.exception(
                    "[EngineeringPersistence] "
                    "Failed to load evidence file: %s",
                    path,
                )

        records.sort(
            key=lambda item: str(
                item.get(
                    "persisted_at",
                    "",
                )
            )
        )

        return tuple(records)

    # ==========================================================
    # Recovery helpers
    # ==========================================================

    async def recoverable_sessions(
        self,
    ) -> tuple[str, ...]:
        """
        Return session IDs that have durable state.

        This does not claim that the sessions are runnable or successful.
        """

        session_ids: set[str] = set()

        for path in self.sessions_root.glob(
            "*.json"
        ):
            session_ids.add(
                path.stem
            )

        for path in self.checkpoints_root.glob(
            "*.json"
        ):
            session_ids.add(
                path.stem
            )

        if self.store is not None:
            store_ids = await self._store_list()

            session_ids.update(
                str(item)
                for item in store_ids
                if str(item).strip()
            )

        return tuple(
            sorted(session_ids)
        )

    async def recover_latest(
        self,
        session_id: str,
    ) -> EngineeringSession | None:
        """
        Restore the latest durable state and its evidence.

        Evidence is reattached to the restored session when the session
        contract supports the operation.
        """

        session = await self.load_session(
            session_id
        )

        if session is None:
            return None

        evidence_records = await self.load_evidence(
            session_id
        )

        self._restore_evidence(
            session,
            evidence_records,
        )

        return session

    # ==========================================================
    # Session snapshot
    # ==========================================================

    def _session_snapshot(
        self,
        session: EngineeringSession,
    ) -> dict[str, Any]:
        """
        Obtain a stable JSON-compatible snapshot from the session.

        Preference order:
            session.snapshot()
            dataclass conversion
            public attribute extraction
        """

        snapshot_method = getattr(
            session,
            "snapshot",
            None,
        )

        if callable(snapshot_method):
            try:
                value = snapshot_method()

                if inspect.isawaitable(value):
                    raise EngineeringPersistenceError(
                        "EngineeringSession.snapshot() must be synchronous."
                    )

                serialized = self._serialize(
                    value
                )

                if isinstance(serialized, dict):
                    return serialized

            except EngineeringPersistenceError:
                raise

            except Exception as exc:
                logger.warning(
                    "[EngineeringPersistence] "
                    "Session snapshot method failed: %s",
                    exc,
                )

        if is_dataclass(session):
            value = asdict(session)

            return self._serialize(
                value
            )

        data: dict[str, Any] = {}

        for name in (
            "session_id",
            "state",
            "phase",
            "requirement",
            "engineering_requirement",
            "knowledge_context",
            "plan",
            "engineering_plan",
            "engineering_task_graph",
            "evidence",
            "metadata",
            "workspace_id",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
            "failure",
            "error",
            "acceptance",
        ):
            if not hasattr(session, name):
                continue

            try:
                data[name] = self._serialize(
                    getattr(session, name)
                )
            except Exception:
                logger.debug(
                    "[EngineeringPersistence] "
                    "Could not serialize session field: %s",
                    name,
                    exc_info=True,
                )

        return data

    def _restore_session(
        self,
        snapshot: Mapping[str, Any],
    ) -> EngineeringSession | None:
        """
        Restore through the authoritative session contract.

        Supported restore styles:
            EngineeringSession.restore(snapshot)
            EngineeringSession.from_snapshot(snapshot)
            EngineeringSession(**snapshot)

        The first available compatible style is used.
        """

        restore_method = getattr(
            EngineeringSession,
            "restore",
            None,
        )

        if callable(restore_method):
            try:
                restored = restore_method(
                    snapshot
                )

                if isinstance(
                    restored,
                    EngineeringSession,
                ):
                    return restored

            except Exception:
                logger.exception(
                    "[EngineeringPersistence] "
                    "EngineeringSession.restore failed"
                )

        from_snapshot = getattr(
            EngineeringSession,
            "from_snapshot",
            None,
        )

        if callable(from_snapshot):
            try:
                restored = from_snapshot(
                    snapshot
                )

                if isinstance(
                    restored,
                    EngineeringSession,
                ):
                    return restored

            except Exception:
                logger.exception(
                    "[EngineeringPersistence] "
                    "EngineeringSession.from_snapshot failed"
                )

        constructor_payload = dict(
            snapshot
        )

        constructor_payload.pop(
            "persistence",
            None,
        )

        try:
            return EngineeringSession(
                **constructor_payload
            )

        except Exception:
            logger.exception(
                "[EngineeringPersistence] "
                "Unable to restore EngineeringSession "
                "from persisted snapshot"
            )

        return None

    # ==========================================================
    # Evidence restoration
    # ==========================================================

    @staticmethod
    def _restore_evidence(
        session: EngineeringSession,
        records: tuple[dict[str, Any], ...],
    ) -> None:
        """
        Restore evidence through the session's canonical evidence API.
        """

        setter = getattr(
            session,
            "set_evidence",
            None,
        )

        if callable(setter):
            try:
                setter(records)
                return
            except Exception:
                logger.exception(
                    "[EngineeringPersistence] "
                    "Session set_evidence failed"
                )

        registry = getattr(
            session,
            "evidence",
            None,
        )

        if isinstance(
            registry,
            list,
        ):
            registry.clear()
            registry.extend(
                records
            )

    # ==========================================================
    # EngineeringStore compatibility
    # ==========================================================

    async def _store_save(
        self,
        session: EngineeringSession,
        snapshot: Mapping[str, Any],
    ) -> None:
        if self.store is None:
            return

        for method_name in (
            "save",
            "save_session",
            "persist",
        ):
            method = getattr(
                self.store,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method(
                    session
                )

                if inspect.isawaitable(result):
                    await result

                return

            except TypeError:
                try:
                    result = method(
                        snapshot
                    )

                    if inspect.isawaitable(result):
                        await result

                    return

                except Exception:
                    logger.exception(
                        "[EngineeringPersistence] "
                        "Store method '%s' failed",
                        method_name,
                    )

            except Exception:
                logger.exception(
                    "[EngineeringPersistence] "
                    "Store method '%s' failed",
                    method_name,
                )

            return

    async def _store_load(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        if self.store is None:
            return None

        for method_name in (
            "load",
            "load_session",
            "restore",
        ):
            method = getattr(
                self.store,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method(
                    session_id
                )

                if inspect.isawaitable(result):
                    result = await result

                if result is None:
                    return None

                if isinstance(
                    result,
                    EngineeringSession,
                ):
                    return self._session_snapshot(
                        result
                    )

                if isinstance(
                    result,
                    Mapping,
                ):
                    return dict(result)

                return None

            except Exception:
                logger.exception(
                    "[EngineeringPersistence] "
                    "Store load method '%s' failed",
                    method_name,
                )

                return None

        return None

    async def _store_list(
        self,
    ) -> tuple[str, ...]:
        if self.store is None:
            return ()

        for method_name in (
            "list",
            "list_sessions",
            "sessions",
        ):
            method = getattr(
                self.store,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method()

                if inspect.isawaitable(result):
                    result = await result

                if isinstance(
                    result,
                    Mapping,
                ):
                    return tuple(
                        str(key)
                        for key in result.keys()
                    )

                if isinstance(
                    result,
                    (list, tuple, set, frozenset),
                ):
                    return tuple(
                        str(item)
                        for item in result
                    )

            except Exception:
                logger.exception(
                    "[EngineeringPersistence] "
                    "Store list method '%s' failed",
                    method_name,
                )

                return ()

        return ()

    # ==========================================================
    # Serialization
    # ==========================================================

    @classmethod
    def _serialize(
        cls,
        value: Any,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            (str, int, float, bool),
        ):
            return value

        if isinstance(
            value,
            Path,
        ):
            return value.as_posix()

        if isinstance(
            value,
            datetime,
        ):
            return value.isoformat()

        if is_dataclass(value):
            return cls._serialize(
                asdict(value)
            )

        if isinstance(
            value,
            Mapping,
        ):
            return {
                str(key): cls._serialize(item)
                for key, item in value.items()
            }

        if isinstance(
            value,
            (list, tuple, set, frozenset),
        ):
            return [
                cls._serialize(item)
                for item in value
            ]

        to_dict = getattr(
            value,
            "to_dict",
            None,
        )

        if callable(to_dict):
            try:
                return cls._serialize(
                    to_dict()
                )
            except Exception:
                pass

        try:
            return str(value)
        except Exception:
            return repr(value)

    # ==========================================================
    # File operations
    # ==========================================================

    @staticmethod
    def _atomic_json_write(
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = path.with_suffix(
            path.suffix + ".tmp"
        )

        text = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )

        temporary.write_text(
            text,
            encoding="utf-8",
        )

        temporary.replace(
            path
        )

    @staticmethod
    def _read_json(
        path: Path,
    ) -> dict[str, Any]:
        text = path.read_text(
            encoding="utf-8"
        )

        payload = json.loads(
            text
        )

        if not isinstance(
            payload,
            dict,
        ):
            raise EngineeringPersistenceError(
                f"Persisted state must be a JSON object: {path}"
            )

        return payload

    # ==========================================================
    # Identity helpers
    # ==========================================================

    @staticmethod
    def _session_id(
        session: EngineeringSession,
    ) -> str:
        value = getattr(
            session,
            "session_id",
            None,
        )

        if value is None:
            value = getattr(
                session,
                "id",
                None,
            )

        return str(
            value or ""
        ).strip()

    @staticmethod
    def _normalize_session_id(
        session_id: str,
    ) -> str:
        value = str(
            session_id
        ).strip()

        if not value:
            raise EngineeringPersistenceError(
                "session_id cannot be empty."
            )

        return EngineeringPersistence._safe_component(
            value
        )

    def _session_path(
        self,
        session_id: str,
    ) -> Path:
        return (
            self.sessions_root
            / f"{self._safe_component(session_id)}.json"
        )

    @staticmethod
    def _safe_component(
        value: str,
    ) -> str:
        text = str(
            value
        ).strip()

        if not text:
            return "unknown"

        allowed = (
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789"
            "-_."
        )

        sanitized = "".join(
            char
            if char in allowed
            else "_"
            for char in text
        )

        return sanitized[:180]

    @staticmethod
    def _generated_evidence_id() -> str:
        return (
            "evidence-"
            + datetime.now(
                timezone.utc
            ).strftime(
                "%Y%m%d%H%M%S%f"
            )
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()


# ==========================================================
# Authoritative compatibility alias
# ==========================================================

# The authoritative integration layer uses this name while the
# underlying implementation remains EngineeringPersistence.
#
# Both names intentionally reference the SAME persistence engine.
# This avoids creating a duplicate persistence architecture.
AuthoritativeEngineeringPersistence = EngineeringPersistence


__all__ = [
    "EngineeringPersistence",
    "AuthoritativeEngineeringPersistence",
    "EngineeringPersistenceError",
]