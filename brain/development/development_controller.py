"""
ARIA Development Controller.

High-level lifecycle controller for ARIA's self-development system.

Responsibilities:
    - accept development requirements
    - create development jobs
    - prevent concurrent development jobs
    - invoke DevelopmentAgent
    - retain current/last development state
    - retain a bounded development history
    - expose safe status information
    - normalize development failures

This module does NOT:
    - generate code directly
    - write files directly
    - execute shell commands directly
    - commit directly
    - push to GitHub
    - deploy production directly

DevelopmentAgent remains the execution boundary for the actual
development workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .development_agent import (
    DevelopmentAgent,
    DevelopmentReport,
)


# ======================================================================
# Time helpers
# ======================================================================


def _utc_now() -> str:
    """
    Return the current UTC timestamp in ISO-8601 format.
    """

    return datetime.now(
        timezone.utc
    ).isoformat()


# ======================================================================
# Development job
# ======================================================================


@dataclass(frozen=True)
class DevelopmentJob:
    """
    Immutable record representing one development job.

    Status values currently used:

        queued
        running
        completed
        failed
        blocked
    """

    job_id: str

    requirement: str

    created_at: str

    status: str = "queued"

    report: DevelopmentReport | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> dict[str, Any]:
        """
        Convert the job into a JSON-safe dictionary.
        """

        report_dict = None

        if self.report is not None:

            try:

                report_dict = (
                    self.report.to_dict()
                )

            except Exception:

                report_dict = {
                    "success": bool(
                        getattr(
                            self.report,
                            "success",
                            False,
                        )
                    ),
                    "status": str(
                        getattr(
                            self.report,
                            "status",
                            "unknown",
                        )
                    ),
                }

        return {
            "job_id": self.job_id,
            "requirement": self.requirement,
            "created_at": self.created_at,
            "status": self.status,
            "report": report_dict,
            "metadata": dict(
                self.metadata
            ),
        }


# ======================================================================
# Development controller
# ======================================================================


class DevelopmentController:
    """
    High-level controller for ARIA's development system.

    The controller provides one controlled entry point:

        execute(requirement)

    The controller intentionally allows only one development job at a
    time because DevelopmentAgent operates against a repository and
    development workspace. Concurrent self-modification would make
    workspace state, repair attempts, Git state, and rollback evidence
    ambiguous.

    The controller does not decide whether production deployment is
    allowed. That responsibility belongs to the development/deployment
    policy layers.
    """

    # ------------------------------------------------------------------
    # History limit
    # ------------------------------------------------------------------

    DEFAULT_HISTORY_LIMIT = 20

    # ------------------------------------------------------------------
    # Maximum metadata error size
    # ------------------------------------------------------------------

    MAX_ERROR_LENGTH = 2000

    # ==================================================================
    # Initialization
    # ==================================================================

    def __init__(
        self,
        agent: DevelopmentAgent,
        *,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:

        if agent is None:
            raise ValueError(
                "agent is required."
            )

        self.agent = agent

        self.history_limit = max(
            1,
            int(history_limit),
        )

        # --------------------------------------------------------------
        # Runtime state.
        # --------------------------------------------------------------

        self._active = False

        self._current_job: DevelopmentJob | None = None

        self._last_job: DevelopmentJob | None = None

        self._history: list[
            DevelopmentJob
        ] = []

        self._counter = 0

    # ==================================================================
    # Job ID
    # ==================================================================

    def _next_job_id(
        self,
    ) -> str:
        """
        Generate a process-local development job ID.

        The counter ensures uniqueness when multiple jobs start within
        the same second.
        """

        self._counter += 1

        timestamp = datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%d%H%M%S"
        )

        return (
            "devjob-"
            f"{timestamp}-"
            f"{self._counter:04d}"
        )

    # ==================================================================
    # Execute
    # ==================================================================

    async def execute(
        self,
        requirement: str,
        *,
        changes: list[
            tuple[str, str]
        ] | None = None,
        test_paths: list[str] | None = None,
        workspace_id: str | None = None,
    ) -> DevelopmentJob:
        """
        Execute one development job.

        Args:
            requirement:
                Master's development requirement.

            changes:
                Optional explicitly supplied file/content changes.
                DevelopmentAgent remains responsible for validating
                and applying them.

            test_paths:
                Optional targeted test paths.

            workspace_id:
                Optional existing development workspace ID.

        Returns:
            DevelopmentJob

        Raises:
            RuntimeError:
                If another development job is already running.

            TypeError:
                If requirement is not a string.

            ValueError:
                If requirement is empty.
        """

        # --------------------------------------------------------------
        # Concurrency gate.
        # --------------------------------------------------------------

        if self._active:

            current_id = (
                self._current_job.job_id
                if self._current_job is not None
                else "unknown"
            )

            raise RuntimeError(
                "Another development job is already "
                f"running ({current_id})."
            )

        # --------------------------------------------------------------
        # Validate requirement.
        # --------------------------------------------------------------

        if not isinstance(
            requirement,
            str,
        ):

            raise TypeError(
                "requirement must be a string."
            )

        normalized_requirement = (
            requirement.strip()
        )

        if not normalized_requirement:

            raise ValueError(
                "requirement cannot be empty."
            )

        # --------------------------------------------------------------
        # Validate optional inputs before creating a job.
        # --------------------------------------------------------------

        normalized_changes = (
            self._normalize_changes(
                changes
            )
        )

        normalized_test_paths = (
            self._normalize_test_paths(
                test_paths
            )
        )

        normalized_workspace_id = (
            self._normalize_workspace_id(
                workspace_id
            )
        )

        # --------------------------------------------------------------
        # Create running job.
        # --------------------------------------------------------------

        job = DevelopmentJob(
            job_id=self._next_job_id(),
            requirement=normalized_requirement,
            created_at=_utc_now(),
            status="running",
            metadata={
                "started_at": _utc_now(),
            },
        )

        self._current_job = job

        self._active = True

        try:

            # ----------------------------------------------------------
            # Delegate actual development.
            # ----------------------------------------------------------

            report = await self.agent.develop(
                normalized_requirement,
                changes=normalized_changes,
                test_paths=normalized_test_paths,
                workspace_id=normalized_workspace_id,
            )

            # ----------------------------------------------------------
            # Defensive report validation.
            # ----------------------------------------------------------

            if not isinstance(
                report,
                DevelopmentReport,
            ):

                raise TypeError(
                    "DevelopmentAgent returned an invalid "
                    "development report."
                )

            # ----------------------------------------------------------
            # Determine final status.
            # ----------------------------------------------------------

            final_status = (
                "completed"
                if bool(
                    report.success
                )
                else "failed"
            )

            # ----------------------------------------------------------
            # Preserve useful report metadata.
            # ----------------------------------------------------------

            final_metadata = {
                "started_at": job.metadata.get(
                    "started_at"
                ),
                "completed_at": _utc_now(),
                "workspace_id": (
                    normalized_workspace_id
                    if normalized_workspace_id
                    else None
                ),
            }

            # Remove None values to keep status compact.
            final_metadata = {
                key: value
                for key, value in final_metadata.items()
                if value is not None
            }

            final_job = DevelopmentJob(
                job_id=job.job_id,
                requirement=job.requirement,
                created_at=job.created_at,
                status=final_status,
                report=report,
                metadata=final_metadata,
            )

            # ----------------------------------------------------------
            # Persist state.
            # ----------------------------------------------------------

            self._last_job = final_job

            self._record_history(
                final_job
            )

            self._current_job = None

            return final_job

        except Exception as exc:

            # ----------------------------------------------------------
            # Preserve a bounded error.
            # ----------------------------------------------------------

            error_text = self._bounded_error(
                exc
            )

            failed_job = DevelopmentJob(
                job_id=job.job_id,
                requirement=job.requirement,
                created_at=job.created_at,
                status="failed",
                metadata={
                    "started_at": job.metadata.get(
                        "started_at"
                    ),
                    "completed_at": _utc_now(),
                    "error": error_text,
                    "error_type": type(
                        exc
                    ).__name__,
                },
            )

            self._last_job = failed_job

            self._record_history(
                failed_job
            )

            self._current_job = None

            # ----------------------------------------------------------
            # Preserve existing controller behavior:
            # callers receive the exception, while last_job/status
            # still contain a useful failure record.
            # ----------------------------------------------------------

            raise

        finally:

            self._active = False

            # ----------------------------------------------------------
            # Never leave a stale current job after an unexpected
            # exception.
            #
            # If the normal success/failure path already cleared it,
            # this is a no-op.
            # ----------------------------------------------------------

            if (
                self._current_job is not None
                and self._current_job.job_id
                == job.job_id
            ):

                self._current_job = None

    # ==================================================================
    # Change normalization
    # ==================================================================

    @staticmethod
    def _normalize_changes(
        changes: list[
            tuple[str, str]
        ] | None,
    ) -> list[
        tuple[str, str]
    ] | None:
        """
        Validate and normalize optional explicit changes.

        The controller does not inspect or execute their contents.
        """

        if changes is None:
            return None

        if not isinstance(
            changes,
            list,
        ):
            raise TypeError(
                "changes must be a list of "
                "(path, content) tuples."
            )

        normalized: list[
            tuple[str, str]
        ] = []

        for index, item in enumerate(
            changes
        ):

            if not isinstance(
                item,
                (tuple, list),
            ):
                raise TypeError(
                    "Change at index "
                    f"{index} must be a tuple/list."
                )

            if len(item) != 2:
                raise ValueError(
                    "Each change must contain "
                    "(path, content)."
                )

            path, content = item

            if not isinstance(
                path,
                str,
            ):
                raise TypeError(
                    "Change path must be a string."
                )

            if not isinstance(
                content,
                str,
            ):
                raise TypeError(
                    "Change content must be a string."
                )

            path = path.strip()

            if not path:
                raise ValueError(
                    "Change path cannot be empty."
                )

            normalized.append(
                (
                    path,
                    content,
                )
            )

        return normalized

    # ==================================================================
    # Test-path normalization
    # ==================================================================

    @staticmethod
    def _normalize_test_paths(
        test_paths: list[str] | None,
    ) -> list[str] | None:
        """
        Normalize explicitly supplied executable test paths.

        Empty strings are removed.

        Natural-language acceptance criteria should NOT be supplied
        here. They belong to Requirement.acceptance_criteria.
        """

        if test_paths is None:
            return None

        if not isinstance(
            test_paths,
            list,
        ):
            raise TypeError(
                "test_paths must be a list of strings."
            )

        normalized: list[str] = []

        for path in test_paths:

            if not isinstance(
                path,
                str,
            ):
                raise TypeError(
                    "Each test path must be a string."
                )

            clean = path.strip()

            if not clean:
                continue

            normalized.append(
                clean
            )

        # Stable deduplication.
        return list(
            dict.fromkeys(
                normalized
            )
        )

    # ==================================================================
    # Workspace normalization
    # ==================================================================

    @staticmethod
    def _normalize_workspace_id(
        workspace_id: str | None,
    ) -> str | None:
        """
        Normalize an optional workspace identifier.
        """

        if workspace_id is None:
            return None

        if not isinstance(
            workspace_id,
            str,
        ):
            raise TypeError(
                "workspace_id must be a string or None."
            )

        clean = workspace_id.strip()

        if not clean:
            return None

        return clean

    # ==================================================================
    # History
    # ==================================================================

    def _record_history(
        self,
        job: DevelopmentJob,
    ) -> None:
        """
        Store a bounded development history.

        History is process-local in this phase. Persistent learning
        storage can be connected later without changing the public
        controller API.
        """

        self._history.append(
            job
        )

        if len(
            self._history
        ) > self.history_limit:

            excess = (
                len(
                    self._history
                )
                - self.history_limit
            )

            del self._history[
                :excess
            ]

    def history(
        self,
    ) -> list[
        DevelopmentJob
    ]:
        """
        Return a snapshot of the bounded job history.
        """

        return list(
            self._history
        )

    def history_dicts(
        self,
    ) -> list[
        dict[str, Any]
    ]:
        """
        Return a JSON-safe development history.
        """

        return [
            job.to_dict()
            for job in self._history
        ]

    # ==================================================================
    # State access
    # ==================================================================

    def is_running(
        self,
    ) -> bool:
        """
        Return whether a development job is currently running.
        """

        return self._active

    def current_job(
        self,
    ) -> DevelopmentJob | None:
        """
        Return the currently running job, if any.
        """

        return self._current_job

    def last_job(
        self,
    ) -> DevelopmentJob | None:
        """
        Return the most recently completed/failed job.
        """

        return self._last_job

    # ==================================================================
    # Status
    # ==================================================================

    def status(
        self,
    ) -> dict[str, Any]:
        """
        Return a bounded controller status snapshot.
        """

        current = (
            self._current_job.to_dict()
            if self._current_job is not None
            else None
        )

        last = (
            self._last_job.to_dict()
            if self._last_job is not None
            else None
        )

        return {
            "active": self._active,
            "current_job": current,
            "last_job": last,
            "history_count": len(
                self._history
            ),
            "history_limit": self.history_limit,
        }

    # ==================================================================
    # Safe error handling
    # ==================================================================

    @classmethod
    def _bounded_error(
        cls,
        exc: Exception,
    ) -> str:
        """
        Convert an exception into bounded diagnostic text.

        This prevents huge exception payloads from being stored in
        job metadata.
        """

        try:

            text = str(
                exc
            ).strip()

        except Exception:

            text = ""

        if not text:

            text = type(
                exc
            ).__name__

        return text[
            : cls.MAX_ERROR_LENGTH
        ]


__all__ = [
    "DevelopmentJob",
    "DevelopmentController",
]