from pathlib import Path

from brain.development.workspace import DevelopmentWorkspace
from brain.development.filesystem_guard import FilesystemGuard
from brain.development.sandbox import DevelopmentSandbox


def test_development_modules_import():
    assert DevelopmentWorkspace is not None
    assert FilesystemGuard is not None
    assert DevelopmentSandbox is not None


def test_workspace_class_signature():
    assert hasattr(DevelopmentWorkspace, "create")
    assert hasattr(DevelopmentWorkspace, "destroy")
    assert hasattr(DevelopmentWorkspace, "get")


def test_filesystem_guard_signature(tmp_path):
    guard = FilesystemGuard(tmp_path)

    assert guard.can_write("test.py")
    assert guard.resolve("test.py").parent == Path(tmp_path).resolve()


def test_sandbox_signature(tmp_path):
    sandbox = DevelopmentSandbox(tmp_path)

    assert sandbox.guard.workspace_root == Path(
        tmp_path
    ).resolve()
    assert sandbox.timeout_seconds > 0
    assert sandbox.max_output_bytes > 0