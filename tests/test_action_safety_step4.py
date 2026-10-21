import asyncio
import os
from pathlib import Path

import pytest

from actions.base import ActionResult, BaseAction
from actions.manager import ActionManager
from actions.permissions import PermissionManager
import actions.actions.file as file_module
from actions.actions.file import FileAction


class DummyAction(BaseAction):
    name = "dummy"
    description = "Test action"
    permission_level = "safe"
    timeout_seconds = 1

    def __init__(self, permission_level="safe"):
        self.permission_level = permission_level
        self.calls = 0

    async def validate(self, params):
        return True

    async def execute(self, params):
        self.calls += 1
        return ActionResult(True, self.name, data={"ok": True})


@pytest.mark.parametrize("mode", ["locked", "strict", "confirm"])
def test_unknown_permission_fails_closed(mode):
    manager = PermissionManager(mode)
    assert manager.evaluate("x", "mystery") == "deny"


@pytest.mark.asyncio
async def test_safe_action_executes_and_confirm_action_requires_confirmation():
    manager = ActionManager(permission_mode="autonomous")
    safe = DummyAction("safe")
    guarded = DummyAction("confirm")
    guarded.name = "guarded"
    manager.register(safe)
    manager.register(guarded)

    allowed = await manager.execute_action("dummy", {}, confirmed=False)
    assert allowed.success is True
    assert safe.calls == 1

    denied = await manager.execute_action("guarded", {}, confirmed=False)
    assert denied.success is False
    assert "confirmation" in denied.error.lower()
    assert guarded.calls == 0

    approved = await manager.execute_action("guarded", {}, confirmed=True)
    assert approved.success is True
    assert guarded.calls == 1


@pytest.mark.asyncio
async def test_deny_decision_never_executes_action(monkeypatch):
    manager = ActionManager(permission_mode="autonomous")
    action = DummyAction("unrecognized")
    manager.register(action)
    monkeypatch.setattr(manager.permissions, "evaluate", lambda *_: "deny")
    result = await manager.execute_action("dummy", {}, confirmed=False)
    assert result.success is False
    assert action.calls == 0


def test_file_action_rejects_path_traversal(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(file_module, "FILE_WORKSPACE", str(workspace))
    action = FileAction()
    assert action._resolve_safe_path("../outside.txt") is None


def test_file_action_rejects_symlink_escape(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = workspace / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not supported on this platform")
    monkeypatch.setattr(file_module, "FILE_WORKSPACE", str(workspace))
    action = FileAction()
    assert action._resolve_safe_path("escape/secret.txt") is None


@pytest.mark.asyncio
async def test_file_read_and_write_stay_inside_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(file_module, "FILE_WORKSPACE", str(workspace))
    action = FileAction()
    assert await action.validate({"mode": "write", "path": "notes.txt", "content": "hello"})
    write_result = await action.execute({"mode": "write", "path": "notes.txt", "content": "hello"})
    assert write_result.success
    read_result = await action.execute({"mode": "read", "path": "notes.txt"})
    assert read_result.success
    assert read_result.data["content"] == "hello"
