"""Phase 6: bounded end-to-end execution with postcondition verification.

Only owner-scoped local workspace operations are available. No shell, Python,
network, OAuth, GitHub write, or arbitrary plugin execution is exposed here.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from integrations.personal_workspace import _connect, _create_task, _now, _owner

router = APIRouter(prefix="/automation", tags=["ARIA verified automation"])
_ALLOWED = {"create_task", "create_note", "list_open_tasks"}
_MAX_STEPS = 20


class AutomationStep(BaseModel):
    action: Literal["create_task", "create_note", "list_open_tasks"]
    title: str | None = Field(default=None, max_length=200)
    description: str = Field(default="", max_length=8000)
    content: str = Field(default="", max_length=100000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"


class AutomationRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    steps: list[AutomationStep] = Field(min_length=1, max_length=_MAX_STEPS)
    idempotency_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    dry_run: bool = False


def _initialize(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS verified_automation_runs (
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
      goal TEXT NOT NULL, status TEXT NOT NULL, plan_json TEXT NOT NULL,
      result_json TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT,
      UNIQUE(owner_id, idempotency_key)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_verified_runs_owner_created ON verified_automation_runs(owner_id, created_at DESC)")
    conn.commit()


def _validate_plan(steps: list[AutomationStep]) -> None:
    for index, step in enumerate(steps):
        if step.action not in _ALLOWED:
            raise HTTPException(422, f"Step {index} uses an unsupported action")
        if step.action in {"create_task", "create_note"} and not (step.title or "").strip():
            raise HTTPException(422, f"Step {index} requires a title")


def _execute_step(conn: sqlite3.Connection, owner: str, step: AutomationStep, index: int) -> dict[str, Any]:
    if step.action == "create_task":
        item = _create_task(conn, owner, {
            "title": (step.title or "").strip(), "description": step.description,
            "priority": step.priority,
        })
        verified = conn.execute(
            "SELECT id,title,status,priority FROM workspace_tasks WHERE id=? AND owner_id=?",
            (item["id"], owner),
        ).fetchone()
        if verified is None or verified["title"] != (step.title or "").strip():
            raise RuntimeError("Task postcondition verification failed")
        return {"step": index, "action": step.action, "success": True, "verified": True, "task": dict(verified)}

    if step.action == "create_note":
        now, note_id = _now(), str(uuid.uuid4())
        conn.execute(
            "INSERT INTO workspace_notes(id,owner_id,title,content,tags_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (note_id, owner, (step.title or "").strip(), step.content, "[]", now, now),
        )
        verified = conn.execute(
            "SELECT id,title,content FROM workspace_notes WHERE id=? AND owner_id=?",
            (note_id, owner),
        ).fetchone()
        if verified is None or verified["title"] != (step.title or "").strip() or verified["content"] != step.content:
            raise RuntimeError("Note postcondition verification failed")
        return {"step": index, "action": step.action, "success": True, "verified": True, "note": dict(verified)}

    if step.action == "list_open_tasks":
        count = conn.execute(
            "SELECT COUNT(*) FROM workspace_tasks WHERE owner_id=? AND status IN ('open','in_progress','blocked')",
            (owner,),
        ).fetchone()[0]
        verified_count = conn.execute(
            "SELECT COUNT(*) FROM workspace_tasks WHERE owner_id=? AND status IN ('open','in_progress','blocked')",
            (owner,),
        ).fetchone()[0]
        if count != verified_count:
            raise RuntimeError("Read postcondition verification failed")
        return {"step": index, "action": step.action, "success": True, "verified": True, "open_task_count": count}

    raise HTTPException(422, "Unsupported automation action")


@router.post("/execute", status_code=200)
def execute_automation(body: AutomationRequest, request: Request) -> dict[str, Any]:
    """Validate, execute, verify, and persist a bounded local workflow."""
    owner = _owner(request)
    _validate_plan(body.steps)
    plan = [step.model_dump() for step in body.steps]
    conn = _connect()
    run_id = str(uuid.uuid4())
    started = _now()
    try:
        _initialize(conn)
        previous = conn.execute(
            "SELECT * FROM verified_automation_runs WHERE owner_id=? AND idempotency_key=?",
            (owner, body.idempotency_key),
        ).fetchone()
        if previous is not None:
            return {
                "run_id": previous["id"], "status": previous["status"],
                "idempotent_replay": True, "goal": previous["goal"],
                "results": json.loads(previous["result_json"]),
                "created_at": previous["created_at"], "finished_at": previous["finished_at"],
            }

        if body.dry_run:
            results = [{"step": i, "action": step.action, "success": True, "verified": False, "dry_run": True}
                       for i, step in enumerate(body.steps)]
            finished = _now()
            conn.execute(
                "INSERT INTO verified_automation_runs VALUES(?,?,?,?,?,?,?,?,?)",
                (run_id, owner, body.idempotency_key, body.goal, "dry_run", json.dumps(plan), json.dumps(results), started, finished),
            )
            conn.commit()
            return {"run_id": run_id, "status": "dry_run", "idempotent_replay": False,
                    "goal": body.goal, "results": results, "created_at": started, "finished_at": finished}

        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO verified_automation_runs VALUES(?,?,?,?,?,?,?,?,?)",
            (run_id, owner, body.idempotency_key, body.goal, "running", json.dumps(plan), "[]", started, None),
        )
        results: list[dict[str, Any]] = []
        try:
            for index, step in enumerate(body.steps):
                results.append(_execute_step(conn, owner, step, index))
            if not all(item.get("success") and item.get("verified") for item in results):
                raise RuntimeError("At least one step did not pass verification")
            status = "completed"
            finished = _now()
            conn.execute(
                "UPDATE verified_automation_runs SET status=?,result_json=?,finished_at=? WHERE id=? AND owner_id=?",
                (status, json.dumps(results), finished, run_id, owner),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            status = "failed"
            finished = _now()
            # Persist a failure record separately after rolling back all workspace writes.
            conn.execute(
                "INSERT INTO verified_automation_runs VALUES(?,?,?,?,?,?,?,?,?)",
                (run_id, owner, body.idempotency_key, body.goal, status, json.dumps(plan),
                 json.dumps([{"success": False, "verified": False,
                              "error": "Execution failed; the workflow transaction was rolled back."}]), started, finished),
            )
            conn.commit()
            results = [{"success": False, "verified": False,
                        "error": "Execution failed; the workflow transaction was rolled back."}]
        return {"run_id": run_id, "status": status, "idempotent_replay": False,
                "goal": body.goal, "results": results, "created_at": started, "finished_at": finished}
    finally:
        conn.close()


@router.get("/runs")
def list_automation_runs(request: Request, limit: int = 50) -> dict[str, Any]:
    owner = _owner(request)
    if not 1 <= limit <= 100:
        raise HTTPException(422, "limit must be between 1 and 100")
    conn = _connect()
    try:
        _initialize(conn)
        rows = conn.execute(
            "SELECT * FROM verified_automation_runs WHERE owner_id=? ORDER BY created_at DESC LIMIT ?",
            (owner, limit),
        ).fetchall()
        return {"runs": [{"run_id": row["id"], "goal": row["goal"], "status": row["status"],
                           "plan": json.loads(row["plan_json"]), "results": json.loads(row["result_json"]),
                           "created_at": row["created_at"], "finished_at": row["finished_at"]}
                          for row in rows]}
    finally:
        conn.close()


__all__ = ["router", "AutomationRequest", "AutomationStep", "execute_automation", "list_automation_runs"]
