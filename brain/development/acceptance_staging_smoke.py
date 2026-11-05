from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Sequence

from .build_manager import BuildManager
from .deployment_manager import DeploymentManager
from .health_monitor import HealthMonitor
from .test_runner import DevelopmentTestRunner
from .validator import DevelopmentValidator
from .workspace import DevelopmentWorkspace

logger = logging.getLogger("aria.acceptance")


@dataclass(frozen=True)
class AcceptanceCheck:
    name: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptanceResult:
    accepted: bool
    workspace_id: str
    checks: tuple[AcceptanceCheck, ...] = ()
    build: dict[str, Any] | None = None
    tests: dict[str, Any] | None = None
    deployment: dict[str, Any] | None = None
    smoke: dict[str, Any] | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "workspace_id": self.workspace_id,
            "checks": [c.to_dict() for c in self.checks],
            "build": self.build,
            "tests": self.tests,
            "deployment": self.deployment,
            "smoke": self.smoke,
            "message": self.message,
        }


class AcceptanceStagingSmoke:
    """
    Final verification gate for autonomous development.

    Flow:
        static validation -> compile/build -> tests -> optional staging
        -> HTTP smoke checks -> acceptance result

    This component never enables production deployment. Staging deployment
    requires an explicit command supplied by the caller.
    """

    def __init__(
        self,
        workspace_manager: DevelopmentWorkspace,
        *,
        build_manager_factory: Any = BuildManager,
        validator_factory: Any = DevelopmentValidator,
        test_runner_factory: Any = DevelopmentTestRunner,
        sandbox_factory: Any = None,
        deployment_manager: DeploymentManager | None = None,
        health_monitor: HealthMonitor | None = None,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.build_manager_factory = build_manager_factory
        self.validator_factory = validator_factory
        self.test_runner_factory = test_runner_factory
        self.sandbox_factory = sandbox_factory
        self.deployment_manager = deployment_manager
        self.health_monitor = health_monitor or HealthMonitor()

    def _sandbox(self, root: str):
        if self.sandbox_factory is None:
            from .sandbox import DevelopmentSandbox
            factory = DevelopmentSandbox
        else:
            factory = self.sandbox_factory
        return factory(root)

    def _services(self, root: str):
        sandbox = self._sandbox(root)
        validator = self.validator_factory(sandbox.guard)
        runner = self.test_runner_factory(sandbox)
        builder = self.build_manager_factory(sandbox)
        return sandbox, validator, runner, builder

    async def run(
        self,
        *,
        workspace_id: str,
        test_paths: Sequence[str] = (),
        build_command: Sequence[str] | None = None,
        build_cwd: str = ".",
        smoke_urls: Sequence[str] = (),
        staging_command: Sequence[str] | None = None,
        staging_version: str | None = None,
        stage: bool = False,
        smoke_attempts: int = 5,
        smoke_delay_seconds: float = 5.0,
    ) -> AcceptanceResult:
        checks: list[AcceptanceCheck] = []
        workspace = self.workspace_manager.get(workspace_id)
        if workspace is None:
            return AcceptanceResult(
                accepted=False,
                workspace_id=workspace_id,
                checks=(AcceptanceCheck("workspace", False, "Workspace not found."),),
                message="Acceptance stopped because the workspace does not exist.",
            )

        root = str(workspace.root)
        _, validator, runner, builder = self._services(root)

        validation = validator.validate_repository(include_tests=True)
        checks.append(AcceptanceCheck(
            "static_validation",
            validation.valid,
            "Static validation passed." if validation.valid else "Static validation failed.",
            validation.to_dict(),
        ))
        if not validation.valid:
            return AcceptanceResult(False, workspace_id, tuple(checks), message="Acceptance stopped at static validation.")

        if build_command:
            build = await builder.build(tuple(str(x) for x in build_command), cwd=build_cwd)
        else:
            build = await builder.python_compile(path=".")
        checks.append(AcceptanceCheck("build", build.success, "Build passed." if build.success else "Build failed.", build.to_dict()))
        if not build.success:
            return AcceptanceResult(False, workspace_id, tuple(checks), build=build.to_dict(), message="Acceptance stopped at build.")

        tests_data = None
        if test_paths:
            tests = await runner.run_targeted_tests(tuple(str(x) for x in test_paths))
            tests_data = tests.to_dict()
        else:
            tests = await runner.run_regression_suite()
            tests_data = tests.to_dict()
        checks.append(AcceptanceCheck("tests", tests.passed, "Tests passed." if tests.passed else "Tests failed.", tests_data))
        if not tests.passed:
            return AcceptanceResult(False, workspace_id, tuple(checks), build=build.to_dict(), tests=tests_data, message="Acceptance stopped at tests.")

        deployment_data = None
        smoke_data = None
        if stage:
            if self.deployment_manager is None:
                checks.append(AcceptanceCheck("staging", False, "No deployment manager is configured."))
                return AcceptanceResult(False, workspace_id, tuple(checks), build=build.to_dict(), tests=tests_data, message="Staging requested but unavailable.")
            if not staging_command:
                checks.append(AcceptanceCheck("staging", False, "A staging deployment command is required."))
                return AcceptanceResult(False, workspace_id, tuple(checks), build=build.to_dict(), tests=tests_data, message="Staging requested without a command.")
            deployment = await self.deployment_manager.deploy(
                build,
                version=staging_version or f"aria-{uuid.uuid4().hex[:12]}",
                environment="staging",
                command=tuple(str(x) for x in staging_command),
                explicit_authorization=True,
            )
            deployment_data = deployment.to_dict()
            checks.append(AcceptanceCheck("staging", deployment.success, deployment.message or "Staging deployment completed.", deployment_data))
            if not deployment.success:
                return AcceptanceResult(False, workspace_id, tuple(checks), build=build.to_dict(), tests=tests_data, deployment=deployment_data, message="Acceptance stopped at staging deployment.")

        if smoke_urls:
            smoke = await self.health_monitor.wait_until_healthy(
                list(smoke_urls),
                attempts=max(1, int(smoke_attempts)),
                delay_seconds=max(0.0, float(smoke_delay_seconds)),
            )
            smoke_data = smoke.to_dict()
            checks.append(AcceptanceCheck("smoke", smoke.healthy, "Smoke checks passed." if smoke.healthy else "Smoke checks failed.", smoke_data))
            if not smoke.healthy:
                return AcceptanceResult(False, workspace_id, tuple(checks), build=build.to_dict(), tests=tests_data, deployment=deployment_data, smoke=smoke_data, message="Acceptance stopped at smoke checks.")

        checks.append(AcceptanceCheck("acceptance", True, "All requested acceptance gates passed."))
        return AcceptanceResult(True, workspace_id, tuple(checks), build=build.to_dict(), tests=tests_data, deployment=deployment_data, smoke=smoke_data, message="Engineering result accepted by all requested gates.")

    def health(self) -> dict[str, Any]:
        return {
            "healthy": self.workspace_manager is not None,
            "staging_available": self.deployment_manager is not None,
            "smoke_available": self.health_monitor is not None,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "name": "acceptance_staging_smoke",
            "capabilities": [
                "static_validation",
                "build",
                "tests",
                "staging_deployment",
                "http_smoke_checks",
                "acceptance_gate",
            ],
            "safety": [
                "production_deployment_not_performed",
                "staging_requires_explicit_command",
                "failure_stops_acceptance",
            ],
        }


__all__ = ["AcceptanceCheck", "AcceptanceResult", "AcceptanceStagingSmoke"]
