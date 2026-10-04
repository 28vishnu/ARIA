"""Persistent storage contract for ARIA autonomous engineering sessions.

Step 5 provides durable persistence for:
- engineering session snapshots
- immutable evidence
- lifecycle transitions
- recovery/resume information

This module deliberately contains no repository editing, command execution,
deployment, GitHub push, or autonomous decision-making.

The store is filesystem-backed by default so it can work without introducing
a new database dependency. Later steps may place a higher-level persistence
adapter in front of it without changing the session contract.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any

from .engineering_evidence import EngineeringEvidence
from .engineering_session import EngineeringSession


class EngineeringStoreError(RuntimeError):
    """Base error for engineering persistence failures."""


class EngineeringSessionNotFound(
    EngineeringStoreError
):
    """Raised when a requested engineering session does not exist."""


class EngineeringStore:
    """Durable filesystem store for autonomous engineering sessions.

    Storage layout:

        <root>/
            <session_id>/
                session.json

    Writes use a temporary file followed by an atomic replace so a process
    interruption cannot normally leave a half-written session snapshot.
    """

    VERSION = "PHASE1-ENGINEERING-STORE-20261004"
    SESSION_FILENAME = "session.json"

    def __init__(
        self,
        root: str | os.PathLike[str],
    ) -> None:
        resolved_root = Path(root).expanduser()

        self._root = resolved_root
        self._lock = RLock()

        self._root.mkdir(
            parents=True,
            exist_ok=True,
        )

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def save(
        self,
        session: EngineeringSession,
    ) -> Path:
        """Persist the complete current session snapshot."""

        if not isinstance(
            session,
            EngineeringSession,
        ):
            raise TypeError(
                "session must be an EngineeringSession."
            )

        snapshot = session.snapshot()

        session_id = self._safe_session_id(
            session.session_id
        )

        destination_directory = (
            self._root / session_id
        )

        destination_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination = (
            destination_directory
            / self.SESSION_FILENAME
        )

        self._atomic_write_json(
            destination,
            snapshot,
        )

        return destination

    def load(
        self,
        session_id: str,
    ) -> EngineeringSession:
        """Restore a persisted engineering session."""

        path = self.session_path(
            session_id
        )

        if not path.is_file():
            raise EngineeringSessionNotFound(
                f"Engineering session not found: {session_id}"
            )

        try:
            payload = self._read_json(
                path
            )
        except Exception as exc:
            raise EngineeringStoreError(
                "Unable to read engineering session "
                f"{session_id}: {exc}"
            ) from exc

        try:
            return EngineeringSession.from_snapshot(
                payload
            )
        except Exception as exc:
            raise EngineeringStoreError(
                "Unable to restore engineering session "
                f"{session_id}: {exc}"
            ) from exc

    def exists(
        self,
        session_id: str,
    ) -> bool:
        return self.session_path(
            session_id
        ).is_file()

    def delete(
        self,
        session_id: str,
    ) -> bool:
        """Delete one persisted session.

        This is intentionally explicit and never called automatically by the
        engineering lifecycle.
        """

        session_directory = self.session_directory(
            session_id
        )

        if not session_directory.exists():
            return False

        if not session_directory.is_dir():
            raise EngineeringStoreError(
                "Session storage path is not a directory: "
                f"{session_directory}"
            )

        for child in session_directory.iterdir():
            if child.is_file():
                child.unlink()

        session_directory.rmdir()

        return True

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_session_ids(self) -> tuple[str, ...]:
        """Return persisted session IDs in deterministic order."""

        if not self._root.exists():
            return ()

        session_ids: list[str] = []

        for child in self._root.iterdir():
            if not child.is_dir():
                continue

            if not (
                child / self.SESSION_FILENAME
            ).is_file():
                continue

            session_ids.append(
                child.name
            )

        return tuple(
            sorted(session_ids)
        )

    def session_path(
        self,
        session_id: str,
    ) -> Path:
        return (
            self.session_directory(
                session_id
            )
            / self.SESSION_FILENAME
        )

    def session_directory(
        self,
        session_id: str,
    ) -> Path:
        safe_id = self._safe_session_id(
            session_id
        )

        return self._root / safe_id

    # ------------------------------------------------------------------
    # Evidence access
    # ------------------------------------------------------------------

    def evidence(
        self,
        session_id: str,
        evidence_id: str,
    ) -> EngineeringEvidence | None:
        """Retrieve immutable evidence from a persisted session."""

        session = self.load(
            session_id
        )

        return session.evidence(
            evidence_id
        )

    def evidence_by_kind(
        self,
        session_id: str,
        kind: str,
    ) -> tuple[EngineeringEvidence, ...]:
        """Retrieve persisted evidence of one category."""

        session = self.load(
            session_id
        )

        return session.evidence_by_kind(
            kind
        )

    # ------------------------------------------------------------------
    # Export / diagnostics
    # ------------------------------------------------------------------

    def export_snapshot(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        """Return the exact persisted snapshot."""

        session = self.load(
            session_id
        )

        return session.snapshot()

    def health(
        self,
    ) -> dict[str, Any]:
        """Return persistence health information."""

        try:
            self._root.mkdir(
                parents=True,
                exist_ok=True,
            )

            writable = os.access(
                self._root,
                os.W_OK,
            )
        except OSError as exc:
            return {
                "healthy": False,
                "version": self.VERSION,
                "root": str(self._root),
                "writable": False,
                "error": str(exc),
            }

        return {
            "healthy": bool(writable),
            "version": self.VERSION,
            "root": str(self._root),
            "writable": bool(writable),
            "sessions": len(
                self.list_session_ids()
            ),
        }

    # ------------------------------------------------------------------
    # Internal persistence
    # ------------------------------------------------------------------

    def _atomic_write_json(
        self,
        destination: Path,
        payload: dict[str, Any],
    ) -> None:
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fd: int | None = None
        temporary_path: Path | None = None

        try:
            fd, temporary_name = (
                tempfile.mkstemp(
                    prefix=".session-",
                    suffix=".tmp",
                    dir=str(
                        destination.parent
                    ),
                )
            )

            temporary_path = Path(
                temporary_name
            )

            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=self._json_default,
            )

            with os.fdopen(
                fd,
                "w",
                encoding="utf-8",
            ) as handle:
                fd = None

                handle.write(
                    serialized
                )
                handle.write("\n")
                handle.flush()
                os.fsync(
                    handle.fileno()
                )

            os.replace(
                temporary_path,
                destination,
            )

            temporary_path = None

        except Exception as exc:
            raise EngineeringStoreError(
                "Unable to persist engineering session: "
                f"{exc}"
            ) from exc

        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

            if (
                temporary_path is not None
                and temporary_path.exists()
            ):
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _read_json(
        path: Path,
    ) -> dict[str, Any]:
        with path.open(
            "r",
            encoding="utf-8",
        ) as handle:
            payload = json.load(
                handle
            )

        if not isinstance(
            payload,
            dict,
        ):
            raise EngineeringStoreError(
                "Persisted session root must be a JSON object."
            )

        return payload

    @staticmethod
    def _json_default(
        value: Any,
    ) -> Any:
        if hasattr(
            value,
            "value",
        ):
            return value.value

        if isinstance(
            value,
            Path,
        ):
            return str(value)

        raise TypeError(
            f"Object is not JSON serializable: "
            f"{type(value).__name__}"
        )

    @staticmethod
    def _safe_session_id(
        session_id: str,
    ) -> str:
        value = str(
            session_id
        ).strip()

        if not value:
            raise ValueError(
                "session_id must not be empty."
            )

        if value in {".", ".."}:
            raise ValueError(
                "Invalid session_id."
            )

        if "/" in value or "\\" in value:
            raise ValueError(
                "session_id must not contain path separators."
            )

        if "\x00" in value:
            raise ValueError(
                "session_id must not contain NUL bytes."
            )

        return value


__all__ = [
    "EngineeringStore",
    "EngineeringStoreError",
    "EngineeringSessionNotFound",
]