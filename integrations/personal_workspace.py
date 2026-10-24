"""Owner-scoped persistent workspace APIs for ARIA.

Stores projects, notes, tasks, and declarative reusable workflows in SQLite.
All records are scoped to the authenticated ARIA owner. Workflow execution is
intentionally restricted to safe workspace operations; it cannot execute code
or trigger external account actions.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/workspace", tags=["ARIA personal workspace"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db_path() -> str:
    return (os.getenv("ARIA_WORKSPACE_DB_PATH") or "/var/data/aria_workspace.sqlite3").strip()


def _connect(path: str | None = None) -> sqlite3.Connection:
    target = path or _db_path()
    if target != ":memory:":
        Path(target).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    _initialize(conn)
    return conn


def _initialize(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS workspace_projects (
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_workspace_projects_owner_updated
      ON workspace_projects(owner_id, updated_at DESC);
    CREATE TABLE IF NOT EXISTS workspace_notes (
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, title TEXT NOT NULL,
      content TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_workspace_notes_owner_updated
      ON workspace_notes(owner_id, updated_at DESC);
    CREATE TABLE IF NOT EXISTS workspace_tasks (
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
      priority TEXT NOT NULL DEFAULT 'normal', due_at TEXT, created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_workspace_tasks_owner_status
      ON workspace_tasks(owner_id, status, updated_at DESC);
    CREATE TABLE IF NOT EXISTS workspace_workflows (
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '', steps_json TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_workspace_workflows_owner
      ON workspace_workflows(owner_id, updated_at DESC);
    CREATE TABLE IF NOT EXISTS workspace_workflow_runs (
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, workflow_id TEXT NOT NULL,
      status TEXT NOT NULL, result_json TEXT NOT NULL,
      created_at TEXT NOT NULL, finished_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_workspace_runs_owner_created
      ON workspace_workflow_runs(owner_id, created_at DESC);
    CREATE TABLE IF NOT EXISTS workspace_research_reports (
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, title TEXT NOT NULL,
      query TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL,
      sources_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_workspace_research_owner_created
      ON workspace_research_reports(owner_id, created_at DESC);
    """)
    conn.commit()


def initialize_database(path: str | None = None) -> None:
    conn = _connect(path)
    conn.close()


def _owner(request: Request) -> str:
    owner = getattr(request.state, "aria_owner", None)
    if not owner:
        raise HTTPException(status_code=401, detail="Authenticated ARIA owner session required.")
    return str(owner)


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    status: Literal["active", "paused", "completed", "archived"] = "active"


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=100000)
    tags: list[str] = Field(default_factory=list, max_length=30)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=8000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    due_at: str | None = Field(default=None, max_length=80)


class TaskUpdate(BaseModel):
    status: Literal["open", "in_progress", "blocked", "completed", "cancelled"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=8000)
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    due_at: str | None = Field(default=None, max_length=80)


class ResearchReportCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    query: str = Field(default="", max_length=2000)
    summary: str = Field(min_length=1, max_length=100000)
    sources: list[dict[str, str]] = Field(default_factory=list, max_length=100)


class WorkflowStep(BaseModel):
    action: Literal["create_task", "create_note", "list_open_tasks"]
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=100000)
    description: str | None = Field(default=None, max_length=8000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=20)


def _create_task(conn: sqlite3.Connection, owner: str, data: dict[str, Any]) -> dict[str, Any]:
    now, task_id = _now(), str(uuid.uuid4())
    conn.execute("""INSERT INTO workspace_tasks
      (id,owner_id,title,description,status,priority,due_at,created_at,updated_at)
      VALUES (?,?,?,?,?,?,?,?,?)""",
      (task_id, owner, data["title"].strip(), data.get("description", ""), "open",
       data.get("priority", "normal"), data.get("due_at"), now, now))
    return _row(conn.execute("SELECT * FROM workspace_tasks WHERE id=?", (task_id,)).fetchone()) or {}


