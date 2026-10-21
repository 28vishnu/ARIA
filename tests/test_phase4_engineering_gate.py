from __future__ import annotations

from pathlib import Path

import pytest

from brain.development.phase4_engineering_gate import EngineeringChangeGate


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return repo


def test_stage_changes_only_in_workspace_and_returns_diff(tmp_path):
    repo = make_repo(tmp_path)
    original = (repo / "app.py").read_text(encoding="utf-8")
    gate = EngineeringChangeGate(repo, workspace_base=tmp_path / "workspaces")

    report = gate.stage({"app.py": "VALUE = 2\n"})

    assert report.status == "staged"
    assert report.ready_for_review
    assert report.workspace_id
    assert "VALUE = 2" in report.diff
    assert len(report.patch_sha256) == 64
    assert report.metadata["source_unchanged"] is True
    assert (repo / "app.py").read_text(encoding="utf-8") == original
    staged = tmp_path / "workspaces" / report.workspace_id / "repo" / "app.py"
    assert staged.read_text(encoding="utf-8") == "VALUE = 2\n"
    gate.destroy(report.workspace_id)


@pytest.mark.parametrize("path", ["../outside.txt", "/tmp/outside.txt", "C:\\outside.txt", "a/../../b.py"])
def test_rejects_path_traversal(tmp_path, path):
    repo = make_repo(tmp_path)
    gate = EngineeringChangeGate(repo, workspace_base=tmp_path / "workspaces")
    report = gate.stage({path: "x"})
    assert report.status == "rejected"
    assert report.errors
    assert not (tmp_path / "outside.txt").exists()


def test_sensitive_files_are_always_blocked(tmp_path):
    repo = make_repo(tmp_path)
    gate = EngineeringChangeGate(repo, workspace_base=tmp_path / "workspaces")
    report = gate.stage({".env": "TOKEN=not-real"})
    assert report.status == "rejected"
    assert ".env" in report.blocked_files
    assert not (repo / ".env").exists()


def test_operational_files_require_explicit_approval(tmp_path):
    repo = make_repo(tmp_path)
    gate = EngineeringChangeGate(repo, workspace_base=tmp_path / "workspaces")
    rejected = gate.stage({"Dockerfile": "FROM python:3.11\n"})
    assert rejected.status == "rejected"
    assert "Dockerfile" in rejected.requires_approval

    accepted = gate.stage(
        {"Dockerfile": "FROM python:3.11\n"},
        approved_paths=["Dockerfile"],
    )
    assert accepted.status == "staged"
    assert accepted.metadata["source_unchanged"] is True
    gate.destroy(accepted.workspace_id)


def test_python_syntax_error_fails_review_readiness(tmp_path):
    repo = make_repo(tmp_path)
    gate = EngineeringChangeGate(repo, workspace_base=tmp_path / "workspaces")
    report = gate.stage({"app.py": "def broken(:\n  pass\n"})
    assert report.status == "validation_failed"
    assert not report.ready_for_review
    assert report.syntax_errors
    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    gate.destroy(report.workspace_id)


def test_rejects_oversized_changes_before_creating_workspace(tmp_path):
    repo = make_repo(tmp_path)
    gate = EngineeringChangeGate(
        repo, workspace_base=tmp_path / "workspaces",
        max_file_bytes=4, max_total_bytes=8,
    )
    report = gate.stage({"new.txt": "too long"})
    assert report.status == "rejected"
    assert report.errors
    assert not (tmp_path / "workspaces").exists()


def test_rejects_empty_change_set(tmp_path):
    repo = make_repo(tmp_path)
    gate = EngineeringChangeGate(repo, workspace_base=tmp_path / "workspaces")
    report = gate.stage({})
    assert report.status == "rejected"
    assert report.errors


def test_validation_runs_pytest_only_inside_workspace(tmp_path):
    import asyncio

    repo = make_repo(tmp_path)
    gate = EngineeringChangeGate(repo, workspace_base=tmp_path / "workspaces")
    report = gate.stage({"app.py": "VALUE = 2\n"})
    validation = asyncio.run(
        gate.validate(report.workspace_id, test_paths=["tests/test_app.py"])
    )
    assert validation["status"] == "passed", validation
    assert validation["passed"] is True
    assert validation["tests_passed"] is True
    assert validation["production_deployment"] is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    gate.destroy(report.workspace_id)
