"""
ARIA Phase 1 — Step 28
Final End-to-End Jarvis Validator

Purpose
-------
Validate that ARIA Phase 1 contains the complete autonomous developer
foundation required for future phases.

Expected architecture:

    USER
      ↓
    Intent / Requirement
      ↓
    Goal
      ↓
    Planning
      ↓
    Knowledge + Repository Context
      ↓
    Autonomous Development
      ↓
    Workspace / Sandbox
      ↓
    Build / Test / Validation
      ↓
    Failure Analysis
      ↓
    Repair
      ↓
    Retest
      ↓
    Experience / Learning
      ↓
    Git Checkpoint
      ↓
    EXPLICIT USER AUTHORIZATION
      ↓
    GitHub Push
      ↓
    EXPLICIT USER AUTHORIZATION
      ↓
    Deployment
      ↓
    Health Check
      ↓
    Rollback if unhealthy

This validator is READ-ONLY.

It:
    - checks required files;
    - checks required classes;
    - checks required methods;
    - checks Python syntax;
    - checks important architectural boundaries;
    - checks that GitHub/deployment authorization exists;
    - checks that the autonomous development chain exists.

It does NOT:
    - execute arbitrary generated code;
    - modify repository files;
    - create Git commits;
    - push to GitHub;
    - deploy;
    - rollback;
    - invoke the autonomous developer.

The validator is intentionally independent from the runtime bootstrap
so it can be safely used before deployment.
"""

from __future__ import annotations

import ast
import json
import py_compile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ==============================================================
# RESULT MODELS
# ==============================================================


@dataclass(frozen=True)
class ValidationFinding:
    """
    One validator finding.
    """

    check: str
    passed: bool
    severity: str
    message: str
    path: str | None = None
    details: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "passed": self.passed,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class Phase1ValidationReport:
    """
    Complete Phase 1 validation report.
    """

    success: bool
    status: str

    total_checks: int
    passed_checks: int
    failed_checks: int
    warning_checks: int

    findings: tuple[ValidationFinding, ...]

    required_capabilities: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()

    architecture_chain: tuple[str, ...] = ()

    repository_root: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "warning_checks": self.warning_checks,
            "findings": [
                item.to_dict()
                for item in self.findings
            ],
            "required_capabilities": list(
                self.required_capabilities
            ),
            "missing_capabilities": list(
                self.missing_capabilities
            ),
            "architecture_chain": list(
                self.architecture_chain
            ),
            "repository_root": self.repository_root,
        }

    def json(
        self,
        *,
        indent: int = 2,
    ) -> str:
        return json.dumps(
            self.to_dict(),
            indent=indent,
            default=str,
        )


# ==============================================================
# VALIDATOR
# ==============================================================


