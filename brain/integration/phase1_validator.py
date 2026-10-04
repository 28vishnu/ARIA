"""
ARIA Phase 1 - Final Integration Validator

Purpose:
    Final structural and compatibility validation for the Phase 1
    autonomous AI architecture.

This validator is intentionally read-only.

It does NOT:
    - execute user actions
    - modify source files
    - call an LLM
    - modify MongoDB
    - modify the existing canonical Planner / Executor
    - deploy anything

Run from ARIA-main:

    python -m brain.integration.phase1_validator

or:

    python brain/integration/phase1_validator.py
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================
# RESULT MODELS
# ============================================================


@dataclass
class ValidationIssue:
    level: str
    component: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "level": self.level,
            "component": self.component,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    passed: bool
    total_checks: int
    passed_checks: int
    failed_checks: int
    warnings: int
    issues: List[ValidationIssue] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "warnings": self.warnings,
            "issues": [
                issue.as_dict()
                for issue in self.issues
            ],
        }


# ============================================================
# VALIDATOR
# ============================================================


class Phase1Validator:
    """
    Read-only validator for the ARIA Phase 1 architecture.
    """

    EXPECTED_FILES = {
        # Existing canonical architecture
        "canonical_task":
            "brain/task.py",

        "canonical_plan":
            "brain/plan.py",

        "canonical_planner":
            "brain/planning/planner.py",

        "canonical_executor":
            "brain/executor.py",

        # Phase 1 additions
        "coding_context_selector":
            "brain/development/coding_context_selector.py",

        "code_generation_bridge":
            "brain/development/code_generation_bridge.py",

        "knowledge_architecture":
            "brain/development/knowledge_architecture.py",

        "knowledge_ingestion":
            "brain/development/knowledge_ingestion.py",

        "knowledge_retriever":
            "brain/memory/knowledge_retriever.py",

        "phase_planner":
            "brain/planning/phase_planner.py",

        "autonomous_executor":
            "brain/execution/autonomous_executor.py",

        "self_correction":
            "brain/verification/self_correction.py",

        "experience_engine":
            "brain/learning/experience_engine.py",

        "experience_adapter":
            "brain/learning/experience_adapter.py",

        "experience_consolidator":
            "brain/memory/experience_consolidator.py",

        "goal_manager":
            "brain/goals/goal_manager.py",

        "autonomous_orchestrator":
            "brain/orchestration/autonomous_orchestrator.py",

        "permission_guard":
            "brain/safety/permission_guard.py",

        "phase1_system":
            "brain/integration/phase1_system.py",

        # This validator
        "phase1_validator":
            "brain/integration/phase1_validator.py",
    }

    EXPECTED_CLASSES = {
        "brain/development/coding_context_selector.py": [
            "CodingContextSelector",
        ],

        "brain/development/code_generation_bridge.py": [
            "LLMCodeGenerationBridge",
        ],

        "brain/development/knowledge_architecture.py": [
            "KnowledgeArchitecture",
        ],

        "brain/development/knowledge_ingestion.py": [
            "KnowledgeIngestion",
        ],

        "brain/memory/knowledge_retriever.py": [
            "KnowledgeRetriever",
        ],

        "brain/planning/phase_planner.py": [
            "PhasePlanner",
        ],

        "brain/execution/autonomous_executor.py": [
            "AutonomousExecutionController",
        ],

        "brain/verification/self_correction.py": [
            "SelfCorrectionEngine",
        ],

        "brain/learning/experience_engine.py": [
            "ExperienceEngine",
        ],

        "brain/learning/experience_adapter.py": [
            "ExperienceAdapter",
        ],

        "brain/memory/experience_consolidator.py": [
            "ExperienceConsolidator",
        ],

        "brain/goals/goal_manager.py": [
            "GoalManager",
        ],

        "brain/orchestration/autonomous_orchestrator.py": [
            "AutonomousOrchestrator",
        ],

        "brain/safety/permission_guard.py": [
            "PermissionGuard",
        ],

        "brain/integration/phase1_system.py": [
            "Phase1System",
        ],

        "brain/integration/phase1_validator.py": [
            "Phase1Validator",
        ],
    }

    EXPECTED_DATACLASSES = {
        "brain/task.py": [
            "Task",
        ],

        "brain/plan.py": [
            "ExecutionPlan",
        ],

        "brain/execution/autonomous_executor.py": [
            "AutonomousExecutionResult",
        ],

        "brain/verification/self_correction.py": [
            "VerificationIssue",
            "CorrectionAction",
            "VerificationResult",
        ],

        "brain/learning/experience_engine.py": [
            "ExperienceRecord",
        ],

        "brain/learning/experience_adapter.py": [
            "AdaptationRecommendation",
        ],

        "brain/memory/experience_consolidator.py": [
            "ConsolidatedPattern",
        ],

        "brain/goals/goal_manager.py": [
            "Goal",
            "SubGoal",
        ],

        "brain/integration/phase1_system.py": [
            "Phase1Components",
        ],
    }

    REQUIRED_METHODS = {
        "brain/development/coding_context_selector.py": [
            "select",
        ],

        "brain/development/code_generation_bridge.py": [
            "generate",
        ],

        "brain/development/knowledge_ingestion.py": [
            "ingest",
        ],

        "brain/memory/knowledge_retriever.py": [
            "retrieve",
        ],

        "brain/planning/phase_planner.py": [
            "create_plan",
            "validate_plan",
        ],

        "brain/execution/autonomous_executor.py": [
            "execute",
            "cancel",
            "status",
        ],

        "brain/verification/self_correction.py": [
            "verify",
        ],

        "brain/learning/experience_engine.py": [
            "record",
            "recent",
        ],

        "brain/learning/experience_adapter.py": [
            "recommend",
        ],

        "brain/memory/experience_consolidator.py": [
            "consolidate",
        ],

        "brain/goals/goal_manager.py": [
            "add_goal",
            "get_goal",
        ],

        "brain/orchestration/autonomous_orchestrator.py": [
            "run",
            "cancel",
            "status",
        ],

        "brain/safety/permission_guard.py": [
            "check",
        ],

        "brain/integration/phase1_system.py": [
            "run",
            "status",
            "health",
        ],
    }

    # Canonical classes that must remain the single source
    # of execution/planning/task ownership.
    CANONICAL_CLASSES = {
        "brain/task.py": "Task",
        "brain/plan.py": "ExecutionPlan",
        "brain/planning/planner.py": "Planner",
        "brain/executor.py": "Executor",
    }

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        repository_root: Optional[str] = None,
    ):
        if repository_root:
            self.root = Path(repository_root).resolve()
        else:
            self.root = self._discover_root()

        self.issues: List[ValidationIssue] = []
        self.total_checks = 0
        self.passed_checks = 0

    # ========================================================
    # ROOT DISCOVERY
    # ========================================================

    @staticmethod
    def _discover_root() -> Path:
        """
        Discover ARIA-main from the current working directory.
        """

        current = Path.cwd().resolve()

        candidates = [
            current,
            current / "ARIA-main",
        ]

        for candidate in candidates:

            if (
                (candidate / "brain").is_dir()
                and (candidate / "main.py").exists()
            ):
                return candidate

        # Fallback:
        # allow execution directly from ARIA-main.
        if (current / "brain").is_dir():
            return current

        return current

    # ========================================================
    # CHECK HELPERS
    # ========================================================

    def _pass(
        self,
        component: str,
        message: str,
    ) -> None:

        self.total_checks += 1
        self.passed_checks += 1

        self.issues.append(
            ValidationIssue(
                level="PASS",
                component=component,
                message=message,
            )
        )

    def _fail(
        self,
        component: str,
        message: str,
    ) -> None:

        self.total_checks += 1

        self.issues.append(
            ValidationIssue(
                level="FAIL",
                component=component,
                message=message,
            )
        )

    def _warn(
        self,
        component: str,
        message: str,
    ) -> None:

        self.issues.append(
            ValidationIssue(
                level="WARN",
                component=component,
                message=message,
            )
        )

    # ========================================================
    # FILE CHECK
    # ========================================================

    def check_files(self) -> None:
        """
        Verify that every Phase 1 file exists.
        """

        for name, relative_path in self.EXPECTED_FILES.items():

            path = self.root / relative_path

            if path.is_file():

                self._pass(
                    name,
                    f"Found {relative_path}",
                )

            else:

                self._fail(
                    name,
                    f"Missing required file: {relative_path}",
                )

    # ========================================================
    # PYTHON SYNTAX CHECK
    # ========================================================

    def check_python_syntax(self) -> None:
        """
        Parse every Phase 1 Python file without importing it.

        This avoids triggering external dependencies.
        """

        for relative_path in self.EXPECTED_FILES.values():

            path = self.root / relative_path

            if not path.is_file():
                continue

            try:

                source = path.read_text(
                    encoding="utf-8"
                )

                ast.parse(
                    source,
                    filename=str(path),
                )

                self._pass(
                    f"syntax:{relative_path}",
                    "Python syntax is valid.",
                )

            except SyntaxError as exc:

                self._fail(
                    f"syntax:{relative_path}",
                    (
                        "Syntax error at "
                        f"line {exc.lineno}: "
                        f"{exc.msg}"
                    ),
                )

            except Exception as exc:

                self._fail(
                    f"syntax:{relative_path}",
                    f"Unable to parse file: {exc}",
                )

    # ========================================================
    # AST CLASS CHECK
    # ========================================================

    def _classes_from_ast(
        self,
        path: Path,
    ) -> List[str]:

        source = path.read_text(
            encoding="utf-8"
        )

        tree = ast.parse(
            source,
            filename=str(path),
        )

        return [
            node.name
            for node in ast.walk(tree)
            if isinstance(
                node,
                ast.ClassDef,
            )
        ]

    def _methods_from_ast(
        self,
        path: Path,
        class_name: str,
    ) -> List[str]:

        source = path.read_text(
            encoding="utf-8"
        )

        tree = ast.parse(
            source,
            filename=str(path),
        )

        for node in tree.body:

            if (
                isinstance(node, ast.ClassDef)
                and node.name == class_name
            ):

                return [
                    child.name
                    for child in node.body
                    if isinstance(
                        child,
                        (
                            ast.FunctionDef,
                            ast.AsyncFunctionDef,
                        ),
                    )
                ]

        return []

    def check_classes(self) -> None:
        """
        Verify required classes exist.
        """

        for relative_path, expected_classes in (
            self.EXPECTED_CLASSES.items()
        ):

            path = self.root / relative_path

            if not path.is_file():
                continue

            try:

                classes = self._classes_from_ast(
                    path
                )

                for class_name in expected_classes:

                    if class_name in classes:

                        self._pass(
                            (
                                f"class:"
                                f"{relative_path}:"
                                f"{class_name}"
                            ),
                            f"Found class {class_name}.",
                        )

                    else:

                        self._fail(
                            (
                                f"class:"
                                f"{relative_path}:"
                                f"{class_name}"
                            ),
                            (
                                f"Missing required "
                                f"class {class_name}."
                            ),
                        )

            except Exception as exc:

                self._fail(
                    f"class:{relative_path}",
                    f"Class inspection failed: {exc}",
                )

    # ========================================================
    # DATACLASS CHECK
    # ========================================================

    def check_dataclasses(self) -> None:
        """
        Verify important data models use @dataclass.
        """

        for relative_path, expected_classes in (
            self.EXPECTED_DATACLASSES.items()
        ):

            path = self.root / relative_path

            if not path.is_file():
                continue

            try:

                source = path.read_text(
                    encoding="utf-8"
                )

                tree = ast.parse(
                    source,
                    filename=str(path),
                )

                class_nodes = {
                    node.name: node
                    for node in ast.walk(tree)
                    if isinstance(
                        node,
                        ast.ClassDef,
                    )
                }

                for class_name in expected_classes:

                    node = class_nodes.get(
                        class_name
                    )

                    if node is None:
                        continue

                    is_dataclass = any(
                        (
                            isinstance(
                                decorator,
                                ast.Name,
                            )
                            and decorator.id
                            == "dataclass"
                        )
                        or (
                            isinstance(
                                decorator,
                                ast.Attribute,
                            )
                            and decorator.attr
                            == "dataclass"
                        )
                        for decorator
                        in node.decorator_list
                    )

                    if is_dataclass:

                        self._pass(
                            (
                                f"dataclass:"
                                f"{relative_path}:"
                                f"{class_name}"
                            ),
                            (
                                f"{class_name} "
                                "is a dataclass."
                            ),
                        )

                    else:

                        self._warn(
                            (
                                f"dataclass:"
                                f"{relative_path}:"
                                f"{class_name}"
                            ),
                            (
                                f"{class_name} "
                                "is not decorated "
                                "with @dataclass."
                            ),
                        )

            except Exception as exc:

                self._fail(
                    f"dataclass:{relative_path}",
                    f"Dataclass inspection failed: {exc}",
                )

    # ========================================================
    # METHOD CHECK
    # ========================================================

    def check_methods(self) -> None:
        """
        Verify important public APIs.
        """

        for relative_path, methods in (
            self.REQUIRED_METHODS.items()
        ):

            path = self.root / relative_path

            if not path.is_file():
                continue

            try:

                classes = self._classes_from_ast(
                    path
                )

                if not classes:
                    continue

                # Select the first non-dataclass-looking
                # application class.
                selected_class = None

                for class_name in classes:

                    if class_name not in {
                        "Exception",
                        "Enum",
                    }:
                        selected_class = class_name
                        break

                if selected_class is None:
                    continue

                available = self._methods_from_ast(
                    path,
                    selected_class,
                )

                for method in methods:

                    if method in available:

                        self._pass(
                            (
                                f"method:"
                                f"{relative_path}:"
                                f"{method}"
                            ),
                            (
                                f"{selected_class}."
                                f"{method}() exists."
                            ),
                        )

                    else:

                        self._warn(
                            (
                                f"method:"
                                f"{relative_path}:"
                                f"{method}"
                            ),
                            (
                                f"Expected API "
                                f"{selected_class}."
                                f"{method}() was not "
                                "found in the first "
                                "application class."
                            ),
                        )

            except Exception as exc:

                self._warn(
                    f"method:{relative_path}",
                    f"Method inspection failed: {exc}",
                )

    # ========================================================
    # CANONICAL ARCHITECTURE CHECK
    # ========================================================

    def check_canonical_architecture(self) -> None:
        """
        Ensure Phase 1 does not accidentally replace the
        canonical Task / Plan / Planner / Executor ownership.
        """

        for relative_path, class_name in (
            self.CANONICAL_CLASSES.items()
        ):

            path = self.root / relative_path

            if not path.is_file():
                continue

            try:

                classes = self._classes_from_ast(
                    path
                )

                if class_name in classes:

                    self._pass(
                        (
                            f"canonical:"
                            f"{relative_path}"
                        ),
                        (
                            f"Canonical {class_name} "
                            "remains present."
                        ),
                    )

                else:

                    self._fail(
                        (
                            f"canonical:"
                            f"{relative_path}"
                        ),
                        (
                            f"Canonical {class_name} "
                            "was not found."
                        ),
                    )

            except Exception as exc:

                self._fail(
                    f"canonical:{relative_path}",
                    (
                        "Canonical architecture "
                        f"check failed: {exc}"
                    ),
                )

    # ========================================================
    # DUPLICATE OWNERSHIP CHECK
    # ========================================================

    def check_duplicate_ownership(self) -> None:
        """
        Detect accidental duplicate definitions of the
        canonical Planner / Executor / Task / Plan classes
        inside Phase 1 files.

        Subclasses or wrapper classes with different names
        are allowed.
        """

        protected_names = {
            "Planner",
            "Executor",
            "Task",
            "ExecutionPlan",
        }

        phase1_paths = [
            path
            for path in self.EXPECTED_FILES.values()
            if path not in {
                "brain/task.py",
                "brain/plan.py",
                "brain/planning/planner.py",
                "brain/executor.py",
            }
        ]

        for relative_path in phase1_paths:

            path = self.root / relative_path

            if not path.is_file():
                continue

            try:

                classes = self._classes_from_ast(
                    path
                )

                duplicates = (
                    protected_names
                    .intersection(classes)
                )

                if duplicates:

                    self._fail(
                        (
                            f"ownership:"
                            f"{relative_path}"
                        ),
                        (
                            "Duplicate canonical "
                            "class definitions found: "
                            + ", ".join(
                                sorted(duplicates)
                            )
                        ),
                    )

                else:

                    self._pass(
                        (
                            f"ownership:"
                            f"{relative_path}"
                        ),
                        (
                            "No duplicate canonical "
                            "Planner/Executor/Task/"
                            "ExecutionPlan class."
                        ),
                    )

            except Exception as exc:

                self._warn(
                    f"ownership:{relative_path}",
                    f"Ownership check failed: {exc}",
                )

    # ========================================================
    # IMPORT CHECK
    # ========================================================

    def check_imports(self) -> None:
        """
        Attempt to import Phase 1 modules.

        External dependency failures are reported as warnings
        rather than automatically failing the architecture.
        """

        if str(self.root) not in sys.path:
            sys.path.insert(
                0,
                str(self.root),
            )

        modules = []

        for relative_path in self.EXPECTED_FILES.values():

            if not relative_path.endswith(".py"):
                continue

            module_name = (
                relative_path[:-3]
                .replace("/", ".")
            )

            if module_name.endswith(
                ".__init__"
            ):
                continue

            modules.append(module_name)

        for module_name in modules:

            try:

                importlib.import_module(
                    module_name
                )

                self._pass(
                    f"import:{module_name}",
                    "Module imported successfully.",
                )

            except ModuleNotFoundError as exc:

                self._warn(
                    f"import:{module_name}",
                    (
                        "Import requires an external "
                        f"dependency: {exc}"
                    ),
                )

            except ImportError as exc:

                self._warn(
                    f"import:{module_name}",
                    (
                        "Import dependency issue: "
                        f"{exc}"
                    ),
                )

            except Exception as exc:

                self._fail(
                    f"import:{module_name}",
                    (
                        "Module import raised "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )

    # ========================================================
    # PACKAGE CHECK
    # ========================================================

    def check_packages(self) -> None:
        """
        Check package directories used by Phase 1.

        Python namespace packages are valid, so missing
        __init__.py files are warnings rather than failures.
        """

        package_dirs = {
            "brain/development",
            "brain/knowledge",
            "brain/memory",
            "brain/planning",
            "brain/execution",
            "brain/verification",
            "brain/learning",
            "brain/goals",
            "brain/orchestration",
            "brain/safety",
            "brain/integration",
        }

        for relative_dir in sorted(package_dirs):

            directory = self.root / relative_dir

            if not directory.is_dir():

                self._fail(
                    f"package:{relative_dir}",
                    (
                        "Required Phase 1 "
                        "package directory is missing."
                    ),
                )

                continue

            init_file = directory / "__init__.py"

            if init_file.is_file():

                self._pass(
                    f"package:{relative_dir}",
                    "__init__.py present.",
                )

            else:

                self._warn(
                    f"package:{relative_dir}",
                    (
                        "__init__.py not present. "
                        "Namespace-package behavior "
                        "may still be valid."
                    ),
                )

    # ========================================================
    # INTEGRATION SOURCE CHECK
    # ========================================================

    def check_integration_references(self) -> None:
        """
        Verify that the final integration layer references
        the expected Phase 1 components by source text.

        This avoids executing the orchestration pipeline.
        """

        path = (
            self.root
            / "brain/integration/phase1_system.py"
        )

        if not path.is_file():
            return

        try:

            source = path.read_text(
                encoding="utf-8"
            )

            expected_references = [
                "GoalManager",
                "PhasePlanner",
                "AutonomousExecutionController",
                "SelfCorrectionEngine",
                "ExperienceEngine",
                "ExperienceAdapter",
                "ExperienceConsolidator",
                "PermissionGuard",
            ]

            for name in expected_references:

                if name in source:

                    self._pass(
                        f"integration:{name}",
                        (
                            f"Phase1System references "
                            f"{name}."
                        ),
                    )

                else:

                    self._warn(
                        f"integration:{name}",
                        (
                            f"Phase1System does not "
                            f"reference {name} directly."
                        ),
                    )

        except Exception as exc:

            self._fail(
                "integration:source",
                (
                    "Unable to inspect Phase1System: "
                    f"{exc}"
                ),
            )

    # ========================================================
    # FINAL REPORT
    # ========================================================

    def validate(
        self,
        include_imports: bool = True,
    ) -> ValidationReport:
        """
        Run all validation checks.
        """

        self.issues.clear()
        self.total_checks = 0
        self.passed_checks = 0

        self.check_files()
        self.check_python_syntax()
        self.check_classes()
        self.check_dataclasses()
        self.check_methods()
        self.check_canonical_architecture()
        self.check_duplicate_ownership()
        self.check_packages()
        self.check_integration_references()

        if include_imports:
            self.check_imports()

        failed = sum(
            1
            for issue in self.issues
            if issue.level == "FAIL"
        )

        warnings = sum(
            1
            for issue in self.issues
            if issue.level == "WARN"
        )

        passed = (
            failed == 0
            and self.total_checks > 0
        )

        return ValidationReport(
            passed=passed,
            total_checks=self.total_checks,
            passed_checks=self.passed_checks,
            failed_checks=failed,
            warnings=warnings,
            issues=list(self.issues),
        )

    # ========================================================
    # HUMAN-READABLE OUTPUT
    # ========================================================

    @staticmethod
    def _icon(level: str) -> str:

        return {
            "PASS": "✅",
            "FAIL": "❌",
            "WARN": "⚠️",
        }.get(level, "•")

    def print_report(
        self,
        report: ValidationReport,
    ) -> None:

        print()
        print("=" * 72)
        print("ARIA PHASE 1 — FINAL VALIDATION")
        print("=" * 72)

        print(
            f"Repository: {self.root}"
        )

        print()

        for issue in report.issues:

            print(
                f"{self._icon(issue.level)} "
                f"[{issue.level}] "
                f"{issue.component}: "
                f"{issue.message}"
            )

        print()
        print("-" * 72)

        print(
            f"Total checks : {report.total_checks}"
        )

        print(
            f"Passed       : {report.passed_checks}"
        )

        print(
            f"Failed       : {report.failed_checks}"
        )

        print(
            f"Warnings     : {report.warnings}"
        )

        print()

        if report.passed:

            print(
                "🎉 PHASE 1 VALIDATION PASSED"
            )

            print(
                "ARIA Phase 1 architecture is "
                "structurally ready."
            )

        else:

            print(
                "❌ PHASE 1 VALIDATION FAILED"
            )

            print(
                "Fix the FAIL items above before "
                "considering Phase 1 complete."
            )

        print("=" * 72)
        print()


# ============================================================
# CONVENIENCE FUNCTION
# ============================================================


def validate_phase1(
    repository_root: Optional[str] = None,
    include_imports: bool = True,
) -> Dict:
    """
    Programmatic Phase 1 validation entry point.
    """

    validator = Phase1Validator(
        repository_root=repository_root
    )

    report = validator.validate(
        include_imports=include_imports
    )

    return report.as_dict()


# ============================================================
# CLI
# ============================================================


def main() -> int:
    """
    Command-line entry point.
    """

    repository_root = None

    if len(sys.argv) > 1:
        repository_root = sys.argv[1]

    validator = Phase1Validator(
        repository_root=repository_root
    )

    report = validator.validate(
        include_imports=True
    )

    validator.print_report(
        report
    )

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )