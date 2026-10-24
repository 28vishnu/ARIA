"""Durable, opt-in proactive task store for ARIA.

This module deliberately separates persisted schedules from execution and delivery.
Callers supply an async handler and optional async notifier; no external service is
contacted and no notification is claimed delivered unless the notifier succeeds.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("aria.proactive")
AsyncHandler = Callable[[dict[str, Any]], Awaitable[Any]]
AsyncNotifier = Callable[[str, dict[str, Any]], Awaitable[Any]]


class ProactiveTaskStore:
    """SQLite-backed one-shot and interval task store with safe claim semantics."""

    def __init__(self, database_path: str | Path = "data/aria_proactive.sqlite3"):
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS proactive_tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('once','interval')),
                payload_json TEXT NOT NULL,
                due_at REAL NOT NULL,
                interval_seconds REAL,
                enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'scheduled',
                run_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_proactive_due ON proactive_tasks(enabled, status, due_at)")

    def schedule_once(self, title: str, due_at: float, payload: Optional[dict[str, Any]] = None) -> str:
        return self._schedule(title, "once", float(due_at), None, payload or {})

    def schedule_interval(self, title: str, first_due_at: float, interval_seconds: float,
                          payload: Optional[dict[str, Any]] = None) -> str:
        interval = float(interval_seconds)
        if interval < 60:
            raise ValueError("interval_seconds must be at least 60 seconds")
        return self._schedule(title, "interval", float(first_due_at), interval, payload or {})

    def _schedule(self, title: str, kind: str, due_at: float, interval: Optional[float], payload: dict[str, Any]) -> str:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        if due_at < 0:
            raise ValueError("due_at must be a Unix timestamp >= 0")
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be JSON-serializable") from exc
        now = time.time()
        task_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute("INSERT INTO proactive_tasks(id,title,kind,payload_json,due_at,interval_seconds,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                         (task_id, title.strip(), kind, encoded, due_at, interval, now, now))
        return task_id

    def list_tasks(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM proactive_tasks" + ("" if include_disabled else " WHERE enabled=1") + " ORDER BY due_at,id"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        item["enabled"] = bool(item["enabled"])
        return item

    def cancel(self, task_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("UPDATE proactive_tasks SET enabled=0,status='cancelled',updated_at=? WHERE id=? AND enabled=1",
                               (time.time(), task_id))
            return cur.rowcount == 1

    def _claim_due(self, now: float, limit: int) -> list[dict[str, Any]]:
        # BEGIN IMMEDIATE ensures multiple workers don't claim the same due rows.
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT * FROM proactive_tasks WHERE enabled=1 AND status='scheduled' AND due_at<=? ORDER BY due_at LIMIT ?", (now, limit)).fetchall()
            ids = [row["id"] for row in rows]
            for task_id in ids:
                conn.execute("UPDATE proactive_tasks SET status='running',updated_at=? WHERE id=? AND status='scheduled'", (now, task_id))
            conn.commit()
            return [self._row(row) for row in rows]
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _finish(self, task: dict[str, Any], success: bool, error: Optional[str], now: float) -> None:
        with self._connect() as conn:
            if task["kind"] == "interval" and task["enabled"]:
                # Skip missed intervals rather than creating a burst after downtime.
                # The enabled predicate preserves a cancellation made while the task ran.
                next_due = max(float(task["due_at"]) + float(task["interval_seconds"]), now + float(task["interval_seconds"]))
                conn.execute("UPDATE proactive_tasks SET status='scheduled',due_at=?,run_count=run_count+?,failure_count=failure_count+?,last_error=?,updated_at=? WHERE id=? AND enabled=1",
                             (next_due, int(success), int(not success), error, now, task["id"]))
            else:
                conn.execute("UPDATE proactive_tasks SET status=?,enabled=0,run_count=run_count+?,failure_count=failure_count+?,last_error=?,updated_at=? WHERE id=?",
                             ("completed" if success else "failed", int(success), int(not success), error, now, task["id"]))

    async def run_due(self, handler: AsyncHandler, notifier: Optional[AsyncNotifier] = None,
                      *, now: Optional[float] = None, limit: int = 20) -> dict[str, int]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        claimed = self._claim_due(time.time() if now is None else float(now), limit)
        succeeded = failed = 0
        for task in claimed:
            try:
                result = await handler(task)
                if notifier is not None:
                    # Handler may return a message; otherwise notify only task metadata.
                    message = result if isinstance(result, str) else task["title"]
                    await notifier(message, task)
                self._finish(task, True, None, time.time())
                succeeded += 1
            except asyncio.CancelledError:
                # Make the task eligible for a later retry after worker cancellation.
                with self._connect() as conn:
                    conn.execute("UPDATE proactive_tasks SET status='scheduled',updated_at=? WHERE id=? AND status='running'", (time.time(), task["id"]))
                raise
            except Exception as exc:
                logger.exception("Proactive task failed: %s", task["id"])
                self._finish(task, False, str(exc)[:1000], time.time())
                failed += 1
        return {"claimed": len(claimed), "succeeded": succeeded, "failed": failed}


class ProactiveAgent:
    """Small polling runner; lifecycle is controlled by the hosting application."""
    def __init__(self, store: ProactiveTaskStore, handler: AsyncHandler,
                 notifier: Optional[AsyncNotifier] = None, poll_interval_seconds: float = 15.0):
        if poll_interval_seconds < 1:
            raise ValueError("poll_interval_seconds must be at least 1")
        self.store = store
        self.handler = handler
        self.notifier = notifier
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._stop = asyncio.Event()

    async def run(self) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            await self.store.run_due(self.handler, self.notifier)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()


class MongoProactiveTaskStore:
    """MongoDB-backed implementation of the ProactiveTaskStore interface.

    Uses PyMongo's atomic find_one_and_update for cross-process task claiming.
    This stores task state in MongoDB, so it survives Render instance replacement
    when the MongoDB deployment itself is durable and reachable.
    """

    def __init__(self, mongo_uri: str, database_name: str = "aria_db",
                 collection_name: str = "proactive_tasks", *, server_selection_timeout_ms: int = 5000):
        if not isinstance(mongo_uri, str) or not mongo_uri.strip():
            raise ValueError("mongo_uri must be a non-empty MongoDB URI")
        try:
            from pymongo import MongoClient, ASCENDING, ReturnDocument
        except ImportError as exc:  # pragma: no cover - depends on deployment environment
            raise RuntimeError("MongoDB proactive storage requires pymongo; add pymongo to requirements.txt") from exc
        self._return_document = ReturnDocument
        self._client = MongoClient(mongo_uri, serverSelectionTimeoutMS=server_selection_timeout_ms,
                                   connectTimeoutMS=server_selection_timeout_ms)
        self._client.admin.command("ping")
        self._collection = self._client[database_name][collection_name]
        self._collection.create_index([("enabled", ASCENDING), ("status", ASCENDING), ("due_at", ASCENDING)])
        self._collection.create_index([("id", ASCENDING)], unique=True)

    def close(self) -> None:
        self._client.close()

    def schedule_once(self, title: str, due_at: float, payload: Optional[dict[str, Any]] = None) -> str:
        return self._schedule(title, "once", float(due_at), None, payload or {})

    def schedule_interval(self, title: str, first_due_at: float, interval_seconds: float,
                          payload: Optional[dict[str, Any]] = None) -> str:
        interval = float(interval_seconds)
        if interval < 60:
            raise ValueError("interval_seconds must be at least 60 seconds")
        return self._schedule(title, "interval", float(first_due_at), interval, payload or {})

    def _schedule(self, title: str, kind: str, due_at: float, interval: Optional[float], payload: dict[str, Any]) -> str:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        if due_at < 0:
            raise ValueError("due_at must be a Unix timestamp >= 0")
        try:
            json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be JSON-serializable") from exc
        now = time.time()
        task_id = str(uuid.uuid4())
        self._collection.insert_one({
            "id": task_id, "title": title.strip(), "kind": kind, "payload": payload,
            "due_at": due_at, "interval_seconds": interval, "enabled": True,
            "status": "scheduled", "run_count": 0, "failure_count": 0,
            "last_error": None, "created_at": now, "updated_at": now,
        })
        return task_id

    def list_tasks(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        query = {} if include_disabled else {"enabled": True}
        rows = self._collection.find(query, {"_id": 0}).sort([("due_at", 1), ("id", 1)])
        return [dict(row) for row in rows]

    def cancel(self, task_id: str) -> bool:
        result = self._collection.update_one(
            {"id": task_id, "enabled": True},
            {"$set": {"enabled": False, "status": "cancelled", "updated_at": time.time()}},
        )
        return result.modified_count == 1

    def _claim_due(self, now: float, limit: int) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        for _ in range(limit):
            row = self._collection.find_one_and_update(
                {"enabled": True, "status": "scheduled", "due_at": {"$lte": now}},
                {"$set": {"status": "running", "updated_at": now}},
                sort=[("due_at", 1), ("id", 1)],
                return_document=self._return_document.BEFORE,
                projection={"_id": 0},
            )
            if row is None:
                break
            claimed.append(dict(row))
        return claimed

    def _finish(self, task: dict[str, Any], success: bool, error: Optional[str], now: float) -> None:
        common = {"last_error": error, "updated_at": now}
        increments = {"run_count": int(success), "failure_count": int(not success)}
        if task["kind"] == "interval" and task["enabled"]:
            next_due = max(float(task["due_at"]) + float(task["interval_seconds"]),
                           now + float(task["interval_seconds"]))
            self._collection.update_one(
                {"id": task["id"], "enabled": True},
                {"$set": {**common, "status": "scheduled", "due_at": next_due}, "$inc": increments},
            )
        else:
            self._collection.update_one(
                {"id": task["id"]},
                {"$set": {**common, "status": "completed" if success else "failed", "enabled": False},
                 "$inc": increments},
            )

    async def run_due(self, handler: AsyncHandler, notifier: Optional[AsyncNotifier] = None,
                      *, now: Optional[float] = None, limit: int = 20) -> dict[str, int]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        claimed = self._claim_due(time.time() if now is None else float(now), limit)
        succeeded = failed = 0
        for task in claimed:
            try:
                result = await handler(task)
                if notifier is not None:
                    message = result if isinstance(result, str) else task["title"]
                    await notifier(message, task)
                self._finish(task, True, None, time.time())
                succeeded += 1
            except asyncio.CancelledError:
                self._collection.update_one(
                    {"id": task["id"], "status": "running"},
                    {"$set": {"status": "scheduled", "updated_at": time.time()}},
                )
                raise
            except Exception as exc:
                logger.exception("Proactive task failed: %s", task["id"])
                self._finish(task, False, str(exc)[:1000], time.time())
                failed += 1
        return {"claimed": len(claimed), "succeeded": succeeded, "failed": failed}
