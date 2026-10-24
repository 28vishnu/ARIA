from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from integrations import personal_workspace as workspace
from integrations import verified_automation as automation


def request_for(owner=None):
    return SimpleNamespace(state=SimpleNamespace(aria_owner=owner))


def setup_db(monkeypatch, tmp_path):
    path = tmp_path / "workspace.sqlite3"
    monkeypatch.setenv("ARIA_WORKSPACE_DB_PATH", str(path))
    workspace.initialize_database(str(path))
    return path


def test_execute_plan_verifies_each_write_and_persists_run(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    body = automation.AutomationRequest(
        goal="Prepare project kickoff",
        idempotency_key="kickoff-run-0001",
        steps=[
            automation.AutomationStep(action="create_task", title="Define milestones", priority="high"),
            automation.AutomationStep(action="create_note", title="Kickoff", content="Agree on scope"),
            automation.AutomationStep(action="list_open_tasks"),
        ],
    )
    result = automation.execute_automation(body, request_for("alice"))
    assert result["status"] == "completed"
    assert all(step["success"] and step["verified"] for step in result["results"])
    assert len(workspace.list_tasks(request_for("alice"))["tasks"]) == 1
    assert len(workspace.list_notes(request_for("alice"))["notes"]) == 1
    assert automation.list_automation_runs(request_for("alice"))["runs"][0]["status"] == "completed"


def test_idempotency_key_prevents_duplicate_side_effects(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    body = automation.AutomationRequest(
        goal="Create task", idempotency_key="same-request-0001",
        steps=[automation.AutomationStep(action="create_task", title="One task")],
    )
    first = automation.execute_automation(body, request_for("alice"))
    second = automation.execute_automation(body, request_for("alice"))
    assert first["run_id"] == second["run_id"]
    assert second["idempotent_replay"] is True
    assert len(workspace.list_tasks(request_for("alice"))["tasks"]) == 1


def test_dry_run_has_no_workspace_side_effects(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    body = automation.AutomationRequest(
        goal="Preview task", idempotency_key="dry-run-key-0001", dry_run=True,
        steps=[automation.AutomationStep(action="create_task", title="Preview only")],
    )
    result = automation.execute_automation(body, request_for("alice"))
    assert result["status"] == "dry_run"
    assert workspace.list_tasks(request_for("alice"))["tasks"] == []


def test_runs_are_owner_scoped_and_auth_required(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    body = automation.AutomationRequest(
        goal="Private run", idempotency_key="private-run-0001",
        steps=[automation.AutomationStep(action="list_open_tasks")],
    )
    automation.execute_automation(body, request_for("alice"))
    assert automation.list_automation_runs(request_for("bob"))["runs"] == []
    with pytest.raises(HTTPException) as exc:
        automation.list_automation_runs(request_for())
    assert exc.value.status_code == 401


def test_plan_validation_rejects_missing_required_title(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    body = automation.AutomationRequest(
        goal="Invalid", idempotency_key="invalid-plan-0001",
        steps=[automation.AutomationStep(action="create_task")],
    )
    with pytest.raises(HTTPException) as exc:
        automation.execute_automation(body, request_for("alice"))
    assert exc.value.status_code == 422


def test_automation_routes_are_registered():
    from main import app
    paths = {route.path for route in app.routes}
    assert {"/automation/execute", "/automation/runs"}.issubset(paths)
