"""Phase 4: safe, reviewable engineering changes in isolated workspaces.

This module stages proposed text changes only in a DevelopmentWorkspace. It
never writes to the source repository, runs arbitrary commands, commits, pushes,
or deploys. Passing static validation is not proof that a change is correct.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Mapping

from .workspace import DevelopmentWorkspace


@dataclass(frozen=True)
class EngineeringChangeReport:
    status: str
    workspace_id: str | None
    changed_files: tuple[str, ...] = ()
    deleted_files: tuple[str, ...] = ()
    blocked_files: tuple[str, ...] = ()
    syntax_errors: tuple[str, ...] = ()
    requires_approval: tuple[str, ...] = ()
    diff: str = ""
    patch_sha256: str = ""
    errors: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)

    @property
    def ready_for_review(self) -> bool:
        return self.status == "staged" and not self.errors and not self.syntax_errors

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ready_for_review"] = self.ready_for_review
        return data


class EngineeringChangeGate:
    """Validate a change set and stage it inside a disposable workspace.

    ``changes`` maps repository-relative paths to UTF-8 text. A value of ``None``
    requests deletion. Sensitive paths are always blocked. Operational files
    require an explicit approval flag before they may be staged.
    """

    VERSION = "phase4-safe-engineering-gate-1"

    HARD_BLOCK_PATTERNS = (
        re.compile(r"(^|/)\.env($|\.)", re.I),
        re.compile(r"(^|/)(secrets?|credentials?|private|certs?|certificates?)(/|$)", re.I),
        re.compile(r"(^|/).+\.(pem|key|p12|pfx)$", re.I),
    )
    APPROVAL_PATTERNS = (
        re.compile(r"(^|/)\.github/workflows(/|$)", re.I),
        re.compile(r"(^|/)(Dockerfile|docker-compose[^/]*\.ya?ml|compose\.ya?ml)$", re.I),
        re.compile(r"(^|/)(render\.yaml|render\.yml|Procfile)$", re.I),
        re.compile(r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|setup\.py)$", re.I),
    )

    def __init__(
        self,
        repository_root: str | Path,
        *,
        workspace_base: str | Path | None = None,
        max_files: int = 100,
        max_file_bytes: int = 1_000_000,
        max_total_bytes: int = 5_000_000,
    ) -> None:
        if max_files < 1 or max_file_bytes < 1 or max_total_bytes < 1:
            raise ValueError("Change limits must be positive.")
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.workspace_manager = DevelopmentWorkspace(
            self.repository_root,
            workspace_base=workspace_base,
        )
        self.max_files = int(max_files)
        self.max_file_bytes = int(max_file_bytes)
        self.max_total_bytes = int(max_total_bytes)

    @staticmethod
    def _relative_path(raw_path: str) -> str:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("Change path must be a non-empty string.")
        normalized = raw_path.replace("\\", "/")
        candidate = PurePosixPath(normalized)
        if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
            raise ValueError(f"Unsafe repository-relative path: {raw_path!r}")
        if re.match(r"^[A-Za-z]:", normalized):
            raise ValueError(f"Absolute drive path is not allowed: {raw_path!r}")
        return candidate.as_posix()

    @classmethod
    def _hard_blocked(cls, path: str) -> bool:
        return any(pattern.search(path) for pattern in cls.HARD_BLOCK_PATTERNS)

    @classmethod
    def _needs_approval(cls, path: str) -> bool:
        return any(pattern.search(path) for pattern in cls.APPROVAL_PATTERNS)

    def stage(
        self,
        changes: Mapping[str, str | None],
        *,
        approved_paths: tuple[str, ...] | list[str] = (),
        workspace_id: str | None = None,
    ) -> EngineeringChangeReport:
        """Validate and stage changes; source repository is never edited."""
        if not isinstance(changes, Mapping) or not changes:
            return EngineeringChangeReport(
                status="rejected", workspace_id=None,
                errors=("At least one proposed change is required.",),
            )
        if len(changes) > self.max_files:
            return EngineeringChangeReport(
                status="rejected", workspace_id=None,
                errors=(f"Change set exceeds max_files={self.max_files}.",),
            )
        if not self.repository_root.is_dir():
            return EngineeringChangeReport(
                status="rejected", workspace_id=None,
                errors=(f"Repository directory does not exist: {self.repository_root}",),
            )

        normalized: dict[str, str | None] = {}
        errors: list[str] = []
        blocked: list[str] = []
        approval_needed: list[str] = []
        total_bytes = 0
        approved = set()
        for raw in approved_paths:
            try:
                approved.add(self._relative_path(raw))
            except ValueError as exc:
                errors.append(str(exc))

        for raw_path, content in changes.items():
            try:
                rel = self._relative_path(raw_path)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if rel in normalized:
                errors.append(f"Duplicate normalized path: {rel}")
                continue
            if self._hard_blocked(rel):
                blocked.append(rel)
                continue
            if self._needs_approval(rel) and rel not in approved:
                approval_needed.append(rel)
                continue
            if content is not None and not isinstance(content, str):
                errors.append(f"{rel}: content must be UTF-8 text or None for deletion.")
                continue
            if content is not None:
                size = len(content.encode("utf-8"))
                total_bytes += size
                if size > self.max_file_bytes:
                    errors.append(f"{rel}: file exceeds max_file_bytes={self.max_file_bytes}.")
                    continue
            normalized[rel] = content

        if total_bytes > self.max_total_bytes:
            errors.append(f"Change set exceeds max_total_bytes={self.max_total_bytes}.")
        if blocked or approval_needed or errors:
            return EngineeringChangeReport(
                status="rejected", workspace_id=None,
                blocked_files=tuple(sorted(blocked)),
                requires_approval=tuple(sorted(approval_needed)),
                errors=tuple(errors),
                metadata={"version": self.VERSION, "source_unchanged": True},
            )

        identifier = workspace_id or f"phase4-{uuid.uuid4().hex[:12]}"
        info = self.workspace_manager.create(identifier)
        workspace_root = info.source_root
        diff_chunks: list[str] = []
        changed: list[str] = []
        deleted: list[str] = []
        syntax_errors: list[str] = []
        staged_files: list[Path] = []

        try:
            for rel, content in sorted(normalized.items()):
                target = (workspace_root / rel).resolve()
                try:
                    target.relative_to(workspace_root.resolve())
                except ValueError:
                    raise ValueError(f"Path escapes workspace: {rel}")
                # Refuse to follow a pre-existing symlink anywhere in the path.
                cursor = workspace_root.resolve()
                for part in PurePosixPath(rel).parts:
                    cursor = cursor / part
                    if cursor.is_symlink():
                        raise ValueError(f"Symlink target is not allowed: {rel}")

                old_text = ""
                existed = target.exists()
                if existed:
                    if not target.is_file():
                        raise ValueError(f"Cannot replace non-file path: {rel}")
                    try:
                        old_text = target.read_text(encoding="utf-8")
                    except (UnicodeDecodeError, OSError):
                        raise ValueError(f"Existing file is not readable UTF-8 text: {rel}")
                if content is None:
                    if existed:
                        target.unlink()
                    deleted.append(rel)
                    new_text = ""
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8", newline="")
                    new_text = content
                    changed.append(rel)
                    staged_files.append(target)
                    if target.suffix.lower() == ".py":
                        import ast
                        try:
                            ast.parse(new_text, filename=rel)
                        except SyntaxError as exc:
                            syntax_errors.append(f"{rel}: {exc.msg} (line {exc.lineno})")
                diff_chunks.extend(difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=f"a/{rel}" if existed else "/dev/null",
                    tofile=f"b/{rel}" if content is not None else "/dev/null",
                ))
        except Exception as exc:
            self.workspace_manager.destroy(identifier)
            return EngineeringChangeReport(
                status="rejected", workspace_id=None,
                errors=(f"Staging failed: {type(exc).__name__}: {exc}",),
                metadata={"version": self.VERSION, "source_unchanged": True},
            )

        diff_text = "".join(diff_chunks)
        digest = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
        status = "validation_failed" if syntax_errors else "staged"
        manifest = {
            "version": self.VERSION,
            "workspace_id": identifier,
            "status": status,
            "changed_files": changed,
            "deleted_files": deleted,
            "syntax_errors": syntax_errors,
            "patch_sha256": digest,
            "created_at": info.created_at,
            "note": "Staged in isolated workspace; not approved for production deployment.",
        }
        (info.root / "phase4_change_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        return EngineeringChangeReport(
            status=status,
            workspace_id=identifier,
            changed_files=tuple(changed),
            deleted_files=tuple(deleted),
            syntax_errors=tuple(syntax_errors),
            diff=diff_text,
            patch_sha256=digest,
            metadata={
                "version": self.VERSION,
                "workspace_root": str(info.root),
                "source_unchanged": True,
                "workspace_verified": bool(self.workspace_manager.verify(identifier).get("valid")),
                "tests_run": False,
                "production_deployment": False,
            },
        )

    async def validate(
        self,
        workspace_id: str,
        *,
        test_paths: tuple[str, ...] | list[str] | None = None,
        run_regression_suite: bool = False,
    ) -> dict:
        """Compile changed Python files and optionally run isolated pytest tests.

        Tests execute only in the copied workspace through DevelopmentSandbox.
        This is a process/filesystem boundary, not a full OS container.
        """
        from .sandbox import DevelopmentSandbox
        from .test_runner import DevelopmentTestRunner

        info = self.workspace_manager.get(workspace_id)
        manifest_path = info.root / "phase4_change_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("Phase 4 change manifest is missing.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sandbox = DevelopmentSandbox(info.source_root)
        runner = DevelopmentTestRunner(sandbox)
        compile_results = []
        for relative in manifest.get("changed_files", []):
            if not relative.lower().endswith(".py"):
                continue
            result = await runner.compile_file(relative)
            compile_results.append({"path": relative, **result.to_dict()})
            if not result.passed:
                return {
                    "status": "failed",
                    "workspace_id": workspace_id,
                    "passed": False,
                    "compile_results": compile_results,
                    "test_results": [],
                    "reason": "python_compile_failed",
                    "production_deployment": False,
                }

        test_result_dicts = []
        if test_paths:
            suite = await runner.run_targeted_tests(tuple(test_paths))
            test_result_dicts = [item.to_dict() for item in suite.results]
            tests_passed = suite.passed
        elif run_regression_suite:
            suite = await runner.run_regression_suite()
            test_result_dicts = [item.to_dict() for item in suite.results]
            tests_passed = suite.passed
        else:
            tests_passed = None

        passed = all(item["passed"] for item in compile_results) and (
            tests_passed is not False
        )
        status = "passed" if passed and tests_passed is True else (
            "compile_passed_tests_not_run" if passed else "failed"
        )
        return {
            "status": status,
            "workspace_id": workspace_id,
            "passed": passed,
            "compile_results": compile_results,
            "tests_passed": tests_passed,
            "test_results": test_result_dicts,
            "reason": "tests_passed" if tests_passed is True else (
                "tests_not_run" if tests_passed is None else "tests_failed"
            ),
            "production_deployment": False,
        }

    def destroy(self, workspace_id: str) -> None:
        """Delete only the named workspace through the workspace manager."""
        self.workspace_manager.destroy(workspace_id)
