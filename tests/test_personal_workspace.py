from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from integrations import personal_workspace as workspace


def request_for(owner=None):
    return SimpleNamespace(state=SimpleNamespace(aria_owner=owner))


def setup_db(monkeypatch, tmp_path):
    path = tmp_path / "workspace.sqlite3"
    monkeypatch.setenv("ARIA_WORKSPACE_DB_PATH", str(path))
    workspace.initialize_database(str(path))
    return path


def test_workspace_requires_authenticated_owner(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as exc:
        workspace.workspace_overview(request_for())
    assert exc.value.status_code == 401


def test_projects_and_notes_are_owner_scoped(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    project = workspace.create_project(workspace.ProjectCreate(name="ARIA", description="assistant"), request_for("alice"))
    note = workspace.create_note(workspace.NoteCreate(title="Idea", content="Persistent notes", tags=["ai", "ai"]), request_for("alice"))
    assert project["name"] == "ARIA"
    assert note["tags"] == ["ai"]
    assert len(workspace.list_projects(request_for("alice"))["projects"]) == 1
    assert workspace.list_projects(request_for("bob"))["projects"] == []
    assert workspace.list_notes(request_for("bob"))["notes"] == []


def test_task_lifecycle_and_owner_isolation(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    task = workspace.create_task(workspace.TaskCreate(title="Ship Phase 5", priority="high"), request_for("alice"))
    assert task["status"] == "open"
    updated = workspace.update_task(task["id"], workspace.TaskUpdate(status="completed"), request_for("alice"))
    assert updated["status"] == "completed"
    with pytest.raises(HTTPException) as exc:
        workspace.update_task(task["id"], workspace.TaskUpdate(status="cancelled"), request_for("bob"))
    assert exc.value.status_code == 404
    assert workspace.list_tasks(request_for("bob"))["tasks"] == []


def test_reusable_workflow_creates_task_and_note_and_persists_run(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    workflow = workspace.create_workflow(
        workspace.WorkflowCreate(name="Start project", steps=[
            workspace.WorkflowStep(action="create_task", title="Define milestones", priority="high"),
            workspace.WorkflowStep(action="create_note", title="Kickoff notes", content="Set goals"),
            workspace.WorkflowStep(action="list_open_tasks"),
        ]), request_for("alice"))
    result = workspace.run_workflow(workflow["id"], request_for("alice"))
    assert result["status"] == "completed"
    assert len(result["results"]) == 3
    assert len(workspace.list_tasks(request_for("alice"))["tasks"]) == 1
    assert len(workspace.list_notes(request_for("alice"))["notes"]) == 1
    assert workspace.list_workflow_runs(request_for("alice"))["runs"][0]["status"] == "completed"


def test_workflow_cannot_be_run_by_another_owner(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    workflow = workspace.create_workflow(
        workspace.WorkflowCreate(name="Private", steps=[workspace.WorkflowStep(action="list_open_tasks")]), request_for("alice"))
    with pytest.raises(HTTPException) as exc:
        workspace.run_workflow(workflow["id"], request_for("bob"))
    assert exc.value.status_code == 404


def test_workflow_rejects_missing_title_for_creation_step(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    body = workspace.WorkflowCreate(name="Bad", steps=[workspace.WorkflowStep(action="create_task")])
    with pytest.raises(HTTPException) as exc:
        workspace.create_workflow(body, request_for("alice"))
    assert exc.value.status_code == 422


def test_workflow_actions_are_allowlisted(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    with pytest.raises(Exception):
        workspace.WorkflowStep.model_validate({"action": "execute_shell", "title": "danger"})


def test_research_report_library_preserves_sources_and_is_private(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    report = workspace.save_research_report(
        workspace.ResearchReportCreate(
            title="Python release notes", query="Python latest release",
            summary="A saved source-backed report.",
            sources=[{"title": "Official docs", "url": "https://docs.python.org/"}],
        ), request_for("alice"))
    assert report["sources"][0]["title"] == "Official docs"
    assert workspace.list_research_reports(request_for("alice"))["reports"][0]["id"] == report["id"]
    assert workspace.list_research_reports(request_for("bob"))["reports"] == []


def test_research_report_rejects_non_http_source_urls(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as exc:
        workspace.save_research_report(
            workspace.ResearchReportCreate(title="Bad source", summary="Summary", sources=[{"url": "file:///etc/passwd"}]),
            request_for("alice"))
    assert exc.value.status_code == 422
