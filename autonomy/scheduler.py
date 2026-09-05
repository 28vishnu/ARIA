import logging
import asyncio
import uuid
from datetime import datetime
from typing import Callable, Coroutine, Optional, Dict, Any

logger = logging.getLogger("aria")


class BackgroundScheduler:
    """
    Phase 4 autonomous scheduler.

    Supports:
    - recurring background jobs
    - one-time delayed jobs
    - autonomous-goal monitoring jobs
    - job tracking
    - cancellation
    - graceful shutdown
    """

    def __init__(self):
        self.tasks = []
        self.jobs: Dict[str, Dict[str, Any]] = {}

    # =========================================================
    # RECURRING JOBS
    # =========================================================

    def schedule_recurring(
        self,
        interval_seconds: float,
        coro_func: Callable[..., Coroutine],
        *args,
        goal_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Schedule a recurring background maintenance or
        autonomous-goal monitoring job.
        """

        if interval_seconds <= 0:
            raise ValueError(
                "interval_seconds must be greater than 0"
            )

        job_id = str(uuid.uuid4())

        async def _wrapper():
            logger.info(
                "[BackgroundScheduler] Started recurring job: %s",
                job_id,
            )

            while True:
                try:
                    await asyncio.sleep(interval_seconds)

                    if job_id not in self.jobs:
                        break

                    await coro_func(*args, **kwargs)

                    job = self.jobs.get(job_id)

                    if job:
                        job["last_run"] = datetime.utcnow()
                        job["run_count"] += 1

                except asyncio.CancelledError:
                    logger.info(
                        "[BackgroundScheduler] Recurring job "
                        "cancelled: %s",
                        job_id,
                    )
                    break

                except Exception as exc:
                    logger.exception(
                        "[BackgroundScheduler] Error in recurring "
                        "job %s: %s",
                        job_id,
                        exc,
                    )

        task = asyncio.create_task(_wrapper())

        self.tasks.append(task)

        self.jobs[job_id] = {
            "id": job_id,
            "type": "recurring",
            "interval_seconds": interval_seconds,
            "goal_id": goal_id,
            "task": task,
            "created_at": datetime.utcnow(),
            "last_run": None,
            "run_count": 0,
            "status": "scheduled",
        }

        logger.info(
            "[BackgroundScheduler] Scheduled recurring job "
            "%s | interval=%.1fs | goal=%s",
            job_id,
            interval_seconds,
            goal_id,
        )

        return job_id

    # =========================================================
    # ONE-TIME JOBS
    # =========================================================

    def schedule_once(
        self,
        delay_seconds: float,
        coro_func: Callable[..., Coroutine],
        *args,
        goal_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Schedule a one-time autonomous task.
        """

        if delay_seconds < 0:
            raise ValueError(
                "delay_seconds cannot be negative"
            )

        job_id = str(uuid.uuid4())

        async def _wrapper():
            try:
                await asyncio.sleep(delay_seconds)

                if job_id not in self.jobs:
                    return

                self.jobs[job_id]["status"] = "running"

                await coro_func(*args, **kwargs)

                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = "completed"
                    self.jobs[job_id]["last_run"] = datetime.utcnow()
                    self.jobs[job_id]["run_count"] += 1

            except asyncio.CancelledError:
                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = "cancelled"

                logger.info(
                    "[BackgroundScheduler] One-time job "
                    "cancelled: %s",
                    job_id,
                )

            except Exception as exc:
                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = "failed"
                    self.jobs[job_id]["error"] = str(exc)

                logger.exception(
                    "[BackgroundScheduler] Error in one-time "
                    "job %s: %s",
                    job_id,
                    exc,
                )

        task = asyncio.create_task(_wrapper())

        self.tasks.append(task)

        self.jobs[job_id] = {
            "id": job_id,
            "type": "once",
            "delay_seconds": delay_seconds,
            "goal_id": goal_id,
            "task": task,
            "created_at": datetime.utcnow(),
            "last_run": None,
            "run_count": 0,
            "status": "scheduled",
        }

        logger.info(
            "[BackgroundScheduler] Scheduled one-time job "
            "%s | delay=%.1fs | goal=%s",
            job_id,
            delay_seconds,
            goal_id,
        )

        return job_id

    # =========================================================
    # MONITORING
    # =========================================================

    def schedule_goal_monitor(
        self,
        goal_id: str,
        interval_seconds: float,
        monitor_func: Callable[..., Coroutine],
        *args,
        **kwargs,
    ) -> str:
        """
        Schedule recurring monitoring for an autonomous goal.
        """

        if not goal_id:
            raise ValueError(
                "goal_id is required for goal monitoring"
            )

        return self.schedule_recurring(
            interval_seconds,
            monitor_func,
            *args,
            goal_id=goal_id,
            **kwargs,
        )

    # =========================================================
    # JOB MANAGEMENT
    # =========================================================

    def get_job(
        self,
        job_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return scheduler metadata for a job."""

        job = self.jobs.get(job_id)

        if not job:
            return None

        return {
            key: value
            for key, value in job.items()
            if key != "task"
        }

    def list_jobs(self):
        """Return all scheduler jobs."""

        return [
            self.get_job(job_id)
            for job_id in list(self.jobs.keys())
        ]

    def list_goal_jobs(
        self,
        goal_id: str,
    ):
        """Return jobs associated with an autonomous goal."""

        return [
            self.get_job(job_id)
            for job_id, job in self.jobs.items()
            if job.get("goal_id") == goal_id
        ]

    # =========================================================
    # CANCELLATION
    # =========================================================

    def cancel_job(
        self,
        job_id: str,
    ) -> bool:
        """Cancel a scheduled job."""

        job = self.jobs.get(job_id)

        if not job:
            return False

        task = job.get("task")

        if task and not task.done():
            task.cancel()

        job["status"] = "cancelled"

        logger.info(
            "[BackgroundScheduler] Cancelled job: %s",
            job_id,
        )

        return True

    def cancel_goal_jobs(
        self,
        goal_id: str,
    ) -> int:
        """Cancel every scheduled job belonging to a goal."""

        cancelled = 0

        for job_id, job in list(self.jobs.items()):
            if job.get("goal_id") != goal_id:
                continue

            if self.cancel_job(job_id):
                cancelled += 1

        return cancelled

    # =========================================================
    # SHUTDOWN
    # =========================================================

    async def shutdown(self):
        """Gracefully stop all scheduler jobs."""

        active_tasks = [
            task
            for task in self.tasks
            if task and not task.done()
        ]

        for task in active_tasks:
            task.cancel()

        if active_tasks:
            await asyncio.gather(
                *active_tasks,
                return_exceptions=True,
            )

        for job in self.jobs.values():
            if job.get("status") not in {
                "completed",
                "failed",
                "cancelled",
            }:
                job["status"] = "cancelled"

        self.tasks.clear()

        logger.info(
            "[BackgroundScheduler] Scheduler shutdown complete."
        )