@router.get("/overview")
def workspace_overview(request: Request) -> dict[str, Any]:
    owner = _owner(request)
    conn = _connect()
    try:
        counts = {}
        for key, table, where in (
            ("projects", "workspace_projects", ""), ("notes", "workspace_notes", ""),
            ("tasks_open", "workspace_tasks", " AND status IN ('open','in_progress','blocked')"),
            ("tasks_completed", "workspace_tasks", " AND status='completed'"),
            ("workflows", "workspace_workflows", ""),
        ):
            counts[key] = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE owner_id=?{where}", (owner,)).fetchone()[0]
        recent_tasks = [dict(r) for r in conn.execute(
            "SELECT * FROM workspace_tasks WHERE owner_id=? ORDER BY updated_at DESC LIMIT 10", (owner,)
        ).fetchall()]
        return {"service": "ARIA personal workspace", "counts": counts, "recent_tasks": recent_tasks}
    finally:
        conn.close()


@router.get("/projects")
def list_projects(request: Request, limit: int = 50) -> dict[str, Any]:
    owner = _owner(request)
    if not 1 <= limit <= 100: raise HTTPException(422, "limit must be between 1 and 100")
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM workspace_projects WHERE owner_id=? ORDER BY updated_at DESC LIMIT ?", (owner, limit)).fetchall()
        return {"projects": [dict(r) for r in rows]}
    finally: conn.close()


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, request: Request) -> dict[str, Any]:
    owner, now, project_id = _owner(request), _now(), str(uuid.uuid4())
    conn = _connect()
    try:
        conn.execute("INSERT INTO workspace_projects VALUES (?,?,?,?,?,?,?)", (project_id, owner, body.name.strip(), body.description, body.status, now, now))
        conn.commit()
        return dict(conn.execute("SELECT * FROM workspace_projects WHERE id=?", (project_id,)).fetchone())
    finally: conn.close()


@router.get("/notes")
def list_notes(request: Request, limit: int = 50) -> dict[str, Any]:
    owner = _owner(request)
    if not 1 <= limit <= 100: raise HTTPException(422, "limit must be between 1 and 100")
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM workspace_notes WHERE owner_id=? ORDER BY updated_at DESC LIMIT ?", (owner, limit)).fetchall()
        result = []
        for row in rows:
            item = dict(row); item["tags"] = json.loads(item.pop("tags_json")); result.append(item)
        return {"notes": result}
    finally: conn.close()


@router.post("/notes", status_code=201)
def create_note(body: NoteCreate, request: Request) -> dict[str, Any]:
    owner, now, note_id = _owner(request), _now(), str(uuid.uuid4())
    tags = list(dict.fromkeys(t.strip()[:60] for t in body.tags if t.strip()))
    conn = _connect()
    try:
        conn.execute("INSERT INTO workspace_notes VALUES (?,?,?,?,?,?,?)", (note_id, owner, body.title.strip(), body.content, json.dumps(tags), now, now))
        conn.commit()
        item = dict(conn.execute("SELECT * FROM workspace_notes WHERE id=?", (note_id,)).fetchone())
        item["tags"] = json.loads(item.pop("tags_json"))
        return item
    finally: conn.close()


