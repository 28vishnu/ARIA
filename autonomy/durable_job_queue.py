"""Mongo-backed durable queue for named, JSON-serializable background jobs.

Handlers are registered by stable name at startup. Jobs are stored in MongoDB,
claimed atomically, and can be recovered after a process restart. A handler must
be idempotent: a process can fail after performing its side effect but before
marking the job complete, so exactly-once side effects cannot be guaranteed by
any queue alone.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger("aria")
JobHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class DurableJobQueue:
    def __init__(self, collection=None, *, max_attempts: int = 5, lease_seconds: int = 300):
        self.collection = collection
        self.max_attempts = max(1, int(max_attempts))
        self.lease_seconds = max(30, int(lease_seconds))
        self.handlers: dict[str, JobHandler] = {}
        self._worker_lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self.collection is not None

    def register_handler(self, name: str, handler: JobHandler) -> None:
        if not name or not isinstance(name, str):
            raise ValueError("handler name must be a non-empty string")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self.handlers[name] = handler

    async def enqueue(self, handler_name: str, payload: dict[str, Any], *, job_id: str | None = None) -> str:
        if self.collection is None:
            raise RuntimeError("Durable job storage is unavailable; configure MongoDB.")
        if handler_name not in self.handlers:
            raise ValueError(f"No handler registered for {handler_name!r}")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        identifier = str(job_id or uuid.uuid4())
        now = datetime.now(timezone.utc)
        document = {
            "_id": identifier,
            "handler": handler_name,
            "payload": payload,
            "status": "pending",
            "attempts": 0,
            "max_attempts": self.max_attempts,
            "created_at": now,
            "updated_at": now,
            "last_error": None,
            "lease_until": None,
        }
        await self.collection.insert_one(document)
        return identifier

    async def run_one(self) -> dict[str, Any] | None:
        """Atomically claim and execute one pending or expired-lease job."""
        if self.collection is None:
            raise RuntimeError("Durable job storage is unavailable; configure MongoDB.")
        if self._worker_lock.locked():
            return None
        async with self._worker_lock:
            now = datetime.now(timezone.utc)
            try:
                from pymongo import ReturnDocument
                after = ReturnDocument.AFTER
            except ImportError:  # pragma: no cover - Motor installs PyMongo
                after = True
            job = await self.collection.find_one_and_update(
                {
                    "attempts": {"$lt": self.max_attempts},
                    "$or": [
                        {"status": "pending"},
                        {"status": "running", "lease_until": {"$lt": now}},
                    ],
                },
                {
                    "$set": {
                        "status": "running",
                        "updated_at": now,
                        "lease_until": datetime.fromtimestamp(now.timestamp() + self.lease_seconds, tz=timezone.utc),
                    },
                    "$inc": {"attempts": 1},
                },
                sort=[("created_at", 1)],
                return_document=after,
            )
            if not job:
                return None
            handler = self.handlers.get(job.get("handler"))
            if handler is None:
                await self.collection.update_one(
                    {"_id": job["_id"]},
                    {"$set": {"status": "failed", "last_error": f"Handler not registered: {job.get('handler')}", "updated_at": datetime.now(timezone.utc), "lease_until": None}},
                )
                return {"id": job["_id"], "status": "failed", "reason": "handler_missing"}
            try:
                result = await handler(job.get("payload") or {})
                await self.collection.update_one(
                    {"_id": job["_id"], "status": "running"},
                    {"$set": {"status": "completed", "result_summary": str(result)[:1000] if result is not None else None, "last_error": None, "updated_at": datetime.now(timezone.utc), "lease_until": None}},
                )
                return {"id": job["_id"], "status": "completed"}
            except asyncio.CancelledError:
                # Leave the lease in place; another worker can recover after expiry.
                raise
            except Exception as exc:
                exhausted = int(job.get("attempts", 1)) >= min(int(job.get("max_attempts", self.max_attempts)), self.max_attempts)
                await self.collection.update_one(
                    {"_id": job["_id"], "status": "running"},
                    {"$set": {"status": "failed" if exhausted else "pending", "last_error": str(exc)[:2000], "updated_at": datetime.now(timezone.utc), "lease_until": None}},
                )
                logger.exception("Durable job %s failed (attempt %s)", job.get("_id"), job.get("attempts"))
                return {"id": job["_id"], "status": "failed" if exhausted else "pending", "attempts": job.get("attempts")}

    async def recover_expired(self) -> int:
        """Make stale running jobs eligible for another worker attempt."""
        if self.collection is None:
            return 0
        now = datetime.now(timezone.utc)
        result = await self.collection.update_many(
            {"status": "running", "lease_until": {"$lt": now}, "attempts": {"$lt": self.max_attempts}},
            {"$set": {"status": "pending", "updated_at": now, "lease_until": None}},
        )
        return int(getattr(result, "modified_count", 0))

    async def status(self) -> dict[str, Any]:
        if self.collection is None:
            return {"available": False, "backend": "none", "durable": False}
        counts = {}
        for state in ("pending", "running", "completed", "failed"):
            counts[state] = await self.collection.count_documents({"status": state})
        return {"available": True, "backend": "mongodb", "durable": True, "counts": counts, "registered_handlers": sorted(self.handlers)}
