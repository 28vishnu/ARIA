"""
ARIA Phase 1 — Canonical Git / GitHub / Deployment Delivery Gateway.

This is the single delivery boundary exposed to the Phase 1 runtime.
It reuses the existing authoritative Git and deployment engines and never
infers permission from engineering success.

Safety invariants:
- GitHub push requires an explicit single-operation authorization.
- PR merge requires an explicit single-operation authorization.
- Deployment requires explicit authorization.
- Rollback requires explicit authorization.
- No operation is executed merely because a plan exists.
- No direct shell/GitHub/deployment implementation is introduced here.
"""

from __future__ import annotations

from typing import Any, Mapping

from brain.development.authoritative_git import AuthoritativeGitLifecycle
from brain.development.authoritative_deployment import AuthoritativeDeploymentEngine
from brain.development.contracts.engineering_git import (
    GitAuthorization,
    GitLifecyclePlan,
    GitLifecycleRequest,
    GitLifecycleResult,
)
from brain.development.contracts.engineering_deployment import (
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentRequest,
    DeploymentResult,
)


class Phase1DeliveryGateway:
    """Canonical, explicit-authorization delivery boundary."""

    VERSION = "phase1-delivery-gateway-20261005"

    def __init__(
        self,
        *,
        git_service: Any = None,
        github_service: Any = None,
        deployment_service: Any = None,
        health_monitor: Any = None,
        rollback_manager: Any = None,
    ) -> None:
        self.git_service = git_service
        self.github_service = github_service
        self.deployment_service = deployment_service
        self.health_monitor = health_monitor
        self.rollback_manager = rollback_manager

        self.git = AuthoritativeGitLifecycle(
            git_service=git_service,
            github_service=github_service,
        )
        self.deployment = AuthoritativeDeploymentEngine(
            deployment_service=deployment_service,
            health_monitor=health_monitor,
            rollback_manager=rollback_manager,
        )

    def plan_git(self, request: GitLifecycleRequest) -> GitLifecyclePlan:
        """Create a Git lifecycle plan without executing anything."""
        return self.git.plan(request)

    async def execute_git(
        self,
        plan: GitLifecyclePlan,
        *,
        authorizations: tuple[GitAuthorization, ...] = (),
    ) -> GitLifecycleResult:
        """Execute only the Git operations permitted by explicit authorization."""
        return await self.git.execute(
            plan,
            authorizations=authorizations,
        )

    def plan_deployment(
        self,
        request: DeploymentRequest,
    ) -> DeploymentPlan:
        """Create a deployment/health/rollback plan without deploying."""
        return self.deployment.plan(request)

    async def execute_deployment(
        self,
        plan: DeploymentPlan,
        *,
        authorization: DeploymentAuthorization | None = None,
        rollback_authorization: DeploymentAuthorization | None = None,
    ) -> DeploymentResult:
        """Deploy only when explicit deployment authorization is supplied."""
        return await self.deployment.execute(
            plan,
            authorization=authorization,
            rollback_authorization=rollback_authorization,
        )

    def health(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "version": self.VERSION,
            "git_engine": self.git is not None,
            "deployment_engine": self.deployment is not None,
            "git_service_available": self.git_service is not None,
            "github_service_available": self.github_service is not None,
            "deployment_service_available": self.deployment_service is not None,
            "github_push_requires_authorization": True,
            "merge_requires_authorization": True,
            "deployment_requires_authorization": True,
            "rollback_requires_authorization": True,
            "production_direct_write": False,
            "automatic_delivery": False,
        }

    def status(self) -> dict[str, Any]:
        return self.health()


__all__ = ["Phase1DeliveryGateway"]
