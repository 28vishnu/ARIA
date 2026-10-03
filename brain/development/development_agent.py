from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from inspect import isawaitable
from pathlib import Path
from typing import Any, Awaitable, Callable

from .change_planner import ChangePlan, ChangePlanner
from .code_writer import CodeWriter, WriteResult
from .failure_analyzer import FailureAnalysis, FailureAnalyzer
from .filesystem_guard import FilesystemGuard
from .repository_manager import RepositoryManager
from .requirement_parser import Requirement, RequirementParser
from .repair_engine import RepairEngine, RepairResult
from .sandbox import DevelopmentSandbox
from .test_runner import (
    DevelopmentTestRunner,
    TestResult,
)
from .validator import (
    DevelopmentValidator,
    ValidationResult,
)
from .workspace import (
    DevelopmentWorkspace,
    WorkspaceInfo,
)


logger = logging.getLogger("aria")


# ============================================================
# Types
# ============================================================

CodeGenerator = Callable[
    [str, dict[str, Any]],
    str | dict[str, Any] | Awaitable[str | dict[str, Any]],
]


# ============================================================
# Generated change model
# ============================================================

@dataclass(frozen=True)
class GeneratedChange:
    """
    A single AI-generated repository change.

    The AI may only describe file operations.
    Actual filesystem writes are performed by CodeWriter
    after the normal Phase 1 safety checks.
    """

    path: str
    operation: str
    content: str = ""

    def to_tuple(self) -> tuple[str, str]:
        return (
            self.path,
            self.content,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "operation": self.operation,
            "content": self.content,
        }


@dataclass(frozen=True)
class CodeGenerationResult:
    """
    Normalized result returned by the code-generation layer.
    """

    success: bool
    summary: str = ""
    reasoning: str = ""
    changes: tuple[GeneratedChange, ...] = ()
    tests: tuple[str, ...] = ()
    raw_response: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

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


# ============================================================
# Development report
# ============================================================

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

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

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


# ============================================================
# Development Agent
# ============================================================

