from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .development_agent import (
    DevelopmentAgent,
    DevelopmentReport,
)


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


@dataclass(frozen=True)
class DevelopmentJob:
    job_id: str
    requirement: str
    created_at: str
    status: str = "queued"
    report: DevelopmentReport | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "requirement": self.requirement,
            "created_at": self.created_at,
            "status": self.status,
            "report": (
                self.report.to_dict()
                if self.report
                else None
            ),
            "metadata": dict(
                self.metadata
            ),
        }


class DevelopmentController:
    """
    High-level controller for ARIA's development system.

    Responsibilities:

    - create development jobs
    - prevent concurrent development jobs
    - invoke DevelopmentAgent
    - retain the latest development result
    - expose status information

    It does NOT perform Git operations or deployment.
    """

    def __init__(
        self,
        agent: DevelopmentAgent,
    ) -> None:

        self.agent = agent

        self._active = False
        self._current_job: DevelopmentJob | None = None
        self._last_job: DevelopmentJob | None = None

        self._counter = 0

    def _next_job_id(self) -> str:
        self._counter += 1

        timestamp = datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%d%H%M%S"
        )

        return (
            f"devjob-"
            f"{timestamp}-"
            f"{self._counter:04d}"
        )

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

        if self._active:

            raise RuntimeError(
                "Another development job "
                "is already running."
            )

        if not isinstance(
            requirement,
            str,
        ):

            raise TypeError(
                "requirement must be a string."
            )

        if not requirement.strip():

            raise ValueError(
                "requirement cannot be empty."
            )

        job = DevelopmentJob(
            job_id=self._next_job_id(),
            requirement=requirement.strip(),
            created_at=_utc_now(),
            status="running",
        )

        self._current_job = job
        self._active = True

        try:

            report = await self.agent.develop(
                requirement.strip(),
                changes=changes,
                test_paths=test_paths,
                workspace_id=workspace_id,
            )

            final_job = DevelopmentJob(
                job_id=job.job_id,
                requirement=job.requirement,
                created_at=job.created_at,
                status=(
                    "completed"
                    if report.success
                    else "failed"
                ),
                report=report,
                metadata={
                    "completed_at": _utc_now(),
                },
            )

            self._last_job = final_job
            self._current_job = None

            return final_job

        except Exception as exc:

            failed_job = DevelopmentJob(
                job_id=job.job_id,
                requirement=job.requirement,
                created_at=job.created_at,
                status="failed",
                metadata={
                    "completed_at": _utc_now(),
                    "error": str(exc),
                },
            )

            self._last_job = failed_job
            self._current_job = None

            raise

        finally:

            self._active = False

    def is_running(self) -> bool:
        return self._active

    def current_job(
        self,
    ) -> DevelopmentJob | None:

        return self._current_job

    def last_job(
        self,
    ) -> DevelopmentJob | None:

        return self._last_job

    def status(self) -> dict[str, Any]:

        return {
            "active": self._active,
            "current_job": (
                self._current_job.to_dict()
                if self._current_job
                else None
            ),
            "last_job": (
                self._last_job.to_dict()
                if self._last_job
                else None
            ),
        }