class Phase1JarvisValidator:
    """
    Read-only end-to-end Phase 1 validator.

    The validator uses static inspection rather than importing ARIA
    modules. This avoids triggering application startup, database
    connections, Telegram clients, schedulers, or deployment services.
    """

    VERSION = (
        "PHASE1-JARVIS-VALIDATOR-20261004"
    )

    REQUIRED_FILES = (
        # Core autonomous development
        "brain/development/development_agent.py",
        "brain/development/development_controller.py",
        "brain/development/requirement_intelligence.py",
        "brain/development/code_generation_bridge.py",
        "brain/development/coding_context_selector.py",
        "brain/development/repository_manager.py",
        "brain/development/workspace.py",
        "brain/development/sandbox.py",
        "brain/development/build_manager.py",
        "brain/development/test_runner.py",
        "brain/development/validator.py",

        # Failure / repair
        "brain/development/failure_analyzer.py",
        "brain/development/repair_engine.py",

        # Knowledge
        "brain/development/knowledge_architecture.py",
        "brain/development/knowledge_ingestion.py",
        "brain/memory/knowledge_retriever.py",

        # Planning / goals
        "brain/planning/phase_planner.py",
        "brain/planning/planner.py",
        "brain/goals/goal_manager.py",

        # Git / GitHub / deployment
        "brain/development/git_manager.py",
        "brain/development/github_manager.py",
        "brain/development/deployment_manager.py",
        "brain/development/deployment_policy.py",
        "brain/development/health_monitor.py",
        "brain/development/rollback_manager.py",

        # Phase 1 integration
        "brain/integration/phase1_system.py",
        "brain/integration/phase1_validator.py",

        # Final autonomous-development bridges
        "brain/development/autonomous_coding_loop.py",
        "brain/development/autonomous_validation_loop.py",
        "brain/development/autonomous_repair_loop.py",
        "brain/development/knowledge_coding_feedback.py",

        # Permission boundaries
        "brain/integration/permissioned_git_workflow.py",
        "brain/integration/permissioned_deployment_workflow.py",

        # Final validator
        "brain/integration/phase1_jarvis_validator.py",

        # Phase 1 runtime integration and engineering extensions
        "brain/integration/phase1_runtime.py",
        "brain/development/phase_task_execution.py",
        "brain/development/acceptance_staging_smoke.py",
        "brain/development/research_service.py",
        "brain/development/local_code_model.py",
        "brain/development/github_sync.py",
        "brain/development/git_branch_lifecycle.py",
        "brain/development/github_pull_request.py",
        "brain/development/github_project_creator.py",
        "brain/development/telegram_approval_interface.py",
        "brain/development/code_generation_router.py",
        "brain/learning/experience_engine.py",
        "brain/memory/experience_consolidator.py",
    )

    REQUIRED_CLASSES = {
        "brain/development/development_controller.py": (
            "DevelopmentController",
            "DevelopmentJob",
        ),
        "brain/development/development_agent.py": (
            "DevelopmentAgent",
            "DevelopmentReport",
        ),
        "brain/development/failure_analyzer.py": (
            "FailureAnalyzer",
        ),
        "brain/development/repair_engine.py": (
            "RepairEngine",
        ),
        "brain/memory/knowledge_retriever.py": (
            "KnowledgeRetriever",
        ),
        "brain/planning/phase_planner.py": (
            "PhasePlanner",
        ),
        "brain/goals/goal_manager.py": (
            "GoalManager",
        ),
        "brain/development/autonomous_coding_loop.py": (
            "AutonomousCodingLoop",
            "AutonomousCodingResult",
        ),
        "brain/development/autonomous_validation_loop.py": (
            "AutonomousValidationLoop",
            "AutonomousValidationResult",
        ),
        "brain/development/autonomous_repair_loop.py": (
            "AutonomousRepairLoop",
            "AutonomousRepairResult",
        ),
        "brain/development/knowledge_coding_feedback.py": (
            "KnowledgeCodingFeedback",
            "CodingKnowledgeContext",
        ),
        "brain/integration/permissioned_git_workflow.py": (
            "PermissionedGitWorkflow",
            "GitPushAuthorization",
        ),
        "brain/integration/permissioned_deployment_workflow.py": (
            "PermissionedDeploymentWorkflow",
            "DeploymentAuthorization",
        ),
        "brain/integration/phase1_jarvis_validator.py": (
            "Phase1JarvisValidator",
            "Phase1ValidationReport",
        ),
    }

    REQUIRED_METHODS = {
        "brain/development/development_controller.py": (
            "execute",
        ),
        "brain/development/development_agent.py": (
            "develop",
        ),
        "brain/development/autonomous_coding_loop.py": (
            "run",
        ),
        "brain/development/autonomous_validation_loop.py": (
            "validate",
        ),
        "brain/development/autonomous_repair_loop.py": (
            "run",
        ),
        "brain/development/knowledge_coding_feedback.py": (
            "prepare",
            "enrich",
            "merge_into",
        ),
        "brain/integration/permissioned_git_workflow.py": (
            "create_checkpoint",
            "push_to_github",
            "checkpoint",
        ),
        "brain/integration/permissioned_deployment_workflow.py": (
            "deploy",
            "check_health",
            "rollback",
        ),
    }

    REQUIRED_CAPABILITIES = (
        "requirement_intelligence",
        "goal_management",
        "planning",
        "knowledge_retrieval",
        "repository_intelligence",
        "coding_context",
        "code_generation",
        "workspace_management",
        "sandbox_execution",
        "build_validation",
        "test_execution",
        "failure_analysis",
        "autonomous_repair",
        "retest",
        "experience_learning",
        "memory_consolidation",
        "local_git_checkpoint",
        "permissioned_github_push",
        "permissioned_deployment",
        "deployment_health",
        "rollback",
    )

    ARCHITECTURE_CHAIN = (
        "requirement",
        "goal",
        "planning",
        "knowledge",
        "repository_context",
        "code_generation",
        "workspace",
        "sandbox",
        "build",
        "tests",
        "validation",
        "failure_analysis",
        "repair",
        "retest",
        "experience",
        "git_checkpoint",
        "explicit_github_authorization",
        "github_push",
        "explicit_deployment_authorization",
        "deployment",
        "health_check",
        "rollback",
    )

    # ==========================================================
    # INIT
    # ==========================================================

    def __init__(
        self,
        repository_root: str | Path,
    ) -> None:

        self.root = Path(
            repository_root
        ).resolve()

        self.findings: list[
            ValidationFinding
        ] = []

    # ==========================================================
    # FINDING
    # ==========================================================

    def _add(
        self,
        *,
        check: str,
        passed: bool,
        severity: str,
        message: str,
        path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:

        self.findings.append(
            ValidationFinding(
                check=check,
                passed=passed,
                severity=severity,
                message=message,
                path=path,
                details=dict(
                    details or {}
                ),
            )
        )

    # ==========================================================
    # FILE CHECK
    # ==========================================================

    def _check_files(self) -> set[str]:

        existing: set[str] = set()

        for relative in self.REQUIRED_FILES:

            path = self.root / relative

            if path.is_file():

                existing.add(relative)

                self._add(
                    check="required_file",
                    passed=True,
                    severity="info",
                    message=(
                        "Required Phase 1 file exists."
                    ),
                    path=relative,
                )

            else:

                self._add(
                    check="required_file",
                    passed=False,
                    severity="error",
                    message=(
                        "Required Phase 1 file is missing."
                    ),
                    path=relative,
                )

        return existing

    # ==========================================================
    # AST
    # ==========================================================

    @staticmethod
    def _parse(
        path: Path,
    ) -> ast.AST | None:

        try:

            return ast.parse(
                path.read_text(
                    encoding="utf-8"
                ),
                filename=str(path),
            )

        except Exception:
            return None

    @staticmethod
    def _class_names(
        tree: ast.AST,
    ) -> set[str]:

        return {
            node.name
            for node in ast.walk(tree)
            if isinstance(
                node,
                ast.ClassDef,
            )
        }

    @staticmethod
    def _method_names(
        tree: ast.AST,
    ) -> set[str]:

        return {
            node.name
            for node in ast.walk(tree)
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
        }

    # ==========================================================
    # CLASS CHECK
    # ==========================================================

    def _check_classes(
        self,
        existing: set[str],
    ) -> None:

        for relative, classes in (
            self.REQUIRED_CLASSES.items()
        ):

            if relative not in existing:
                continue

            path = self.root / relative
            tree = self._parse(path)

            if tree is None:

                self._add(
                    check="class_structure",
                    passed=False,
                    severity="error",
                    message=(
                        "Python AST could not be parsed."
                    ),
                    path=relative,
                )

                continue

            available = self._class_names(
                tree
            )

            for class_name in classes:

                passed = (
                    class_name in available
                )

                self._add(
                    check="required_class",
                    passed=passed,
                    severity=(
                        "info"
                        if passed
                        else "error"
                    ),
                    message=(
                        f"Required class "
                        f"{class_name} "
                        f"{'exists' if passed else 'is missing'}."
                    ),
                    path=relative,
                    details={
                        "class": class_name
                    },
                )

    # ==========================================================
    # METHOD CHECK
    # ==========================================================

    def _check_methods(
        self,
        existing: set[str],
    ) -> None:

        for relative, methods in (
            self.REQUIRED_METHODS.items()
        ):

            if relative not in existing:
                continue

            path = self.root / relative
            tree = self._parse(path)

            if tree is None:
                continue

            available = self._method_names(
                tree
            )

            for method_name in methods:

                passed = (
                    method_name in available
                )

                self._add(
                    check="required_method",
                    passed=passed,
                    severity=(
                        "info"
                        if passed
                        else "error"
                    ),
                    message=(
                        f"Required method "
                        f"{method_name} "
                        f"{'exists' if passed else 'is missing'}."
                    ),
                    path=relative,
                    details={
                        "method": method_name
                    },
                )

    # ==========================================================
    # SYNTAX
    # ==========================================================

    def _check_syntax(
        self,
        existing: set[str],
    ) -> None:

        python_files = sorted(
            self.root.rglob("*.py")
        )

        for path in python_files:

            try:

                py_compile.compile(
                    str(path),
                    doraise=True,
                )

                self._add(
                    check="python_syntax",
                    passed=True,
                    severity="info",
                    message=(
                        "Python syntax compiled successfully."
                    ),
                    path=str(
                        path.relative_to(
                            self.root
                        )
                    ),
                )

            except Exception as exc:

                self._add(
                    check="python_syntax",
                    passed=False,
                    severity="error",
                    message=(
                        "Python syntax compilation failed."
                    ),
                    path=str(
                        path.relative_to(
                            self.root
                        )
                    ),
                    details={
                        "error": str(exc)
                    },
                )

    # ==========================================================
    # SAFETY CHECK
    # ==========================================================

    def _check_permission_boundaries(
        self,
        existing: set[str],
    ) -> None:

        git_path = (
            "brain/integration/"
            "permissioned_git_workflow.py"
        )

        deployment_path = (
            "brain/integration/"
            "permissioned_deployment_workflow.py"
        )

        # ------------------------------------------------------
        # GitHub
        # ------------------------------------------------------

        if git_path in existing:

            path = self.root / git_path
            text = path.read_text(
                encoding="utf-8"
            )

            required_tokens = (
                "GitPushAuthorization",
                "push_to_github",
                "authorization",
                "is_valid",
                "push_not_authorized",
            )

            missing = [
                token
                for token in required_tokens
                if token not in text
            ]

            self._add(
                check="github_push_boundary",
                passed=not missing,
                severity=(
                    "info"
                    if not missing
                    else "error"
                ),
                message=(
                    "GitHub push authorization boundary "
                    "is present."
                    if not missing
                    else (
                        "GitHub push authorization boundary "
                        "appears incomplete."
                    )
                ),
                path=git_path,
                details={
                    "missing_tokens": missing
                },
            )

        # ------------------------------------------------------
        # Deployment
        # ------------------------------------------------------

        if deployment_path in existing:

            path = self.root / deployment_path
            text = path.read_text(
                encoding="utf-8"
            )

            required_tokens = (
                "DeploymentAuthorization",
                "deploy",
                "authorization",
                "is_valid",
                "deployment_not_authorized",
            )

            missing = [
                token
                for token in required_tokens
                if token not in text
            ]

            self._add(
                check="deployment_boundary",
                passed=not missing,
                severity=(
                    "info"
                    if not missing
                    else "error"
                ),
                message=(
                    "Deployment authorization boundary "
                    "is present."
                    if not missing
                    else (
                        "Deployment authorization boundary "
                        "appears incomplete."
                    )
                ),
                path=deployment_path,
                details={
                    "missing_tokens": missing
                },
            )

    # ==========================================================
    # ARCHITECTURE CHECK
    # ==========================================================

    def _check_architecture(
        self,
        existing: set[str],
    ) -> tuple[str, ...]:

        capability_files = {
            "requirement_intelligence":
                "brain/development/"
                "requirement_intelligence.py",

            "goal_management":
                "brain/goals/"
                "goal_manager.py",

            "planning":
                "brain/planning/"
                "phase_planner.py",

            "knowledge_retrieval":
                "brain/memory/"
                "knowledge_retriever.py",

            "repository_intelligence":
                "brain/development/"
                "repository_manager.py",

            "coding_context":
                "brain/development/"
                "coding_context_selector.py",

            "code_generation":
                "brain/development/"
                "code_generation_router.py",

            "workspace_management":
                "brain/development/"
                "workspace.py",

            "sandbox_execution":
                "brain/development/"
                "sandbox.py",

            "build_validation":
                "brain/development/"
                "build_manager.py",

            "test_execution":
                "brain/development/"
                "test_runner.py",

            "validation":
                "brain/development/"
                "validator.py",

            "failure_analysis":
                "brain/development/"
                "failure_analyzer.py",

            "autonomous_repair":
                "brain/development/"
                "autonomous_repair_loop.py",

            "retest":
                "brain/development/"
                "autonomous_validation_loop.py",

            "experience_learning":
                "brain/learning/"
                "experience_engine.py",

            "memory_consolidation":
                "brain/memory/"
                "experience_consolidator.py",

            "local_git_checkpoint":
                "brain/integration/"
                "permissioned_git_workflow.py",

            "permissioned_github_push":
                "brain/integration/"
                "permissioned_git_workflow.py",

            "permissioned_deployment":
                "brain/integration/"
                "permissioned_deployment_workflow.py",

            "deployment_health":
                "brain/development/"
                "health_monitor.py",

            "rollback":
                "brain/development/"
                "rollback_manager.py",
        }

        available: list[str] = []
        missing: list[str] = []

        for capability, relative in (
            capability_files.items()
        ):

            if relative in existing:

                available.append(
                    capability
                )

            else:

                missing.append(
                    capability
                )

            self._add(
                check="capability",
                passed=(
                    relative in existing
                ),
                severity=(
                    "info"
                    if relative in existing
                    else "error"
                ),
                message=(
                    f"Capability '{capability}' "
                    f"is {'available' if relative in existing else 'missing'}."
                ),
                path=relative,
                details={
                    "capability": capability
                },
            )

        return (
            tuple(missing),
            tuple(available),
        )

    # ==========================================================
    # DEVELOPMENT CHAIN
    # ==========================================================

    def _check_development_chain(
        self,
        existing: set[str],
    ) -> None:

        chain_requirements = {
            "requirement":
                (
                    "brain/development/"
                    "requirement_intelligence.py"
                ),

            "goal":
                "brain/goals/goal_manager.py",

            "planning":
                "brain/planning/phase_planner.py",

            "knowledge":
                "brain/memory/knowledge_retriever.py",

            "repository_context":
                "brain/development/repository_manager.py",

            "code_generation":
                "brain/development/code_generation_bridge.py",

            "workspace":
                "brain/development/workspace.py",

            "sandbox":
                "brain/development/sandbox.py",

            "build":
                "brain/development/build_manager.py",

            "tests":
                "brain/development/test_runner.py",

            "validation":
                "brain/development/validator.py",

            "failure_analysis":
                "brain/development/failure_analyzer.py",

            "repair":
                "brain/development/repair_engine.py",

            "retest":
                "brain/development/autonomous_validation_loop.py",

            "experience":
                "brain/memory/experience_consolidator.py",

            "git_checkpoint":
                "brain/integration/"
                "permissioned_git_workflow.py",

            "github_push":
                "brain/development/github_manager.py",

            "deployment":
                "brain/development/deployment_manager.py",

            "health_check":
                "brain/development/health_monitor.py",

            "rollback":
                "brain/development/rollback_manager.py",

            "phase1_runtime":
                "brain/integration/phase1_runtime.py",

            "task_graph":
                "brain/development/phase_task_execution.py",

            "acceptance_gate":
                "brain/development/acceptance_staging_smoke.py",

            "real_time_research":
                "brain/development/research_service.py",

            "local_code_model":
                "brain/development/local_code_model.py",

            "github_sync":
                "brain/development/github_sync.py",

            "branch_lifecycle":
                "brain/development/git_branch_lifecycle.py",

            "pull_request_workflow":
                "brain/development/github_pull_request.py",

            "project_creator":
                "brain/development/github_project_creator.py",

            "telegram_approval":
                "brain/development/telegram_approval_interface.py",
        }

        for stage, relative in (
            chain_requirements.items()
        ):

            self._add(
                check="architecture_stage",
                passed=(
                    relative in existing
                ),
                severity=(
                    "info"
                    if relative in existing
                    else "error"
                ),
                message=(
                    f"Architecture stage '{stage}' "
                    f"is {'present' if relative in existing else 'missing'}."
                ),
                path=relative,
                details={
                    "stage": stage
                },
            )

    # ==========================================================
    # NO DUPLICATE DEVELOPMENT ENGINE
    # ==========================================================

    def _check_authoritative_ownership(
        self,
        existing: set[str],
    ) -> None:

        ownership = {
            "development_execution":
                "brain/development/"
                "development_controller.py",

            "development_agent":
                "brain/development/"
                "development_agent.py",

            "failure_analysis":
                "brain/development/"
                "failure_analyzer.py",

            "repair":
                "brain/development/"
                "repair_engine.py",

            "git":
                "brain/development/"
                "git_manager.py",

            "github":
                "brain/development/"
                "github_manager.py",

            "deployment":
                "brain/development/"
                "deployment_manager.py",

            "rollback":
                "brain/development/"
                "rollback_manager.py",
        }

        for owner, relative in (
            ownership.items()
        ):

            self._add(
                check="authoritative_ownership",
                passed=(
                    relative in existing
                ),
                severity=(
                    "info"
                    if relative in existing
                    else "warning"
                ),
                message=(
                    f"Authoritative owner for "
                    f"'{owner}' is "
                    f"{'present' if relative in existing else 'not detected'}."
                ),
                path=relative,
                details={
                    "owner": owner
                },
            )

    # ==========================================================
    # PUBLIC VALIDATE
    # ==========================================================

    def validate(self) -> Phase1ValidationReport:
        """
        Execute complete static Phase 1 validation.
        """

        self.findings.clear()

        if not self.root.exists():

            finding = ValidationFinding(
                check="repository_root",
                passed=False,
                severity="error",
                message=(
                    "Repository root does not exist."
                ),
                path=str(
                    self.root
                ),
            )

            return Phase1ValidationReport(
                success=False,
                status="repository_missing",
                total_checks=1,
                passed_checks=0,
                failed_checks=1,
                warning_checks=0,
                findings=(finding,),
                required_capabilities=(
                    self.REQUIRED_CAPABILITIES
                ),
                missing_capabilities=(
                    self.REQUIRED_CAPABILITIES
                ),
                architecture_chain=(
                    self.ARCHITECTURE_CHAIN
                ),
                repository_root=str(
                    self.root
                ),
            )

        self._add(
            check="repository_root",
            passed=True,
            severity="info",
            message=(
                "Repository root exists."
            ),
            path=str(
                self.root
            ),
        )

        existing = self._check_files()

        self._check_classes(
            existing
        )

        self._check_methods(
            existing
        )

        self._check_syntax(
            existing
        )

        self._check_permission_boundaries(
            existing
        )

        missing, available = (
            self._check_architecture(
                existing
            )
        )

        self._check_development_chain(
            existing
        )

        self._check_authoritative_ownership(
            existing
        )

        errors = [
            finding
            for finding in self.findings
            if (
                not finding.passed
                and finding.severity
                == "error"
            )
        ]

        warnings = [
            finding
            for finding in self.findings
            if (
                not finding.passed
                and finding.severity
                == "warning"
            )
        ]

        passed = [
            finding
            for finding in self.findings
            if finding.passed
        ]

        success = not errors

        if success:
            status = (
                "phase1_jarvis_ready"
                if not warnings
                else "phase1_jarvis_ready_with_warnings"
            )

        else:
            status = (
                "phase1_validation_failed"
            )

        return Phase1ValidationReport(
            success=success,
            status=status,
            total_checks=len(
                self.findings
            ),
            passed_checks=len(
                passed
            ),
            failed_checks=len(
                errors
            ),
            warning_checks=len(
                warnings
            ),
            findings=tuple(
                self.findings
            ),
            required_capabilities=(
                self.REQUIRED_CAPABILITIES
            ),
            missing_capabilities=missing,
            architecture_chain=(
                self.ARCHITECTURE_CHAIN
            ),
            repository_root=str(
                self.root
            ),
        )


# ==============================================================
# CONVENIENCE FUNCTION
# ==============================================================


def validate_phase1(
    repository_root: str | Path,
) -> Phase1ValidationReport:
    """
    Convenience API for external bootstrap/tests/CLI callers.
    """

    return Phase1JarvisValidator(
        repository_root
    ).validate()


# ==============================================================
# CLI
# ==============================================================


def main() -> int:
    """
    Run:

        python -m brain.integration.phase1_jarvis_validator

    from the ARIA-main repository root.
    """

    repository_root = Path(
        __file__
    ).resolve().parents[2]

    report = validate_phase1(
        repository_root
    )

    print(
        "=" * 72
    )

    print(
        "ARIA PHASE 1 — FINAL JARVIS VALIDATION"
    )

    print(
        "=" * 72
    )

    print(
        f"Repository : {report.repository_root}"
    )

    print(
        f"Status     : {report.status}"
    )

    print(
        f"Success    : {report.success}"
    )

    print(
        f"Checks     : {report.total_checks}"
    )

    print(
        f"Passed     : {report.passed_checks}"
    )

    print(
        f"Failed     : {report.failed_checks}"
    )

    print(
        f"Warnings   : {report.warning_checks}"
    )

    print(
        "-" * 72
    )

    if report.missing_capabilities:

        print(
            "Missing capabilities:"
        )

        for capability in (
            report.missing_capabilities
        ):
            print(
                f"  - {capability}"
            )

        print(
            "-" * 72
        )

    for finding in report.findings:

        if (
            finding.severity == "error"
            or (
                not finding.passed
                and finding.severity
                == "warning"
            )
        ):

            prefix = (
                "FAIL"
                if finding.severity
                == "error"
                else "WARN"
            )

            print(
                f"[{prefix}] "
                f"{finding.check}: "
                f"{finding.message}"
            )

            if finding.path:
                print(
                    f"       {finding.path}"
                )

    print(
        "-" * 72
    )

    if report.success:

        print(
            "ARIA Phase 1 autonomous-development "
            "foundation is structurally ready."
        )

        print(
            "GitHub push and deployment remain "
            "explicitly permissioned."
        )

        return 0

    print(
        "ARIA Phase 1 validation requires fixes "
        "before it should be considered ready."
    )

    return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )


__all__ = [
    "ValidationFinding",
    "Phase1ValidationReport",
    "Phase1JarvisValidator",
    "validate_phase1",
]