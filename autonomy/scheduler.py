import logging
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Callable, Coroutine, Optional, Dict, Any

logger = logging.getLogger("aria")


class BackgroundScheduler:
    """
    Production-ready autonomous scheduler.

    Supports:
    - recurring background jobs
    - one-time delayed jobs
    - autonomous-goal monitoring jobs
    - per-job timeout protection
    - bounded concurrency
    - job tracking and execution history
    - cancellation
    - graceful shutdown
    """

    def __init__(
        self,
        max_concurrent_jobs: int = 5,
        default_timeout_seconds: float = 300.0,
        history_limit: int = 100,
    ):
        self.tasks = set()
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.history = []
        self.max_concurrent_jobs = max(1, int(max_concurrent_jobs))
        self.default_timeout_seconds = max(1.0, float(default_timeout_seconds))
        self.history_limit = max(10, int(history_limit))
        self._semaphore = asyncio.Semaphore(self.max_concurrent_jobs)
        self._shutdown = False

    # =========================================================
    # INTERNAL HELPERS
    # =========================================================

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _track_task(self, task: asyncio.Task) -> None:
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _record_history(self, job: Dict[str, Any]) -> None:
        record = {
            key: value
            for key, value in job.items()
            if key not in {"task", "coro_func", "args", "kwargs"}
        }
        self.history.append(record)
        if len(self.history) > self.history_limit:
            del self.history[:-self.history_limit]

    async def _run_callable(
        self,
        job_id: str,
        coro_func: Callable[..., Coroutine],
        args: tuple,
        kwargs: Dict[str, Any],
        timeout_seconds: float,
    ):
        async with self._semaphore:
            job = self.jobs.get(job_id)
            if not job:
                return

            job["status"] = "running"
            job["last_started"] = self._now()

            try:
                await asyncio.wait_for(
                    coro_func(*args, **kwargs),
                    timeout=timeout_seconds,
                )

                job["run_count"] += 1
                job["last_run"] = self._now()
                job["last_duration_seconds"] = (
                    self._now() - job["last_started"]
                ).total_seconds()
                job["last_error"] = None
                return True

            except asyncio.TimeoutError:
                job["failure_count"] += 1
                job["last_error"] = (
                    f"Job exceeded timeout of "
                    f"{timeout_seconds:.1f} seconds."
                )
                logger.warning(
                    "[BackgroundScheduler] Job timed out: %s",
                    job_id,
                )
                return False

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                job["failure_count"] += 1
                job["last_error"] = str(exc)
                logger.exception(
                    "[BackgroundScheduler] Job execution failed: %s",
                    job_id,
                )
                return False

            finally:
                if job_id in self.jobs:
                    job = self.jobs[job_id]
                    job["status"] = (
                        "scheduled"
                        if job["type"] == "recurring"
                        else job.get("status", "completed")
                    )

    # =========================================================
    # RECURRING JOBS
    # =========================================================

    def schedule_recurring(
        self,
        interval_seconds: float,
        coro_func: Callable[..., Coroutine],
        *args,
        goal_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        run_immediately: bool = False,
        **kwargs,
    ) -> str:
        if self._shutdown:
            raise RuntimeError("Scheduler is shut down.")

        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than 0")

        if not callable(coro_func):
            raise TypeError("coro_func must be callable")

        job_id = str(uuid.uuid4())
        timeout = (
            self.default_timeout_seconds
            if timeout_seconds is None
            else max(1.0, float(timeout_seconds))
        )

        async def _wrapper():
            logger.info(
                "[BackgroundScheduler] Started recurring job: %s",
                job_id,
            )

            first_run = True

            while job_id in self.jobs and not self._shutdown:
                try:
                    if not (run_immediately and first_run):
                        await asyncio.sleep(interval_seconds)

                    first_run = False

                    if job_id not in self.jobs or self._shutdown:
                        break

                    await self._run_callable(
                        job_id,
                        coro_func,
                        args,
                        kwargs,
                        timeout,
                    )

                except asyncio.CancelledError:
                    logger.info(
                        "[BackgroundScheduler] Recurring job cancelled: %s",
                        job_id,
                    )
                    break

                except Exception as exc:
                    logger.exception(
                        "[BackgroundScheduler] Recurring wrapper failed %s: %s",
                        job_id,
                        exc,
                    )

        task = asyncio.create_task(_wrapper())
        self._track_task(task)

        self.jobs[job_id] = {
            "id": job_id,
            "type": "recurring",
            "interval_seconds": interval_seconds,
            "timeout_seconds": timeout,
            "goal_id": goal_id,
            "task": task,
            "created_at": self._now(),
            "last_started": None,
            "last_run": None,
            "last_duration_seconds": None,
            "last_error": None,
            "run_count": 0,
            "failure_count": 0,
            "status": "scheduled",
        }

        logger.info(
            "[BackgroundScheduler] Scheduled recurring job %s | interval=%.1fs",
            job_id,
            interval_seconds,
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
        timeout_seconds: Optional[float] = None,
        **kwargs,
    ) -> str:
        if self._shutdown:
            raise RuntimeError("Scheduler is shut down.")

        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")

        if not callable(coro_func):
            raise TypeError("coro_func must be callable")

        job_id = str(uuid.uuid4())
        timeout = (
            self.default_timeout_seconds
            if timeout_seconds is None
            else max(1.0, float(timeout_seconds))
        )

        async def _wrapper():
            try:
                await asyncio.sleep(delay_seconds)

                if job_id not in self.jobs or self._shutdown:
                    return

                result = await self._run_callable(
                    job_id,
                    coro_func,
                    args,
                    kwargs,
                    timeout,
                )

                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = (
                        "completed" if result else "failed"
                    )
                    self._record_history(self.jobs[job_id])

            except asyncio.CancelledError:
                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = "cancelled"
                    self._record_history(self.jobs[job_id])
                raise

            except Exception as exc:
                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = "failed"
                    self.jobs[job_id]["last_error"] = str(exc)
                    self._record_history(self.jobs[job_id])

                logger.exception(
                    "[BackgroundScheduler] One-time wrapper failed: %s",
                    job_id,
                )

        task = asyncio.create_task(_wrapper())
        self._track_task(task)

        self.jobs[job_id] = {
            "id": job_id,
            "type": "once",
            "delay_seconds": delay_seconds,
            "timeout_seconds": timeout,
            "goal_id": goal_id,
            "task": task,
            "created_at": self._now(),
            "last_started": None,
            "last_run": None,
            "last_duration_seconds": None,
            "last_error": None,
            "run_count": 0,
            "failure_count": 0,
            "status": "scheduled",
        }

        logger.info(
            "[BackgroundScheduler] Scheduled one-time job %s | delay=%.1fs",
            job_id,
            delay_seconds,
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
        if not goal_id:
            raise ValueError("goal_id is required for goal monitoring")

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

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self.jobs.get(job_id)
        if not job:
            return None

        return {
            key: value
            for key, value in job.items()
            if key not in {"task", "coro_func", "args", "kwargs"}
        }

    def list_jobs(self):
        return [
            self.get_job(job_id)
            for job_id in list(self.jobs.keys())
        ]

    def list_goal_jobs(self, goal_id: str):
        return [
            self.get_job(job_id)
            for job_id, job in self.jobs.items()
            if job.get("goal_id") == goal_id
        ]

    def get_history(self):
        return list(self.history)

    # =========================================================
    # CANCELLATION
    # =========================================================

    def cancel_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False

        task = job.get("task")

        if task and not task.done():
            task.cancel()

        job["status"] = "cancelled"
        self._record_history(job)

        logger.info(
            "[BackgroundScheduler] Cancelled job: %s",
            job_id,
        )
        return True

    def cancel_goal_jobs(self, goal_id: str) -> int:
        cancelled = 0

        for job_id, job in list(self.jobs.items()):
            if job.get("goal_id") != goal_id:
                continue

            if self.cancel_job(job_id):
                cancelled += 1

        return cancelled

    # =========================================================
    # STATUS
    # =========================================================

    def status(self) -> Dict[str, Any]:
        active = sum(
            1
            for job in self.jobs.values()
            if job.get("status") in {"scheduled", "running"}
        )

        running = sum(
            1
            for job in self.jobs.values()
            if job.get("status") == "running"
        )

        return {
            "shutdown": self._shutdown,
            "total_jobs": len(self.jobs),
            "active_jobs": active,
            "running_jobs": running,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "history_size": len(self.history),
        }

    # =========================================================
    # SHUTDOWN
    # =========================================================

    async def shutdown(self):
        if self._shutdown:
            return

        self._shutdown = True

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