class DevelopmentAgent:
    """
    Phase 1 self-development agent.

    Workflow:

        requirement
            ↓
        repository inspection
            ↓
        requirement parsing
            ↓
        change planning
            ↓
        isolated workspace
            ↓
        AI code generation
            ↓
        guarded file writes
            ↓
        static validation
            ↓
        tests
            ↓
        bounded repair
            ↓
        development report

    Important safety properties:

    - Production repository is never directly modified.
    - AI output is treated as untrusted data.
    - AI cannot execute arbitrary commands.
    - AI cannot directly write to disk.
    - File writes pass through CodeWriter + FilesystemGuard.
    - Protected/high-risk paths remain governed by the planner.
    - Tests run inside the development sandbox.
    - Repair attempts are bounded.
    - GitHub/deployment/rollback are outside this class.
    """

    # Maximum amount of repository context sent to the
    # generation layer.
    DEFAULT_MAX_CONTEXT_CHARS = 120_000

    # Maximum generated response accepted from an AI provider.
    DEFAULT_MAX_GENERATION_CHARS = 500_000

    # Prevent an AI response from creating an unreasonable
    # number of files in one development request.
    DEFAULT_MAX_GENERATED_FILES = 30

    # Prevent pathological individual generated files.
    DEFAULT_MAX_FILE_CHARS = 2_000_000

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
    ) -> None:

        self.repository_manager = (
            repository_manager
        )

        self.workspace_manager = (
            workspace_manager
        )

        self.requirement_parser = (
            RequirementParser()
        )

        self.change_planner = (
            ChangePlanner()
        )

        self.code_generator = (
            code_generator
        )

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
    # Repository inspection
    # ========================================================

    def _repository_paths(self) -> list[str]:

        snapshot = (
            self.repository_manager.inspect()
        )

        paths: list[str] = []

        for file_info in snapshot.files:

            paths.append(
                str(file_info.path)
            )

        return paths

    def _workspace_paths(
        self,
        workspace: WorkspaceInfo,
    ) -> list[str]:

        paths: list[str] = []

        for path in workspace.source_root.rglob("*"):

            if not path.is_file():
                continue

            try:
                relative = path.relative_to(
                    workspace.source_root
                )

            except ValueError:
                continue

            paths.append(
                relative.as_posix()
            )

        return paths

    def _build_repository_context(
        self,
        workspace: WorkspaceInfo,
    ) -> dict[str, Any]:
        """
        Build a bounded snapshot for the code-generation layer.

        The model receives source context but never receives an
        instruction that it may directly execute commands.
        """

        files: list[dict[str, Any]] = []

        total_chars = 0

        for path in sorted(
            workspace.source_root.rglob("*")
        ):

            if not path.is_file():
                continue

            try:
                relative = path.relative_to(
                    workspace.source_root
                )

            except ValueError:
                continue

            relative_path = relative.as_posix()

            # Skip obvious generated/cache content.
            if any(
                part in {
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
                for part in relative.parts
            ):
                continue

            try:
                size = path.stat().st_size

            except OSError:
                continue

            # Avoid enormous binary/media files.
            if size > 2_000_000:
                continue

            try:
                text = path.read_text(
                    encoding="utf-8"
                )

            except (
                UnicodeDecodeError,
                OSError,
            ):
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

        return {
            "repository_root": ".",
            "file_count": len(files),
            "context_chars": total_chars,
            "files": files,
        }

    # ========================================================
    # Generation prompt
    # ========================================================

    def _build_generation_prompt(
        self,
        requirement: Requirement,
        plan: ChangePlan,
        repository_context: dict[str, Any],
        *,
        failure: FailureAnalysis | None = None,
        previous_changes: list[GeneratedChange] | None = None,
    ) -> str:
        """
        Construct the strict code-generation contract.

        The generator must return JSON only.
        """

        failure_text = ""

        if failure is not None:

            failure_text = (
                "\n\nPREVIOUS TEST FAILURE:\n"
                + json.dumps(
                    failure.to_dict(),
                    ensure_ascii=False,
                    indent=2,
                )
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
            "changes that satisfy the Master's requirement.\n"
            "\n"
            "You are NOT allowed to execute commands.\n"
            "You are NOT allowed to deploy.\n"
            "You are NOT allowed to push to GitHub.\n"
            "You are NOT allowed to modify production directly.\n"
            "You are NOT allowed to invent secrets, tokens, "
            "credentials, API keys, or environment values.\n"
            "\n"
            "Your output is data only. Return ONE valid JSON "
            "object and nothing else.\n"
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
            '  "tests": ["test path or test description"]\n'
            "}\n"
            "\n"
            "Rules:\n"
            "1. Paths must be repository-relative.\n"
            "2. Never use absolute paths.\n"
            "3. Never use '..' path traversal.\n"
            "4. For create/modify, provide complete file "
            "content.\n"
            "5. For delete, content must be an empty string.\n"
            "6. Make the smallest safe change that satisfies "
            "the requirement.\n"
            "7. Preserve existing behavior unless the "
            "requirement explicitly changes it.\n"
            "8. Do not modify protected/security/deployment "
            "files unless the requirement explicitly requires "
            "it; such changes will still be reviewed by ARIA's "
            "safety layer.\n"
            "9. Do not include Markdown fences.\n"
            "10. Do not include comments outside the JSON object.\n"
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
            "CURRENT REPOSITORY CONTEXT:\n"
            f"{json.dumps(repository_context, ensure_ascii=False, indent=2)}"
            f"{failure_text}"
            f"{previous_text}"
        )

    # ========================================================
    # AI result parsing
    # ========================================================

    @staticmethod
    def _strip_code_fences(
        text: str,
    ) -> str:

        value = text.strip()

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

            raw_response = json.dumps(
                response,
                ensure_ascii=False,
            )

        else:

            raw_response = str(response)

            if len(raw_response) > (
                self.max_generation_chars
            ):

                return CodeGenerationResult(
                    success=False,
                    raw_response=raw_response[
                        :10_000
                    ],
                    error=(
                        "Generated response exceeds the "
                        "maximum allowed size."
                    ),
                )

            cleaned = self._strip_code_fences(
                raw_response
            )

            try:
                payload = json.loads(
                    cleaned
                )

            except json.JSONDecodeError as exc:

                return CodeGenerationResult(
                    success=False,
                    raw_response=raw_response[
                        :20_000
                    ],
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

        if not isinstance(
            changes_payload,
            list,
        ):

            return CodeGenerationResult(
                success=False,
                raw_response=raw_response[:20_000],
                error=(
                    "'changes' must be a JSON array."
                ),
            )

        if len(changes_payload) > (
            self.max_generated_files
        ):

            return CodeGenerationResult(
                success=False,
                raw_response=raw_response[:20_000],
                error=(
                    "AI requested too many file changes."
                ),
            )

        generated: list[GeneratedChange] = []

        errors: list[str] = []

        for index, item in enumerate(
            changes_payload
        ):

            if not isinstance(item, dict):

                errors.append(
                    f"Change {index} is not an object."
                )

                continue

            path = str(
                item.get("path", "")
            ).strip()

            operation = str(
                item.get(
                    "operation",
                    "modify",
                )
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
                    f"Change {index} has invalid "
                    f"operation '{operation}'."
                )

                continue

            if not isinstance(
                content,
                str,
            ):

                errors.append(
                    f"Change {index} content must be "
                    "a string."
                )

                continue

            if len(content) > (
                self.max_generated_file_chars
            ):

                errors.append(
                    f"Change {index} exceeds the maximum "
                    "file size."
                )

                continue

            generated.append(
                GeneratedChange(
                    path=path,
                    operation=operation,
                    content=content,
                )
            )

        if errors:

            return CodeGenerationResult(
                success=False,
                summary=str(
                    payload.get(
                        "summary",
                        "",
                    )
                ),
                reasoning=str(
                    payload.get(
                        "reasoning",
                        "",
                    )
                ),
                changes=tuple(generated),
                tests=tuple(
                    str(item)
                    for item in payload.get(
                        "tests",
                        []
                    )
                    if isinstance(
                        item,
                        str,
                    )
                ),
                raw_response=raw_response[:20_000],
                error=" ".join(errors),
            )

        return CodeGenerationResult(
            success=True,
            summary=str(
                payload.get(
                    "summary",
                    "",
                )
            ),
            reasoning=str(
                payload.get(
                    "reasoning",
                    "",
                )
            ),
            changes=tuple(generated),
            tests=tuple(
                str(item)
                for item in payload.get(
                    "tests",
                    []
                )
                if isinstance(
                    item,
                    str,
                )
            ),
            raw_response=raw_response[
                :20_000
            ],
        )

    # ========================================================
    # Generator invocation
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
                error=(
                    f"Code generation failed: {exc}"
                ),
            )

    # ========================================================
    # Generated path validation
    # ========================================================

    @staticmethod
    def _normalize_generated_path(
        path: str,
    ) -> str:

        value = str(path).strip()

        value = value.replace(
            "\\",
            "/",
        )

        while value.startswith("./"):
            value = value[2:]

        return value

    def _validate_generated_changes(
        self,
        changes: tuple[GeneratedChange, ...],
        workspace: WorkspaceInfo,
    ) -> tuple[
        list[GeneratedChange],
        list[str],
    ]:

        valid: list[GeneratedChange] = []

        errors: list[str] = []

        seen: set[str] = set()

        for change in changes:

            path = self._normalize_generated_path(
                change.path
            )

            if not path:

                errors.append(
                    "Generated change contains an empty path."
                )

                continue

            candidate = Path(path)

            if candidate.is_absolute():

                errors.append(
                    f"Absolute path rejected: {path}"
                )

                continue

            if ".." in candidate.parts:

                errors.append(
                    f"Path traversal rejected: {path}"
                )

                continue

            if path in seen:

                errors.append(
                    f"Duplicate generated path: {path}"
                )

                continue

            seen.add(path)

            if (
                change.operation == "delete"
                and change.content
            ):

                errors.append(
                    f"Delete operation must not contain "
                    f"content: {path}"
                )

                continue

            if (
                change.operation in {
                    "create",
                    "modify",
                }
                and not change.content
            ):

                errors.append(
                    f"{change.operation} operation has empty "
                    f"content: {path}"
                )

                continue

            full_path = (
                workspace.source_root / path
            )

            try:
                full_path.resolve().relative_to(
                    workspace.source_root.resolve()
                )

            except ValueError:

                errors.append(
                    f"Generated path escapes workspace: {path}"
                )

                continue

            valid.append(
                GeneratedChange(
                    path=path,
                    operation=change.operation,
                    content=change.content,
                )
            )

        return valid, errors

    # ========================================================
    # Apply generated changes
    # ========================================================

    def _apply_generated_changes(
        self,
        writer: CodeWriter,
        changes: list[GeneratedChange],
    ) -> list[WriteResult]:

        write_operations: list[
            tuple[str, str]
        ] = []

        for change in changes:

            if change.operation == "delete":

                # CodeWriter's delete API is intentionally
                # called separately so deletion remains
                # explicit.
                continue

            write_operations.append(
                (
                    change.path,
                    change.content,
                )
            )

        results: list[WriteResult] = []

        if write_operations:

            results.extend(
                writer.apply_files(
                    write_operations,
                    backup=True,
                )
            )

        for change in changes:

            if change.operation != "delete":
                continue

            result = writer.delete_file(
                change.path
            )

            results.append(
                result
            )

        return results

    # ========================================================
    # Development workflow
    # ========================================================

    async def develop(
        self,
        requirement_text: str,
        *,
        changes: list[tuple[str, str]] | None = None,
        test_paths: list[str] | None = None,
        workspace_id: str | None = None,
    ) -> DevelopmentReport:

        requirement = (
            self.requirement_parser.parse(
                requirement_text
            )
        )

        # ----------------------------------------------------
        # Repository inspection
        # ----------------------------------------------------

        try:

            repository_paths = (
                self._repository_paths()
            )

        except Exception as exc:

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=None,
                workspace=None,
                status="repository_inspection_failed",
                errors=(str(exc),),
            )

        # ----------------------------------------------------
        # Planning
        # ----------------------------------------------------

        plan = self.change_planner.plan(
            requirement,
            existing_paths=repository_paths,
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
        # Isolated workspace
        # ----------------------------------------------------

        try:

            workspace = (
                self.workspace_manager.create(
                    workspace_id=workspace_id
                )
            )

        except Exception as exc:

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=None,
                status="workspace_creation_failed",
                errors=(str(exc),),
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

        write_results: list[
            WriteResult
        ] = []

        errors: list[str] = []

        generation: CodeGenerationResult | None = None

        # ----------------------------------------------------
        # Build repository context
        # ----------------------------------------------------

        try:

            repository_context = (
                self._build_repository_context(
                    workspace
                )
            )

        except Exception as exc:

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                status="context_build_failed",
                errors=(str(exc),),
            )

        # ----------------------------------------------------
        # Generate changes if caller did not provide them
        # ----------------------------------------------------

        generated_changes: list[
            GeneratedChange
        ] = []

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
                    "repository": repository_context,
                    "workspace": str(
                        workspace.source_root
                    ),
                },
            )

            if not generation.success:

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
                )

            generated_changes, generation_errors = (
                self._validate_generated_changes(
                    generation.changes,
                    workspace,
                )
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
                        "validation_errors": (
                            generation_errors
                        )
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

            generated_changes = [
                GeneratedChange(
                    path=path,
                    operation="modify",
                    content=content,
                )
                for path, content in changes
            ]

            generated_changes, generation_errors = (
                self._validate_generated_changes(
                    tuple(generated_changes),
                    workspace,
                )
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

        # ----------------------------------------------------
        # Apply generated changes
        # ----------------------------------------------------

        try:

            write_results.extend(
                self._apply_generated_changes(
                    writer,
                    generated_changes,
                )
            )

        except Exception as exc:

            errors.append(
                str(exc)
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(
                    write_results
                ),
                generation=generation,
                status="write_failed",
                errors=tuple(errors),
            )

        # ----------------------------------------------------
        # Static validation
        # ----------------------------------------------------

        try:

            validation = (
                validator.validate_repository()
            )

        except Exception as exc:

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(
                    write_results
                ),
                generation=generation,
                status="validation_execution_failed",
                errors=(str(exc),),
            )

        if not validation.valid:

            failure = FailureAnalysis(
                failed=True,
                summary=(
                    "Static validation failed."
                ),
                repairable=True,
            )

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(
                    write_results
                ),
                validation=validation,
                generation=generation,
                status="validation_failed",
                failure=failure,
            )

        # ----------------------------------------------------
        # Select tests
        # ----------------------------------------------------

        selected_tests = (
            test_paths
            or (
                list(generation.tests)
                if generation
                and generation.tests
                else self._default_test_paths(
                    workspace
                )
            )
        )

        if not selected_tests:

            return DevelopmentReport(
                success=True,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(
                    write_results
                ),
                validation=validation,
                generation=generation,
                status="validated_no_tests",
                metadata={
                    "generated_change_count": len(
                        generated_changes
                    ),
                    "generated_files": [
                        change.path
                        for change in generated_changes
                    ],
                },
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

            return DevelopmentReport(
                success=False,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(
                    write_results
                ),
                validation=validation,
                generation=generation,
                status="test_execution_failed",
                errors=(str(exc),),
            )

        if test_result.passed:

            return DevelopmentReport(
                success=True,
                requirement=requirement,
                plan=plan,
                workspace=workspace,
                writes=tuple(
                    write_results
                ),
                validation=validation,
                tests=test_result.results[-1],
                generation=generation,
                status="tests_passed",
                metadata={
                    "generated_change_count": len(
                        generated_changes
                    ),
                    "generated_files": [
                        change.path
                        for change in generated_changes
                    ],
                },
            )

        # ----------------------------------------------------
        # Failure analysis + bounded repair
        # ----------------------------------------------------

        initial_test = (
            test_result.results[-1]
        )

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
                    "failed on attempt %s: %s",
                    attempt,
                    repair_generation.error,
                )

                return False

            repaired_changes, repair_errors = (
                self._validate_generated_changes(
                    repair_generation.changes,
                    workspace,
                )
            )

            if repair_errors:

                logger.warning(
                    "[DevelopmentAgent] Repair changes "
                    "rejected: %s",
                    repair_errors,
                )

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

                    logger.warning(
                        "[DevelopmentAgent] Repair attempt "
                        "%s produced invalid source.",
                        attempt,
                    )

                    return False

                generated_changes.extend(
                    repaired_changes
                )

                return True

            except Exception as exc:

                logger.warning(
                    "[DevelopmentAgent] Repair attempt "
                    "%s failed: %s",
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

            return (
                rerun_result.results[-1]
            )

        try:

            repair_result = (
                await repair_engine.repair(
                    initial_test,
                    analyze=(
                        failure_analyzer.analyze
                    ),
                    apply_repair=apply_repair,
                    rerun=rerun,
                )
            )

        except Exception as exc:

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
                writes=tuple(
                    write_results
                ),
                validation=validation,
                tests=initial_test,
                generation=generation,
                failure=failure,
                status="repair_execution_failed",
                errors=(str(exc),),
            )

        failure = (
            failure_analyzer.analyze(
                initial_test
            )
        )

        return DevelopmentReport(
            success=repair_result.success,
            requirement=requirement,
            plan=plan,
            workspace=workspace,
            writes=tuple(
                write_results
            ),
            validation=validation,
            tests=initial_test,
            repair=repair_result,
            generation=generation,
            failure=failure,
            status=(
                "repair_succeeded"
                if repair_result.success
                else "tests_failed"
            ),
            errors=tuple(errors),
            metadata={
                "generated_change_count": len(
                    generated_changes
                ),
                "generated_files": [
                    change.path
                    for change in generated_changes
                ],
            },
        )

    # ========================================================
    # Default tests
    # ========================================================

    @staticmethod
    def _default_test_paths(
        workspace: WorkspaceInfo,
    ) -> list[str]:

        tests_dir = (
            workspace.source_root / "tests"
        )

        if tests_dir.is_dir():
            return ["tests"]

        return []