@router.get("/tasks")
def list_tasks(request: Request, status: str | None = None, limit: int = 100) -> dict[str, Any]:
    owner = _owner(request)
    allowed = {"open", "in_progress", "blocked", "completed", "cancelled"}
    if status is not None and status not in allowed: raise HTTPException(422, "Invalid task status")
    if not 1 <= limit <= 200: raise HTTPException(422, "limit must be between 1 and 200")
    conn = _connect()
    try:
        if status:
            rows = conn.execute("SELECT * FROM workspace_tasks WHERE owner_id=? AND status=? ORDER BY updated_at DESC LIMIT ?", (owner, status, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM workspace_tasks WHERE owner_id=? ORDER BY updated_at DESC LIMIT ?", (owner, limit)).fetchall()
        return {"tasks": [dict(r) for r in rows]}
    finally: conn.close()


@router.post("/tasks", status_code=201)
def create_task(body: TaskCreate, request: Request) -> dict[str, Any]:
    owner = _owner(request); conn = _connect()
    try:
        task = _create_task(conn, owner, body.model_dump()); conn.commit(); return task
    finally: conn.close()


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: TaskUpdate, request: Request) -> dict[str, Any]:
    owner = _owner(request); updates = body.model_dump(exclude_unset=True)
    if not updates: raise HTTPException(400, "Provide at least one field to update")
    if "title" in updates and updates["title"] is not None: updates["title"] = updates["title"].strip()
    updates["updated_at"] = _now()
    conn = _connect()
    try:
        cursor = conn.execute("SELECT id FROM workspace_tasks WHERE id=? AND owner_id=?", (task_id, owner))
        if cursor.fetchone() is None: raise HTTPException(404, "Task not found")
        columns = ",".join(f"{column}=?" for column in updates)
        conn.execute(f"UPDATE workspace_tasks SET {columns} WHERE id=? AND owner_id=?", (*updates.values(), task_id, owner))
        conn.commit()
        return dict(conn.execute("SELECT * FROM workspace_tasks WHERE id=? AND owner_id=?", (task_id, owner)).fetchone())
    finally: conn.close()


@router.get("/workflows")
def list_workflows(request: Request) -> dict[str, Any]:
    owner = _owner(request); conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM workspace_workflows WHERE owner_id=? ORDER BY updated_at DESC", (owner,)).fetchall()
        result = []
        for row in rows:
            item = dict(row); item["steps"] = json.loads(item.pop("steps_json")); result.append(item)
        return {"workflows": result, "allowed_actions": ["create_task", "create_note", "list_open_tasks"]}
    finally: conn.close()


@router.post("/workflows", status_code=201)
def create_workflow(body: WorkflowCreate, request: Request) -> dict[str, Any]:
    owner, now, workflow_id = _owner(request), _now(), str(uuid.uuid4())
    steps = [step.model_dump() for step in body.steps]
    for step in steps:
        if step["action"] in {"create_task", "create_note"} and not (step.get("title") or "").strip():
            raise HTTPException(422, f"The {step['action']} workflow step requires a title")
    conn = _connect()
    try:
        conn.execute("INSERT INTO workspace_workflows VALUES (?,?,?,?,?,?,?)", (workflow_id, owner, body.name.strip(), body.description, json.dumps(steps), now, now))
        conn.commit()
        return {"id": workflow_id, "owner_id": owner, "name": body.name.strip(), "description": body.description, "steps": steps, "created_at": now, "updated_at": now}
    finally: conn.close()


@router.post("/workflows/{workflow_id}/run")
def run_workflow(workflow_id: str, request: Request) -> dict[str, Any]:
    """Run only the allowlisted local workspace actions; no arbitrary code or external writes."""
    owner, run_id, started = _owner(request), str(uuid.uuid4()), _now()
    conn = _connect()
    results: list[dict[str, Any]] = []
    try:
        row = conn.execute("SELECT * FROM workspace_workflows WHERE id=? AND owner_id=?", (workflow_id, owner)).fetchone()
        if row is None: raise HTTPException(404, "Workflow not found")
        steps = json.loads(row["steps_json"])
        conn.execute("INSERT INTO workspace_workflow_runs VALUES (?,?,?,?,?, ?,NULL)", (run_id, owner, workflow_id, "running", "[]", started))
        conn.commit()
        try:
            for index, step in enumerate(steps):
                action = step["action"]
                if action == "create_task":
                    item = _create_task(conn, owner, {"title": step["title"], "description": step.get("description") or "", "priority": step.get("priority", "normal")})
                    results.append({"step": index, "action": action, "success": True, "task_id": item["id"]})
                elif action == "create_note":
                    now, note_id = _now(), str(uuid.uuid4())
                    conn.execute("INSERT INTO workspace_notes VALUES (?,?,?,?,?,?,?)", (note_id, owner, step["title"].strip(), step.get("content") or "", "[]", now, now))
                    results.append({"step": index, "action": action, "success": True, "note_id": note_id})
                elif action == "list_open_tasks":
                    count = conn.execute("SELECT COUNT(*) FROM workspace_tasks WHERE owner_id=? AND status IN ('open','in_progress','blocked')", (owner,)).fetchone()[0]
                    results.append({"step": index, "action": action, "success": True, "open_task_count": count})
                else:  # Defensive guard against corrupted stored workflows.
                    raise ValueError("Unsupported workflow action")
            finished, status = _now(), "completed"
        except Exception:
            conn.rollback()
            finished, status = _now(), "failed"
            results.append({"success": False, "error": "Workflow step failed; changes from this run were rolled back."})
        conn.execute("UPDATE workspace_workflow_runs SET status=?,result_json=?,finished_at=? WHERE id=? AND owner_id=?", (status, json.dumps(results), finished, run_id, owner))
        conn.commit()
        return {"run_id": run_id, "workflow_id": workflow_id, "status": status, "results": results, "started_at": started, "finished_at": finished}
    finally: conn.close()


@router.get("/research-reports")
def list_research_reports(request: Request, limit: int = 50) -> dict[str, Any]:
    owner = _owner(request)
    if not 1 <= limit <= 100: raise HTTPException(422, "limit must be between 1 and 100")
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM workspace_research_reports WHERE owner_id=? ORDER BY created_at DESC LIMIT ?", (owner, limit)).fetchall()
        reports = []
        for row in rows:
            item = dict(row); item["sources"] = json.loads(item.pop("sources_json")); reports.append(item)
        return {"reports": reports}
    finally: conn.close()


@router.post("/research-reports", status_code=201)
def save_research_report(body: ResearchReportCreate, request: Request) -> dict[str, Any]:
    owner, report_id, created = _owner(request), str(uuid.uuid4()), _now()
    safe_sources = []
    for source in body.sources:
        title = (source.get("title") or "").strip()[:300]
        url = (source.get("url") or "").strip()[:2000]
        if url and not url.startswith(("https://", "http://")):
            raise HTTPException(422, "Research source URLs must use HTTP or HTTPS")
        safe_sources.append({"title": title, "url": url})
    conn = _connect()
    try:
        conn.execute("INSERT INTO workspace_research_reports VALUES (?,?,?,?,?,?,?)", (report_id, owner, body.title.strip(), body.query.strip(), body.summary, json.dumps(safe_sources), created))
        conn.commit()
        return {"id": report_id, "owner_id": owner, "title": body.title.strip(), "query": body.query.strip(), "summary": body.summary, "sources": safe_sources, "created_at": created}
    finally: conn.close()


@router.get("/workflow-runs")
def list_workflow_runs(request: Request, limit: int = 50) -> dict[str, Any]:
    owner = _owner(request)
    if not 1 <= limit <= 100: raise HTTPException(422, "limit must be between 1 and 100")
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM workspace_workflow_runs WHERE owner_id=? ORDER BY created_at DESC LIMIT ?", (owner, limit)).fetchall()
        result = []
        for row in rows:
            item = dict(row); item["results"] = json.loads(item.pop("result_json")); result.append(item)
        return {"runs": result}
    finally: conn.close()


__all__ = ["router", "initialize_database", "workspace_overview", "create_project", "list_projects", "create_note", "list_notes", "create_task", "list_tasks", "update_task", "create_workflow", "list_workflows", "run_workflow", "save_research_report", "list_research_reports", "list_workflow_runs"]
