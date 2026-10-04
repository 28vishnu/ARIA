from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from inspect import isawaitable
from pathlib import Path
from typing import Any, Awaitable, Callable

from .change_planner import ChangePlan, ChangePlanner
from .change_impact_planner import ChangeImpactAnalysis, ChangeImpactPlanner
from .architecture_intelligence import ArchitectureIntelligence
from .code_writer import CodeWriter, WriteResult
from .failure_analyzer import FailureAnalysis, FailureAnalyzer
from .filesystem_guard import FilesystemGuard
from .repository_manager import RepositoryManager
from .requirement_parser import Requirement, RequirementParser
from .requirement_intelligence import RequirementAnalysis, RequirementIntelligence
from .repair_engine import RepairEngine, RepairResult
from .sandbox import DevelopmentSandbox
from .test_runner import DevelopmentTestRunner, TestResult
from .validator import DevelopmentValidator, ValidationResult
from .workspace import DevelopmentWorkspace, WorkspaceInfo


logger = logging.getLogger("aria")


CodeGenerator = Callable[
    [str, dict[str, Any]],
    str | dict[str, Any] | Awaitable[str | dict[str, Any]],
]


@dataclass(frozen=True)
class GeneratedChange:
    path: str
    operation: str
    content: str = ""

    def to_tuple(self) -> tuple[str, str]:
        return self.path, self.content

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "operation": self.operation,
            "content": self.content,
        }


@dataclass(frozen=True)
class CodeGenerationResult:
    success: bool
    summary: str = ""
    reasoning: str = ""
    changes: tuple[GeneratedChange, ...] = ()
    tests: tuple[str, ...] = ()
    raw_response: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "summary": self.summary,
            "reasoning": self.reasoning,
            "changes": [
                change.to_dict()
                for change in self.changes
            ],
            "tests": list(self.tests),
            "raw_response": self.raw_response,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DevelopmentReport:
    success: bool
    requirement: Requirement
    plan: ChangePlan | None
    workspace: WorkspaceInfo | None

    writes: tuple[WriteResult, ...] = ()
    validation: ValidationResult | None = None
    tests: TestResult | None = None
    repair: RepairResult | None = None
    failure: FailureAnalysis | None = None
    generation: CodeGenerationResult | None = None

    status: str = "not_started"
    errors: tuple[str, ...] = ()

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "requirement": self.requirement.to_dict(),
            "plan": (
                self.plan.to_dict()
                if self.plan
                else None
            ),
            "workspace": (
                self.workspace.to_dict()
                if self.workspace
                else None
            ),
            "writes": [
                item.to_dict()
                for item in self.writes
            ],
            "validation": (
                self.validation.to_dict()
                if self.validation
                else None
            ),
            "tests": (
                self.tests.to_dict()
                if self.tests
                else None
            ),
            "repair": (
                self.repair.to_dict()
                if self.repair
                else None
            ),
            "failure": (
                self.failure.to_dict()
                if self.failure
                else None
            ),
            "generation": (
                self.generation.to_dict()
                if self.generation
                else None
            ),
            "status": self.status,
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }


class DevelopmentAgent:
    """
    Phase 1 self-development engine.

    The production repository is never modified directly.

    Pipeline:

        Master requirement
              ↓
        repository inspection
              ↓
        deterministic planning
              ↓
        isolated workspace
              ↓
        workspace verification
              ↓
        workspace repository inspection
              ↓
        bounded repository context
              ↓
        AI generation
              ↓
        deterministic safety validation
              ↓
        guarded writes
              ↓
        acceptance checks
              ↓
        static validation
              ↓
        targeted tests
              ↓
        bounded repair
              ↓
        final verification

    This class does not deploy or push to GitHub.
    """

    DEFAULT_MAX_CONTEXT_CHARS = 120_000
    DEFAULT_MAX_GENERATION_CHARS = 500_000
    DEFAULT_MAX_GENERATED_FILES = 30
    DEFAULT_MAX_FILE_CHARS = 2_000_000

    SENSITIVE_PARTS = {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".env.test",
        "credentials",
        "credential",
        "secrets",
        "secret",
        "private",
        "certs",
        "certificates",
        "keys",
    }

    SENSITIVE_SUFFIXES = {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".crt",
        ".cer",
        ".der",
    }

    SKIP_CONTEXT_DIRS = {
        ".git",
        ".aria_workspaces",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
    }

    CODE_SUFFIXES = {
        ".py",
        ".pyw",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".go",
        ".rs",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cc",
        ".cs",
        ".php",
        ".rb",
        ".swift",
        ".kt",
        ".kts",
    }

    def __init__(
        self,
        repository_manager: RepositoryManager,
        workspace_manager: DevelopmentWorkspace,
        *,
        code_generator: CodeGenerator | None = None,
        max_repair_attempts: int = 3,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
        max_generation_chars: int = DEFAULT_MAX_GENERATION_CHARS,
        max_generated_files: int = DEFAULT_MAX_GENERATED_FILES,
        max_generated_file_chars: int = DEFAULT_MAX_FILE_CHARS,
        requirement_intelligence: RequirementIntelligence | None = None,
        architecture_intelligence: ArchitectureIntelligence | None = None,
        change_impact_planner: ChangeImpactPlanner | None = None,
    ) -> None:
        self.repository_manager = repository_manager
        self.workspace_manager = workspace_manager

        self.requirement_parser = RequirementParser()
        self.requirement_intelligence = requirement_intelligence or RequirementIntelligence(self.requirement_parser)
        self.architecture_intelligence = architecture_intelligence or ArchitectureIntelligence(
            repository_manager=repository_manager,
        )
        self.change_planner = ChangePlanner()
        self.change_impact_planner = change_impact_planner or ChangeImpactPlanner(
            self.architecture_intelligence,
        )
        self.code_generator = code_generator

        self.max_repair_attempts = max(
            1,
            int(max_repair_attempts),
        )

        self.max_context_chars = max(
            10_000,
            int(max_context_chars),
        )

        self.max_generation_chars = max(
            10_000,
            int(max_generation_chars),
        )

        self.max_generated_files = max(
            1,
            int(max_generated_files),
        )

        self.max_generated_file_chars = max(
            10_000,
            int(max_generated_file_chars),
        )

    # ========================================================
    # Path safety
    # ========================================================

    @staticmethod
    def _normalize_path(path: str) -> str:
        value = str(path).strip().replace("\\", "/")

        while value.startswith("./"):
            value = value[2:]

        return value

    @classmethod
    def _is_sensitive_path(
        cls,
        path: Path | str,
    ) -> bool:
        candidate = Path(path)

        if any(
            part.lower() in cls.SENSITIVE_PARTS
            for part in candidate.parts
        ):
            return True

        name = candidate.name.lower()

        if name in cls.SENSITIVE_PARTS:
            return True

        return any(
            name.endswith(suffix)
            for suffix in cls.SENSITIVE_SUFFIXES
        )

    @classmethod
    def _is_context_directory(
        cls,
        path: Path,
    ) -> bool:
        return any(
            part in cls.SKIP_CONTEXT_DIRS
            for part in path.parts
        )

    @staticmethod
    def _safe_relative_path(
        path: str,
    ) -> tuple[str | None, str | None]:
        normalized = (
            str(path)
            .strip()
            .replace("\\", "/")
        )

        while normalized.startswith("./"):
            normalized = normalized[2:]

        if not normalized:
            return None, "Empty path."

        candidate = Path(normalized)

        if candidate.is_absolute():
            return None, (
                f"Absolute path rejected: {normalized}"
            )

        if ".." in candidate.parts:
            return None, (
                f"Path traversal rejected: {normalized}"
            )

        return candidate.as_posix(), None

    # ========================================================
    # Repository inspection
    # ========================================================

    def _repository_paths(
        self,
        repository_path: str | Path | None = None,
    ) -> list[str]:
        root = (
            Path(repository_path).expanduser().resolve()
            if repository_path is not None
            else Path(
                self.workspace_manager.repository_root
            ).resolve()
        )

        snapshot = self.repository_manager.inspect(root)

        paths: list[str] = []

        for file_info in snapshot.files:
            relative = self._normalize_path(
                str(file_info.path)
            )

            if relative:
                paths.append(relative)

        return paths

    def _workspace_paths(
        self,
        workspace: WorkspaceInfo,
    ) -> list[str]:
        """
        Return files contained by the isolated workspace.

        IMPORTANT:
        Context-directory filtering is performed against paths
        relative to workspace.source_root.

        The workspace itself normally lives under:

            .aria_workspaces/<workspace_id>/repo

        Therefore checking the absolute path against
        SKIP_CONTEXT_DIRS would incorrectly reject every file
        because the absolute path contains '.aria_workspaces'.
        """

        root = workspace.source_root.resolve()

        if not root.exists() or not root.is_dir():
            return []

        paths: list[str] = []

        for path in root.rglob("*"):
            if not path.is_file():
                continue

            try:
                relative = path.relative_to(root)
            except ValueError:
                continue

            # IMPORTANT:
            # Filter using the workspace-relative path only.
            if self._is_context_directory(relative):
                continue

            paths.append(relative.as_posix())

        paths.sort()

        return paths

    def _verify_workspace_repository(
        self,
        workspace: WorkspaceInfo,
    ) -> tuple[bool, dict[str, Any], str | None]:
        """
        Verify that the isolated workspace really contains a
        repository before allowing the LLM to inspect it.
        """

        try:
            root = workspace.source_root.resolve()

            if not root.exists():
                return (
                    False,
                    {
                        "source_root": str(root),
                        "file_count": 0,
                        "expected_file_count": getattr(
                            workspace,
                            "source_file_count",
                            0,
                        )
                        or 0,
                        "sample_files": [],
                    },
                    (
                        "Workspace repository does not exist: "
                        f"{root}"
                    ),
                )

            if not root.is_dir():
                return (
                    False,
                    {
                        "source_root": str(root),
                        "file_count": 0,
                        "expected_file_count": getattr(
                            workspace,
                            "source_file_count",
                            0,
                        )
                        or 0,
                        "sample_files": [],
                    },
                    (
                        "Workspace repository is not a "
                        f"directory: {root}"
                    ),
                )

            paths = self._workspace_paths(workspace)

            expected_files = (
                getattr(
                    workspace,
                    "source_file_count",
                    0,
                )
                or 0
            )

            snapshot_hash = getattr(
                workspace,
                "source_snapshot_hash",
                "",
            )

            info = {
                "source_root": str(root),
                "file_count": len(paths),
                "expected_file_count": expected_files,
                "sample_files": paths[:25],
                "snapshot_hash": snapshot_hash,
            }

            if not paths:
                return (
                    False,
                    info,
                    (
                        "Workspace repository is empty. "
                        "Code generation is blocked."
                    ),
                )

            # The workspace.py copy operation records the expected
            # source file count. If that count is available, verify
            # that the actual isolated repository matches it.
            if (
                expected_files > 0
                and len(paths) != expected_files
            ):
                return (
                    False,
                    info,
                    (
                        "Workspace repository file count "
                        "mismatch. "
                        f"expected={expected_files} "
                        f"actual={len(paths)}"
                    ),
                )

            return True, info, None

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Workspace verification failed."
            )

            return (
                False,
                {},
                f"Workspace verification failed: {exc}",
            )

    # ========================================================
    # Repository context
    # ========================================================

    def _build_repository_context(
        self,
        workspace: WorkspaceInfo,
    ) -> dict[str, Any]:
        """
        Build bounded repository context from the VERIFIED
        isolated workspace.

        Never builds LLM context from the production repository.

        IMPORTANT:
        All skip-directory checks operate on workspace-relative
        paths, never absolute paths.
        """

        root = workspace.source_root.resolve()

        if not root.exists():
            raise RuntimeError(
                "Cannot build repository context because "
                "workspace repository does not exist."
            )

        if not root.is_dir():
            raise RuntimeError(
                "Cannot build repository context because "
                "workspace repository is not a directory."
            )

        all_paths: list[Path] = []

        for path in root.rglob("*"):
            if not path.is_file():
                continue

            try:
                relative = path.relative_to(root)
            except ValueError:
                continue

            # IMPORTANT:
            # Use the workspace-relative path here.
            #
            # Do NOT pass the absolute path to
            # _is_context_directory(), because the workspace itself
            # is located below '.aria_workspaces'.
            if self._is_context_directory(relative):
                continue

            all_paths.append(path)

        if not all_paths:
            raise RuntimeError(
                "Verified workspace contains no files. "
                "Refusing to send an empty repository context "
                "to the code-generation engine."
            )

        files: list[dict[str, Any]] = []

        total_chars = 0
        skipped_sensitive = 0
        skipped_binary = 0
        skipped_large = 0
        skipped_unreadable = 0

        for path in sorted(all_paths):
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue

            relative_path = relative.as_posix()

            if self._is_sensitive_path(relative):
                skipped_sensitive += 1
                continue

            try:
                size = path.stat().st_size
            except OSError:
                skipped_unreadable += 1
                continue

            if size > self.DEFAULT_MAX_FILE_CHARS:
                skipped_large += 1
                continue

            try:
                raw = path.read_bytes()
            except OSError:
                skipped_unreadable += 1
                continue

            if b"\x00" in raw[:8192]:
                skipped_binary += 1
                continue

            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                skipped_binary += 1
                continue

            remaining = (
                self.max_context_chars
                - total_chars
            )

            if remaining <= 0:
                break

            content = text[:remaining]

            files.append(
                {
                    "path": relative_path,
                    "content": content,
                    "truncated": (
                        len(content) < len(text)
                    ),
                }
            )

            total_chars += len(content)

        if not files:
            raise RuntimeError(
                "Workspace contains files, but no safe textual "
                "files could be included in the LLM context."
            )

        return {
            "repository_root": ".",
            "file_count": len(files),
            "workspace_file_count": len(all_paths),
            "context_chars": total_chars,
            "files": files,
            "safety": {
                "sensitive_files_excluded": skipped_sensitive,
                "binary_files_excluded": skipped_binary,
                "large_files_excluded": skipped_large,
                "unreadable_files_excluded": skipped_unreadable,
            },
        }

    # ========================================================
    # Generation prompt
    # ========================================================

    def _build_generation_prompt(
        self,
        requirement: Requirement,
        plan: ChangePlan,
        repository_context: dict[str, Any],
        impact_analysis: ChangeImpactAnalysis | None = None,
        *,
        failure: FailureAnalysis | None = None,
        previous_changes: list[GeneratedChange] | None = None,
    ) -> str:
        failure_text = ""

        if failure is not None:
            failure_text = (
                "\n\nPREVIOUS TEST FAILURE:\n"
                + json.dumps(
                    failure.to_dict(),
                    ensure_ascii=False,
                    indent=2,
                )[:30_000]
            )

        previous_text = ""

        if previous_changes:
            previous_text = (
                "\n\nPREVIOUS GENERATED CHANGES:\n"
                + json.dumps(
                    [
                        item.to_dict()
                        for item in previous_changes
                    ],
                    ensure_ascii=False,
                    indent=2,
                )[:50_000]
            )

        return (
            "You are ARIA's software-development engine.\n"
            "\n"
            "Your job is to propose safe, minimal source-code "
            "changes satisfying the Master's requirement.\n"
            "\n"
            "IMPORTANT SAFETY RULES:\n"
            "- Return structured data only.\n"
            "- Never execute commands.\n"
            "- Never deploy.\n"
            "- Never push to GitHub.\n"
            "- Never modify production directly.\n"
            "- Never invent secrets, credentials, tokens, API keys, "
            "private keys, or environment values.\n"
            "- Never request arbitrary shell execution.\n"
            "- Never modify unrelated files.\n"
            "\n"
            "Return ONE valid JSON object and nothing else.\n"
            "\n"
            "Required JSON schema:\n"
            "{\n"
            '  "summary": "short description",\n'
            '  "reasoning": "technical reasoning",\n'
            '  "changes": [\n'
            "    {\n"
            '      "path": "relative/path",\n'
            '      "operation": "create|modify|delete",\n'
            '      "content": "complete file content"\n'
            "    }\n"
            "  ],\n"
            '  "tests": ["existing test path"]\n'
            "}\n"
            "\n"
            "Rules:\n"
            "1. Paths must be repository-relative.\n"
            "2. Never use absolute paths.\n"
            "3. Never use '..' traversal.\n"
            "4. For create/modify, provide complete file content.\n"
            "5. For delete, content must be empty.\n"
            "6. Make the smallest safe change.\n"
            "7. Preserve existing behavior unless the requirement "
            "explicitly changes it.\n"
            "8. Do not modify unrelated files.\n"
            "9. Do not modify protected/security/deployment files "
            "unless explicitly required.\n"
            "10. Do not include Markdown fences.\n"
            "11. Do not include prose outside JSON.\n"
            "\n"
            "MASTER REQUIREMENT:\n"
            f"{requirement.raw_text}\n"
            "\n"
            "PARSED REQUIREMENT:\n"
            f"{json.dumps(requirement.to_dict(), ensure_ascii=False, indent=2)}\n"
            "\n"
            "CHANGE PLAN:\n"
            f"{json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)}\n"
            "\n"
            "CURRENT VERIFIED REPOSITORY CONTEXT:\n"
            f"{json.dumps(repository_context, ensure_ascii=False, indent=2)}"
            f"{failure_text}"
            f"{previous_text}"
        )

    # ========================================================
    # AI response parsing
    # ========================================================

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        value = str(text).strip()

        if value.startswith("```"):
            value = re.sub(
                r"^```(?:json)?\s*",
                "",
                value,
                flags=re.IGNORECASE,
            )

            value = re.sub(
                r"\s*```$",
                "",
                value,
            )

        return value.strip()

    def _parse_generation_response(
        self,
        response: str | dict[str, Any],
    ) -> CodeGenerationResult:
        if isinstance(response, dict):
            payload = response

            try:
                raw_response = json.dumps(
                    response,
                    ensure_ascii=False,
                )
            except Exception:
                raw_response = str(response)

        else:
            raw_response = str(response)

            if len(raw_response) > self.max_generation_chars:
                return CodeGenerationResult(
                    success=False,
                    raw_response=raw_response[:10_000],
                    error=(
                        "Generated response exceeds the "
                        "maximum allowed size."
                    ),
                )

            cleaned = self._strip_code_fences(
                raw_response
            )

            try:
                payload = json.loads(cleaned)
            except json.JSONDecodeError as exc:
                return CodeGenerationResult(
                    success=False,
                    raw_response=raw_response[:20_000],
                    error=(
                        "AI code-generation response was "
                        f"not valid JSON: {exc}"
                    ),
                )

        if not isinstance(payload, dict):
            return CodeGenerationResult(
                success=False,
                raw_response=raw_response[:20_000],
                error=(
                    "AI generation result must be a JSON object."
                ),
            )

        changes_payload = payload.get(
            "changes",
            [],
        )

        if not isinstance(changes_payload, list):
            return CodeGenerationResult(
                success=False,
                raw_response=raw_response[:20_000],
                error="'changes' must be a JSON array.",
            )

        if len(changes_payload) > self.max_generated_files:
            return CodeGenerationResult(
                success=False,
                raw_response=raw_response[:20_000],
                error=(
                    "AI requested too many file changes."
                ),
            )

        generated: list[GeneratedChange] = []
        errors: list[str] = []

        for index, item in enumerate(changes_payload):
            if not isinstance(item, dict):
                errors.append(
                    f"Change {index} is not an object."
                )
                continue

            path = str(
                item.get("path", "")
            ).strip()

            operation = str(
                item.get("operation", "modify")
            ).strip().lower()

            content = item.get(
                "content",
                "",
            )

            if not path:
                errors.append(
                    f"Change {index} has no path."
                )
                continue

            if operation not in {
                "create",
                "modify",
                "delete",
            }:
                errors.append(
                    f"Change {index} has invalid operation "
                    f"'{operation}'."
                )
                continue

            if not isinstance(content, str):
                errors.append(
                    f"Change {index} content must be a string."
                )
                continue

            if len(content) > self.max_generated_file_chars:
                errors.append(
                    f"Change {index} exceeds maximum file size."
                )
                continue

            normalized, path_error = (
                self._safe_relative_path(path)
            )

            if path_error or normalized is None:
                errors.append(
                    path_error or f"Invalid path: {path}"
                )
                continue

            generated.append(
                GeneratedChange(
                    path=normalized,
                    operation=operation,
                    content=content,
                )
            )

        tests_payload = payload.get(
            "tests",
            [],
        )

        if tests_payload is None:
            tests_payload = []

        if not isinstance(tests_payload, list):
            return CodeGenerationResult(
                success=False,
                summary=str(
                    payload.get("summary", "")
                ),
                reasoning=str(
                    payload.get("reasoning", "")
                ),
                changes=tuple(generated),
                raw_response=raw_response[:20_000],
                error="'tests' must be a JSON array.",
            )

        tests = tuple(
            str(item).strip()
            for item in tests_payload
            if isinstance(item, str)
            and str(item).strip()
        )

        if errors:
            return CodeGenerationResult(
                success=False,
                summary=str(
                    payload.get("summary", "")
                ),
                reasoning=str(
                    payload.get("reasoning", "")
                ),
                changes=tuple(generated),
                tests=tests,
                raw_response=raw_response[:20_000],
                error=" ".join(errors),
                metadata={
                    "parse_errors": errors,
                },
            )

        return CodeGenerationResult(
            success=True,
            summary=str(
                payload.get("summary", "")
            ),
            reasoning=str(
                payload.get("reasoning", "")
            ),
            changes=tuple(generated),
            tests=tests,
            raw_response=raw_response[:20_000],
        )

    # ========================================================
    # Generator
    # ========================================================

    async def _generate_code(
        self,
        prompt: str,
        context: dict[str, Any],
    ) -> CodeGenerationResult:
        if self.code_generator is None:
            return CodeGenerationResult(
                success=False,
                error=(
                    "No code generator is connected to "
                    "DevelopmentAgent."
                ),
            )

        try:
            response = self.code_generator(
                prompt,
                context,
            )

            if isawaitable(response):
                response = await response

            return self._parse_generation_response(
                response
            )

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Code generation failed."
            )

            return CodeGenerationResult(
                success=False,
                error=f"Code generation failed: {exc}",
            )

    # ========================================================
    # Requirement helpers
    # ========================================================

    @staticmethod
    def _forbids_existing_modification(
        requirement: Requirement,
    ) -> bool:
        text = re.sub(
            r"\s+",
            " ",
            str(requirement.raw_text or "").lower(),
        )

        phrases = (
            "do not modify any existing files",
            "do not modify existing files",
            "don't modify any existing files",
            "don't modify existing files",
            "must not modify existing files",
            "must not modify any existing files",
            "without modifying existing files",
            "without modifying any existing files",
        )

        return any(
            phrase in text
            for phrase in phrases
        )

    @staticmethod
    def _is_create_only_requirement(
        requirement: Requirement,
    ) -> bool:
        text = re.sub(
            r"\s+",
            " ",
            str(requirement.raw_text or "").lower(),
        )

        phrases = (
            "create only",
            "create-only",
            "only create new files",
            "only create files",
            "new file only",
            "new files only",
            "do not modify any existing files",
            "do not modify existing files",
            "don't modify any existing files",
            "don't modify existing files",
            "must not modify existing files",
            "must not modify any existing files",
        )

        return any(
            phrase in text
            for phrase in phrases
        )

    # ========================================================
    # Planner/path enforcement
    # ========================================================

    @staticmethod
    def _planned_actions(
        plan: ChangePlan,
    ) -> dict[str, str]:
        result: dict[str, str] = {}

        for item in plan.changes:
            raw_path = getattr(
                item,
                "path",
                None,
            )

            if not raw_path:
                continue

            path = (
                str(raw_path)
                .replace("\\", "/")
                .lstrip("./")
            )

            action = str(
                getattr(
                    item,
                    "action",
                    "",
                )
            ).lower()

            if path:
                result[path] = action

        return result

    @classmethod
    def _path_is_planned(
        cls,
        path: str,
        plan: ChangePlan | None,
    ) -> bool:
        if plan is None:
            return True

        planned = cls._planned_actions(plan)

        if not planned:
            return True

        return path in planned

    def _validate_generated_changes(
        self,
        changes: tuple[GeneratedChange, ...],
        workspace: WorkspaceInfo,
        *,
        requirement: Requirement | None = None,
        plan: ChangePlan | None = None,
    ) -> tuple[
        list[GeneratedChange],
        list[str],
    ]:
        valid: list[GeneratedChange] = []
        errors: list[str] = []
        seen: set[str] = set()

        planned_actions = (
            self._planned_actions(plan)
            if plan is not None
            else {}
        )

        guard = FilesystemGuard(
            workspace.source_root
        )

        workspace_root = (
            workspace.source_root.resolve()
        )

        for change in changes:
            path, path_error = self._safe_relative_path(
                change.path
            )

            if path_error:
                errors.append(path_error)
                continue

            assert path is not None

            if path in seen:
                errors.append(
                    f"Duplicate generated path: {path}"
                )
                continue

            seen.add(path)

            operation = str(
                change.operation
            ).strip().lower()

            if operation not in {
                "create",
                "modify",
                "delete",
            }:
                errors.append(
                    f"Unsupported operation '{operation}' "
                    f"for {path}"
                )
                continue

            if (
                operation == "delete"
                and change.content
            ):
                errors.append(
                    f"Delete operation must not contain "
                    f"content: {path}"
                )
                continue

            if (
                operation in {"create", "modify"}
                and not change.content
            ):
                errors.append(
                    f"{operation} operation has empty "
                    f"content: {path}"
                )
                continue

            candidate = (
                workspace.source_root / path
            )

            try:
                resolved = candidate.resolve()

                resolved.relative_to(
                    workspace_root
                )

            except ValueError:
                errors.append(
                    f"Generated path escapes workspace: {path}"
                )
                continue

            if self._is_sensitive_path(path):
                errors.append(
                    f"Sensitive path rejected: {path}"
                )
                continue

            try:
                if guard.is_protected(resolved):
                    errors.append(
                        f"Protected development path rejected: {path}"
                    )
                    continue
            except Exception as exc:
                errors.append(
                    f"Could not verify path safety for "
                    f"{path}: {exc}"
                )
                continue

            exists = resolved.exists()

            # ----------------------------------------------
            # Create-only requirements
            # ----------------------------------------------

            if (
                requirement is not None
                and self._is_create_only_requirement(
                    requirement
                )
            ):
                if operation != "create":
                    errors.append(
                        "Create-only requirement rejected "
                        f"non-create operation: {path}"
                    )
                    continue

                if exists:
                    errors.append(
                        "Create-only requirement targets an "
                        f"existing path: {path}"
                    )
                    continue

            if operation == "create" and exists:
                errors.append(
                    "Create operation targets an existing "
                    f"path: {path}"
                )
                continue

            if operation == "modify" and not exists:
                errors.append(
                    "Modify operation targets a missing "
                    f"path: {path}"
                )
                continue

            if operation == "delete" and not exists:
                errors.append(
                    "Delete operation targets a missing "
                    f"path: {path}"
                )
                continue

            # ----------------------------------------------
            # Existing-file modification prohibition
            # ----------------------------------------------

            if (
                exists
                and operation in {
                    "modify",
                    "delete",
                }
                and requirement is not None
                and self._forbids_existing_modification(
                    requirement
                )
            ):
                errors.append(
                    "Requirement forbids modifying "
                    f"existing files: {path}"
                )
                continue

            # ----------------------------------------------
            # Planner agreement
            # ----------------------------------------------

            if plan is not None:
                if not self._path_is_planned(
                    path,
                    plan,
                ):
                    errors.append(
                        "Generated path was not present "
                        f"in the change plan: {path}"
                    )
                    continue

                expected = planned_actions.get(path)

                if expected in {
                    "create",
                    "modify",
                    "delete",
                } and operation != expected:
                    errors.append(
                        "Generated operation "
                        f"'{operation}' conflicts with planned "
                        f"operation '{expected}' for {path}"
                    )
                    continue

            valid.append(
                GeneratedChange(
                    path=path,
                    operation=operation,
                    content=change.content,
                )
            )

        return valid, errors

    # ========================================================
    # Exact-content acceptance
    # ========================================================

    @staticmethod
    def _extract_exact_content_requirement(
        requirement: Requirement,
    ) -> tuple[str, str] | None:
        text = str(
            requirement.raw_text or ""
        )

        match = re.search(
            r"(?:file\s+(?:called|named)\s+[`\"]?"
            r"([^`\"\s]+)[`\"]?)"
            r"[^.\n]*?"
            r"containing\s+exactly\s+(.+?)(?:\.|$)",
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        path = match.group(1).strip()
        expected = match.group(2).strip()
        if len(expected) >= 2 and expected[0] == expected[-1] and expected[0] in {chr(34), chr(39)}:
            expected = expected[1:-1]
        return (path, expected)

    def _check_exact_content_requirement(
        self,
        requirement: Requirement,
        workspace: WorkspaceInfo,
    ) -> str | None:
        extracted = (
            self._extract_exact_content_requirement(
                requirement
            )
        )

        if extracted is None:
            return None

        path, expected = extracted

        safe_path, path_error = (
            self._safe_relative_path(path)
        )

        if path_error or safe_path is None:
            return (
                path_error
                or "Invalid acceptance-test path."
            )

        try:
            target = (
                FilesystemGuard(
                    workspace.source_root
                ).assert_allowed(
                    safe_path,
                    allow_missing=False,
                )
            )

            actual = target.read_text(
                encoding="utf-8"
            )

        except Exception as exc:
            return (
                f"Acceptance check could not read "
                f"{safe_path}: {exc}"
            )

        if actual != expected:
            return (
                "Exact-content acceptance check failed "
                f"for {safe_path}: file content does not "
                "exactly match the requirement."
            )

        return None

    # ========================================================
    # Test selection
    # ========================================================

    def _select_test_paths(
        self,
        workspace: WorkspaceInfo,
        generation: CodeGenerationResult | None,
        explicit_test_paths: list[str] | None,
        generated_changes: list[GeneratedChange],
    ) -> list[str]:
        candidates = (
            explicit_test_paths
            if explicit_test_paths is not None
            else (
                list(generation.tests)
                if generation
                else []
            )
        )

        selected: list[str] = []

        for raw in candidates:
            value = self._normalize_path(
                str(raw)
            )

            if not value:
                continue

            if any(
                token in value
                for token in (
                    ";",
                    "&&",
                    "||",
                    "|",
                    "`",
                    "$(",
                    "${",
                )
            ):
                continue

            safe_path, error = (
                self._safe_relative_path(value)
            )

            if error or safe_path is None:
                continue

            candidate = (
                workspace.source_root / safe_path
            )

            try:
                candidate.resolve().relative_to(
                    workspace.source_root.resolve()
                )
            except ValueError:
                continue

            if not candidate.exists():
                continue

            if not (
                candidate.is_file()
                or candidate.is_dir()
            ):
                continue

            if candidate.is_file():
                if candidate.suffix.lower() not in {
                    ".py",
                    ".pyw",
                }:
                    continue

            if safe_path not in selected:
                selected.append(safe_path)

        if selected:
            return selected

        code_changed = any(
            Path(change.path).suffix.lower()
            in self.CODE_SUFFIXES
            for change in generated_changes
        )

        if code_changed:
            return self._default_test_paths(
                workspace
            )

        return []

    # ========================================================
    # Apply changes
    # ========================================================

    def _apply_generated_changes(
        self,
        writer: CodeWriter,
        changes: list[GeneratedChange],
    ) -> list[WriteResult]:
        results: list[WriteResult] = []

        for change in changes:
            if change.operation == "create":
                results.append(
                    writer.write(
                        change.path,
                        change.content,
                        create_only=True,
                        backup=False,
                    )
                )

            elif change.operation == "modify":
                results.append(
                    writer.write(
                        change.path,
                        change.content,
                        create_only=False,
                        backup=True,
                    )
                )

            elif change.operation == "delete":
                results.append(
                    writer.delete(
                        change.path
                    )
                )

            else:
                raise ValueError(
                    "Unsupported generated operation: "
                    f"{change.operation}"
                )

        return results

    # ========================================================
    # Report metadata
    # ========================================================

    @staticmethod
    def _report_metadata(
        generated_changes: list[GeneratedChange],
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "generated_change_count": len(
                generated_changes
            ),
            "generated_files": [
                change.path
                for change in generated_changes
            ],
        }

        if extra:
            metadata.update(extra)

        return metadata

    # ========================================================
    # Main workflow
    # ========================================================

    async def develop(
        self,
        requirement_text: str,
        *,
        changes: list[tuple[str, str]] | None = None,
        test_paths: list[str] | None = None,
        workspace_id: str | None = None,
    ) -> DevelopmentReport:

        # ----------------------------------------------------
        # Requirement
        # ----------------------------------------------------

        try:
            requirement_analysis = (
                self.requirement_intelligence.analyze(
                    requirement_text
                )
            )
            requirement = requirement_analysis.requirement
        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Requirement intelligence failed."
            )

            raise RuntimeError(
                f"Requirement intelligence failed: {exc}"
            ) from exc

        if not requirement_analysis.ready_for_planning:
            logger.warning(
                "[DevelopmentAgent] Requirement is not sufficiently specified | "
                "intent=%s | ambiguity=%s",
                requirement_analysis.intent,
                requirement_analysis.ambiguity_flags,
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=None,
                workspace=None,
                status="requirement_unclear",
                errors=tuple(requirement_analysis.clarification_questions) or (
                    "The requirement is not specific enough for safe planning.",
                ),
                metadata={
                    "requirement_analysis": requirement_analysis.to_dict(),
                },
            )

        logger.info(
            "[DevelopmentAgent] Starting development job | "
            "requirement=%r",
            requirement.raw_text,
        )

        requirement_analysis_metadata = {
            "requirement_analysis": requirement_analysis.to_dict(),
        }

        # ----------------------------------------------------
        # Production repository inspection
        # ----------------------------------------------------

        try:
            repository_root = (
                self.workspace_manager.repository_root
            )

            repository_paths = (
                self._repository_paths(
                    repository_root
                )
            )

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Repository inspection failed."
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=None,
                workspace=None,
                status="repository_inspection_failed",
                errors=(str(exc),),
                metadata=requirement_analysis_metadata,
            )

        logger.info(
            "[DevelopmentAgent] Repository inspection complete | "
            "root=%s | files=%s",
            repository_root,
            len(repository_paths),
        )

        if not repository_paths:
            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=None,
                workspace=None,
                status="repository_empty",
                errors=(
                    "Production repository inspection returned "
                    "zero files. Development is blocked.",
                ),
                metadata=requirement_analysis_metadata,
            )

        # ----------------------------------------------------
        # Deterministic planning
        # ----------------------------------------------------

        try:
            plan = self.change_planner.plan(
                requirement,
                existing_paths=repository_paths,
            )

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Change planning failed."
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=None,
                workspace=None,
                status="planning_failed",
                errors=(str(exc),),
            )

        if plan.blocked:
            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=None,
                status="blocked",
                errors=(
                    plan.block_reason
                    or "Development request blocked.",
                ),
            )

        # ----------------------------------------------------
        # Change impact analysis
        # ----------------------------------------------------

        try:
            impact_analysis = self.change_impact_planner.analyze(
                requirement_analysis,
                repository_root,
                existing_paths=repository_paths,
            )
        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Change impact analysis failed."
            )
            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=None,
                status="impact_analysis_failed",
                errors=(str(exc),),
                metadata={
                    **requirement_analysis_metadata,
                    "change_impact_analysis": {"error": str(exc)},
                },
            )

        requirement_analysis_metadata = {
            **requirement_analysis_metadata,
            "change_impact_analysis": impact_analysis.to_dict(),
        }

        logger.info(
            "[DevelopmentAgent] Change impact analyzed | direct=%s | dependent=%s | related=%s | affected=%s | confidence=%s",
            len(impact_analysis.direct_targets),
            len(impact_analysis.dependent_targets),
            len(impact_analysis.related_targets),
            len(impact_analysis.affected_files),
            impact_analysis.confidence,
        )

        if impact_analysis.blocked:
            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=None,
                status="impact_blocked",
                errors=(
                    "Change impact analysis identified protected repository targets: "
                    + ", ".join(impact_analysis.protected_affected),
                ),
                metadata=requirement_analysis_metadata,
            )

        # ----------------------------------------------------
        # Isolated workspace
        # ----------------------------------------------------

        try:
            workspace = (
                self.workspace_manager.create(
                    workspace_id=workspace_id
                )
            )

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Workspace creation failed."
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=None,
                status="workspace_creation_failed",
                errors=(str(exc),),
            )

        logger.info(
            "[DevelopmentAgent] Isolated workspace created | "
            "workspace=%s",
            workspace.source_root,
        )

        # ----------------------------------------------------
        # CRITICAL: verify workspace before LLM access
        # ----------------------------------------------------

        (
            workspace_valid,
            workspace_info,
            workspace_error,
        ) = self._verify_workspace_repository(
            workspace
        )

        logger.info(
            "[DevelopmentAgent] Workspace verification | "
            "valid=%s | files=%s | expected=%s | sample=%s",
            workspace_valid,
            workspace_info.get(
                "file_count",
                0,
            ),
            workspace_info.get(
                "expected_file_count",
                0,
            ),
            workspace_info.get(
                "sample_files",
                [],
            )[:5],
        )

        if not workspace_valid:
            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                status="workspace_verification_failed",
                errors=(
                    workspace_error
                    or "Workspace verification failed.",
                ),
                metadata={
                    "workspace_verification": workspace_info,
                },
            )

        # ----------------------------------------------------
        # Inspect the isolated repository itself
        # ----------------------------------------------------

        try:
            workspace_repository_paths = (
                self._repository_paths(
                    workspace.source_root
                )
            )

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Workspace repository "
                "inspection failed."
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                status="workspace_repository_inspection_failed",
                errors=(str(exc),),
            )

        logger.info(
            "[DevelopmentAgent] Workspace repository inspection "
            "complete | files=%s",
            len(workspace_repository_paths),
        )

        if not workspace_repository_paths:
            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                status="workspace_repository_empty",
                errors=(
                    "The isolated workspace contains zero "
                    "repository files. Code generation blocked.",
                ),
                metadata={
                    "workspace_file_count": 0,
                },
            )

        # ----------------------------------------------------
        # Development services
        # ----------------------------------------------------

        guard = FilesystemGuard(
            workspace.source_root
        )

        writer = CodeWriter(
            guard
        )

        validator = DevelopmentValidator(
            guard
        )

        sandbox = DevelopmentSandbox(
            workspace.source_root
        )

        test_runner = DevelopmentTestRunner(
            sandbox
        )

        failure_analyzer = FailureAnalyzer()

        repair_engine = RepairEngine(
            max_attempts=self.max_repair_attempts
        )

        write_results: list[WriteResult] = []
        errors: list[str] = []

        generation: CodeGenerationResult | None = None

        # ----------------------------------------------------
        # Verified repository context
        # ----------------------------------------------------

        try:
            repository_context = (
                self._build_repository_context(
                    workspace
                )
            )

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Context construction failed."
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                status="context_build_failed",
                errors=(str(exc),),
                metadata={
                    "workspace_file_count": len(
                        workspace_repository_paths
                    ),
                },
            )

        logger.info(
            "[DevelopmentAgent] Repository context prepared | "
            "workspace_files=%s | context_files=%s | "
            "context_chars=%s | sensitive_excluded=%s",
            repository_context.get(
                "workspace_file_count",
                0,
            ),
            repository_context.get(
                "file_count",
                0,
            ),
            repository_context.get(
                "context_chars",
                0,
            ),
            repository_context.get(
                "safety",
                {},
            ).get(
                "sensitive_files_excluded",
                0,
            ),
        )

        # ----------------------------------------------------
        # Generate changes
        # ----------------------------------------------------

        generated_changes: list[GeneratedChange] = []

        if changes is None:
            generation_prompt = (
                self._build_generation_prompt(
                    requirement,
                    plan,
                    repository_context,
                )
            )

            generation = await self._generate_code(
                generation_prompt,
                {
                    "requirement": requirement.to_dict(),
                    "plan": plan.to_dict(),
                    "change_impact": impact_analysis.to_dict(),
                    "repository": repository_context,
                    "workspace": {
                        "id": workspace.workspace_id,
                        "root": str(
                            workspace.source_root
                        ),
                        "file_count": len(
                            workspace_repository_paths
                        ),
                    },
                },
            )

            if not generation.success:
                logger.error(
                    "[DevelopmentAgent] Code generation failed | "
                    "error=%s",
                    generation.error,
                )

                return DevelopmentReport(
                    success=False,
                    requirement=requirement,
                    plan=plan,
                    workspace=workspace,
                    generation=generation,
                    status="code_generation_failed",
                    errors=(
                        generation.error
                        or "Code generation failed.",
                    ),
                    metadata={
                        "workspace_file_count": len(
                            workspace_repository_paths
                        ),
                        "context_file_count": repository_context.get(
                            "file_count",
                            0,
                        ),
                    },
                )

            (
                generated_changes,
                generation_errors,
            ) = self._validate_generated_changes(
                generation.changes,
                workspace,
                requirement=requirement,
                plan=plan,
            )

            if generation_errors:
                generation = CodeGenerationResult(
                    success=False,
                    summary=generation.summary,
                    reasoning=generation.reasoning,
                    changes=tuple(
                        generated_changes
                    ),
                    tests=generation.tests,
                    raw_response=generation.raw_response,
                    error=" ".join(
                        generation_errors
                    ),
                    metadata={
                        "validation_errors": generation_errors,
                    },
                )

                return DevelopmentReport(
                    success=False,
                    requirement=requirement,
                    plan=plan,
                    workspace=workspace,
                    generation=generation,
                    status="generated_changes_rejected",
                    errors=tuple(
                        generation_errors
                    ),
                )

        else:
            # Backwards-compatible caller supplied changes.
            for path, content in changes:
                normalized, path_error = (
                    self._safe_relative_path(path)
                )

                if path_error or normalized is None:
                    return DevelopmentReport(
                        success=False,
                        requirement=requirement,
                        plan=plan,
                        workspace=workspace,
                        status="provided_changes_rejected",
                        errors=(
                            path_error
                            or "Invalid provided path.",
                        ),
                    )

                target = (
                    workspace.source_root
                    / normalized
                )

                operation = (
                    "modify"
                    if target.exists()
                    else "create"
                )

                generated_changes.append(
                    GeneratedChange(
                        path=normalized,
                        operation=operation,
                        content=content,
                    )
                )

            (
                generated_changes,
                generation_errors,
            ) = self._validate_generated_changes(
                tuple(generated_changes),
                workspace,
                requirement=requirement,
                plan=plan,
            )

            if generation_errors:
                return DevelopmentReport(
                    success=False,
                    requirement=requirement,
                    plan=plan,
                    workspace=workspace,
                    status="provided_changes_rejected",
                    errors=tuple(
                        generation_errors
                    ),
                )

        if not generated_changes:
            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                generation=generation,
                status="no_changes_generated",
                errors=(
                    "The development engine generated no "
                    "file changes.",
                ),
            )

        logger.info(
            "[DevelopmentAgent] Changes approved by "
            "deterministic safety layer | count=%s | paths=%s",
            len(generated_changes),
            [
                change.path
                for change in generated_changes
            ],
        )

        # ----------------------------------------------------
        # Apply inside workspace
        # ----------------------------------------------------

        try:
            write_results.extend(
                self._apply_generated_changes(
                    writer,
                    generated_changes,
                )
            )

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Workspace write failed."
            )

            errors.append(str(exc))

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(write_results),
                generation=generation,
                status="write_failed",
                errors=tuple(errors),
            )

        # ----------------------------------------------------
        # Exact deterministic acceptance
        # ----------------------------------------------------

        acceptance_error = (
            self._check_exact_content_requirement(
                requirement,
                workspace,
            )
        )

        if acceptance_error:
            failure = FailureAnalysis(
                failed=True,
                summary=acceptance_error,
                repairable=True,
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(write_results),
                generation=generation,
                failure=failure,
                status="acceptance_check_failed",
                errors=(acceptance_error,),
            )

        # ----------------------------------------------------
        # Static validation
        # ----------------------------------------------------

        try:
            validation = (
                validator.validate_repository()
            )

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Static validation failed "
                "to execute."
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(write_results),
                generation=generation,
                status="validation_execution_failed",
                errors=(str(exc),),
            )

        if not validation.valid:
            failure = FailureAnalysis(
                failed=True,
                summary="Static validation failed.",
                repairable=True,
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(write_results),
                validation=validation,
                generation=generation,
                failure=failure,
                status="validation_failed",
                metadata=self._report_metadata(
                    generated_changes,
                    extra={
                        "workspace_file_count": len(
                            workspace_repository_paths
                        ),
                        "context_file_count": repository_context.get(
                            "file_count",
                            0,
                        ),
                    },
                ),
            )

        # ----------------------------------------------------
        # Tests
        # ----------------------------------------------------

        selected_tests = (
            self._select_test_paths(
                workspace,
                generation,
                test_paths,
                generated_changes,
            )
        )

        logger.info(
            "[DevelopmentAgent] Selected tests | tests=%s",
            selected_tests,
        )

        if not selected_tests:
            return DevelopmentReport(
                success=True,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(write_results),
                validation=validation,
                generation=generation,
                status="validated_no_tests",
                metadata=self._report_metadata(
                    generated_changes,
                    extra={
                        "tests_selected": [],
                        "final_acceptance_passed": True,
                        "final_validation_passed": True,
                        "workspace_file_count": len(
                            workspace_repository_paths
                        ),
                        "context_file_count": repository_context.get(
                            "file_count",
                            0,
                        ),
                    },
                ),
            )

        # ----------------------------------------------------
        # Initial tests
        # ----------------------------------------------------

        try:
            test_result = (
                await test_runner.run_targeted_tests(
                    selected_tests
                )
            )

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Test execution failed."
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(write_results),
                validation=validation,
                generation=generation,
                status="test_execution_failed",
                errors=(str(exc),),
            )

        if not test_result.results:
            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(write_results),
                validation=validation,
                generation=generation,
                status="test_result_missing",
                errors=(
                    "Test runner returned no test result.",
                ),
            )

        initial_test = test_result.results[-1]

        if test_result.passed:
            final_acceptance_error = (
                self._check_exact_content_requirement(
                    requirement,
                    workspace,
                )
            )

            if final_acceptance_error:
                return DevelopmentReport(
                    success=False,
                    requirement=requirement,
                    plan=plan,
                    workspace=workspace,
                    writes=tuple(write_results),
                    validation=validation,
                    tests=initial_test,
                    generation=generation,
                    failure=FailureAnalysis(
                        failed=True,
                        summary=final_acceptance_error,
                        repairable=True,
                    ),
                    status="acceptance_check_failed",
                    errors=(
                        final_acceptance_error,
                    ),
                )

            return DevelopmentReport(
                success=True,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(write_results),
                validation=validation,
                tests=initial_test,
                generation=generation,
                status="tests_passed",
                metadata=self._report_metadata(
                    generated_changes,
                    extra={
                        "tests_selected": selected_tests,
                        "final_acceptance_passed": True,
                        "final_validation_passed": True,
                        "workspace_file_count": len(
                            workspace_repository_paths
                        ),
                        "context_file_count": repository_context.get(
                            "file_count",
                            0,
                        ),
                    },
                ),
            )

        # ----------------------------------------------------
        # Bounded repair
        # ----------------------------------------------------

        async def apply_repair(
            analysis: FailureAnalysis,
            attempt: int,
        ) -> bool:
            if self.code_generator is None:
                return False

            current_context = (
                self._build_repository_context(
                    workspace
                )
            )

            repair_prompt = (
                self._build_generation_prompt(
                    requirement,
                    plan,
                    current_context,
                    failure=analysis,
                    previous_changes=generated_changes,
                )
            )

            repair_generation = (
                await self._generate_code(
                    repair_prompt,
                    {
                        "requirement": (
                            requirement.to_dict()
                        ),
                        "plan": plan.to_dict(),
                        "repository": current_context,
                        "failure": analysis.to_dict(),
                        "attempt": attempt,
                    },
                )
            )

            if not repair_generation.success:
                logger.warning(
                    "[DevelopmentAgent] Repair generation "
                    "failed | attempt=%s | error=%s",
                    attempt,
                    repair_generation.error,
                )
                return False

            (
                repaired_changes,
                repair_errors,
            ) = self._validate_generated_changes(
                repair_generation.changes,
                workspace,
                requirement=requirement,
                plan=plan,
            )

            if repair_errors:
                logger.warning(
                    "[DevelopmentAgent] Repair changes rejected | "
                    "attempt=%s | errors=%s",
                    attempt,
                    repair_errors,
                )
                return False

            if not repaired_changes:
                return False

            try:
                repair_writes = (
                    self._apply_generated_changes(
                        writer,
                        repaired_changes,
                    )
                )

                write_results.extend(
                    repair_writes
                )

                validation_after_repair = (
                    validator.validate_repository()
                )

                if not validation_after_repair.valid:
                    return False

                acceptance_after_repair = (
                    self._check_exact_content_requirement(
                        requirement,
                        workspace,
                    )
                )

                if acceptance_after_repair:
                    return False

                generated_changes.extend(
                    repaired_changes
                )

                logger.info(
                    "[DevelopmentAgent] Repair attempt %s "
                    "applied successfully.",
                    attempt,
                )

                return True

            except Exception as exc:
                logger.warning(
                    "[DevelopmentAgent] Repair attempt %s "
                    "failed: %s",
                    attempt,
                    exc,
                )
                return False

        async def rerun() -> TestResult:
            rerun_result = (
                await test_runner.run_targeted_tests(
                    selected_tests
                )
            )

            if not rerun_result.results:
                raise RuntimeError(
                    "Test runner returned no result "
                    "during repair rerun."
                )

            return rerun_result.results[-1]

        try:
            repair_result = (
                await repair_engine.repair(
                    initial_test,
                    analyze=failure_analyzer.analyze,
                    apply_repair=apply_repair,
                    rerun=rerun,
                )
            )

        except Exception as exc:
            logger.exception(
                "[DevelopmentAgent] Repair execution failed."
            )

            failure = (
                failure_analyzer.analyze(
                    initial_test
                )
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(write_results),
                validation=validation,
                tests=initial_test,
                generation=generation,
                failure=failure,
                status="repair_execution_failed",
                errors=(str(exc),),
            )

        # ----------------------------------------------------
        # Final verification
        # ----------------------------------------------------

        try:
            final_validation = (
                validator.validate_repository()
            )

        except Exception as exc:
            final_validation = validation
            errors.append(
                f"Final validation execution failed: {exc}"
            )

        final_acceptance_error = (
            self._check_exact_content_requirement(
                requirement,
                workspace,
            )
        )

        if final_acceptance_error:
            errors.append(
                final_acceptance_error
            )

        final_success = bool(
            repair_result.success
            and final_validation.valid
            and not final_acceptance_error
        )

        failure = None

        if not final_success:
            failure = (
                failure_analyzer.analyze(
                    initial_test
                )
            )

        if final_success:
            status = "repair_succeeded"
        elif repair_result.success:
            status = (
                "repair_completed_but_final_validation_failed"
            )
        else:
            status = "tests_failed"

        return DevelopmentReport(
            success=final_success,
            requirement=requirement,
            plan=plan,
            workspace=workspace,
            writes=tuple(write_results),
            validation=final_validation,
            tests=initial_test,
            repair=repair_result,
            generation=generation,
            failure=failure,
            status=status,
            errors=tuple(errors),
            metadata=self._report_metadata(
                generated_changes,
                extra={
                    **requirement_analysis_metadata,
                    "tests_selected": selected_tests,
                    "final_acceptance_passed": (
                        final_acceptance_error is None
                    ),
                    "final_validation_passed": (
                        final_validation.valid
                    ),
                    "repair_attempts": getattr(
                        repair_result,
                        "attempts",
                        None,
                    ),
                    "workspace_file_count": len(
                        workspace_repository_paths
                    ),
                    "context_file_count": repository_context.get(
                        "file_count",
                        0,
                    ),
                },
            ),
        )

    # ========================================================
    # Default tests
    # ========================================================

    @staticmethod
    def _default_test_paths(
        workspace: WorkspaceInfo,
    ) -> list[str]:
        tests_dir = (
            workspace.source_root
            / "tests"
        )

        if not tests_dir.is_dir():
            return []

        test_files: list[str] = []

        for path in sorted(
            tests_dir.rglob("test_*.py")
        ):
            if not path.is_file():
                continue

            try:
                relative = path.relative_to(
                    workspace.source_root
                )
            except ValueError:
                continue

            value = relative.as_posix()

            if value not in test_files:
                test_files.append(value)

        for path in sorted(
            tests_dir.rglob("*_test.py")
        ):
            if not path.is_file():
                continue

            try:
                relative = path.relative_to(
                    workspace.source_root
                )
            except ValueError:
                continue

            value = relative.as_posix()

            if value not in test_files:
                test_files.append(value)

        return test_files
