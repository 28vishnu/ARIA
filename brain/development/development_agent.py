from __future__ import annotations

from dataclasses import dataclass, field
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
            "status": self.status,
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }


class DevelopmentAgent:
    """
    Executes the development workflow inside an isolated
    development workspace.

    The agent coordinates repository inspection, planning,
    writing, validation, testing, failure analysis, and
    bounded repair.

    It does NOT:

    - modify the production repository directly
    - push to GitHub
    - deploy
    - perform rollback
    - approve its own deployment
    """

    def __init__(
        self,
        repository_manager: RepositoryManager,
        workspace_manager: DevelopmentWorkspace,
        *,
        max_repair_attempts: int = 3,
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

        self.max_repair_attempts = max(
            1,
            int(max_repair_attempts),
        )

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
            if path.is_file():
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

        try:

            if changes:

                write_results.extend(
                    writer.apply_files(
                        changes,
                        backup=True,
                    )
                )

            validation = (
                validator.validate_repository()
            )

            if not validation.valid:

                return DevelopmentReport(
                    success=False,
                    requirement=requirement,
                    plan=plan,
                    workspace=workspace,
                    writes=tuple(
                        write_results
                    ),
                    validation=validation,
                    status="validation_failed",
                    failure=FailureAnalysis(
                        failed=True,
                        summary=(
                            "Static validation "
                            "failed."
                        ),
                        repairable=True,
                    ),
                )

            selected_tests = (
                test_paths
                or self._default_test_paths(
                    workspace
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
                    status="validated_no_tests",
                )

            test_result = (
                await test_runner.run_targeted_tests(
                    selected_tests
                )
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
                    status="tests_passed",
                )

            initial_test = (
                test_result.results[-1]
            )

            async def apply_repair(
                analysis: FailureAnalysis,
                attempt: int,
            ) -> bool:

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
                failure=failure,
                status=(
                    "repair_succeeded"
                    if repair_result.success
                    else "tests_failed"
                ),
                errors=tuple(errors),
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
                status="development_failed",
                errors=tuple(errors),
            )

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