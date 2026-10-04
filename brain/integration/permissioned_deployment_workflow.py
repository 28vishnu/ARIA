"""
ARIA Phase 1 — Step 27
Permissioned Deployment + Health + Rollback Workflow

Architecture:

    Validated Build
          ↓
    Deployment Workflow
          ↓
    ┌───────────────────────┐
    │ EXPLICIT AUTHORIZATION│
    └───────────┬───────────┘
                ↓
            Deploy
                ↓
          Health Check
             /     \
          healthy  unhealthy
             |         |
          success    rollback
                       |
                   health check

Safety:
    - deployment is NEVER automatic
    - explicit deployment authorization is required
    - health checks are bounded
    - rollback is delegated to the existing deployment service
    - no GitHub push is performed here
    - no shell commands are executed directly
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DeploymentAuthorization:
    """
    Single-operation deployment authorization.

    Authorization is intentionally not persistent.
    A new authorization should be supplied for each deployment.
    """

    approved: bool
    reason: str = ""
    approved_by: str = "user"
    operation: str = "deployment"
    created_at: str = field(
        default_factory=_utc_now
    )

    def is_valid(self) -> bool:
        return (
            self.approved
            and self.operation == "deployment"
            and bool(self.approved_by)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "approved_by": self.approved_by,
            "operation": self.operation,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class DeploymentResult:
    success: bool
    status: str

    deployment_attempted: bool = False
    deployment_authorized: bool = False
    health_checked: bool = False
    healthy: bool = False

    rollback_attempted: bool = False
    rollback_succeeded: bool = False

    deployment_id: str | None = None
    version: str | None = None

    message: str = ""
    errors: tuple[str, ...] = ()

    started_at: str = ""
    completed_at: str = ""

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "deployment_attempted": (
                self.deployment_attempted
            ),
            "deployment_authorized": (
                self.deployment_authorized
            ),
            "health_checked": self.health_checked,
            "healthy": self.healthy,
            "rollback_attempted": (
                self.rollback_attempted
            ),
            "rollback_succeeded": (
                self.rollback_succeeded
            ),
            "deployment_id": self.deployment_id,
            "version": self.version,
            "message": self.message,
            "errors": list(self.errors),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": dict(self.metadata),
        }


class PermissionedDeploymentWorkflow:
    """
    Controlled deployment facade.

    Existing deployment infrastructure remains authoritative.

    This class discovers compatible deployment, health, and rollback
    methods instead of implementing a second deployment system.
    """

    DEPLOY_METHODS = (
        "deploy",
        "deploy_application",
        "start_deployment",
        "create_deployment",
    )

    HEALTH_METHODS = (
        "health",
        "health_check",
        "check_health",
        "deployment_health",
        "get_health",
    )

    ROLLBACK_METHODS = (
        "rollback",
        "rollback_deployment",
        "restore_previous",
        "rollback_to_previous",
    )

    STATUS_METHODS = (
        "status",
        "deployment_status",
        "get_status",
    )

    def __init__(
        self,
        deployment_service=None,
        *,
        health_timeout_seconds: float = 60.0,
        health_interval_seconds: float = 5.0,
    ) -> None:

        self.deployment = deployment_service

        self.health_timeout_seconds = max(
            5.0,
            float(
                health_timeout_seconds
            ),
        )

        self.health_interval_seconds = max(
            1.0,
            float(
                health_interval_seconds
            ),
        )

        self._last_result: (
            DeploymentResult | None
        ) = None

    # ==========================================================
    # SERVICE HELPERS
    # ==========================================================

    @staticmethod
    def _find_method(
        service: Any,
        names: tuple[str, ...],
    ):
        if service is None:
            return None

        for name in names:
            method = getattr(
                service,
                name,
                None,
            )

            if callable(method):
                return method

        return None

    @staticmethod
    async def _call(
        method,
        **kwargs,
    ):
        result = method(**kwargs)

        if hasattr(
            result,
            "__await__",
        ):
            result = await result

        return result

    @staticmethod
    def _extract(
        result: Any,
        *names: str,
        default=None,
    ):
        if result is None:
            return default

        if isinstance(
            result,
            Mapping,
        ):
            for name in names:
                if name in result:
                    return result[name]

            return default

        for name in names:
            value = getattr(
                result,
                name,
                None,
            )

            if value is not None:
                return value

        return default

    @staticmethod
    def _is_success(
        result: Any,
    ) -> bool:

        value = (
            PermissionedDeploymentWorkflow
            ._extract(
                result,
                "success",
                "ok",
                "healthy",
                "ready",
                default=None,
            )
        )

        if value is not None:
            return bool(value)

        status = str(
            PermissionedDeploymentWorkflow
            ._extract(
                result,
                "status",
                "state",
                default="",
            )
        ).lower()

        return status in {
            "success",
            "successful",
            "completed",
            "deployed",
            "healthy",
            "ready",
            "running",
            "ok",
        }

    # ==========================================================
    # HEALTH
    # ==========================================================

    async def check_health(
        self,
        *,
        deployment_id: str | None = None,
        version: str | None = None,
        wait: bool = True,
    ) -> dict[str, Any]:
        """
        Perform a bounded deployment health check.

        No deployment or rollback is performed here.
        """

        method = self._find_method(
            self.deployment,
            self.HEALTH_METHODS,
        )

        if method is None:
            return {
                "checked": False,
                "healthy": False,
                "status": "health_service_unavailable",
            }

        deadline = (
            asyncio.get_running_loop().time()
            + self.health_timeout_seconds
        )

        attempts = 0

        while True:

            attempts += 1

            try:

                response = await self._call(
                    method,
                    deployment_id=deployment_id,
                    version=version,
                )

                healthy = self._is_success(
                    response
                )

                result = {
                    "checked": True,
                    "healthy": healthy,
                    "attempts": attempts,
                    "response": (
                        response
                        if isinstance(
                            response,
                            Mapping,
                        )
                        else str(response)
                    ),
                }

                if healthy or not wait:
                    return result

            except Exception as exc:

                result = {
                    "checked": True,
                    "healthy": False,
                    "attempts": attempts,
                    "error": str(exc),
                }

                if not wait:
                    return result

            if (
                asyncio.get_running_loop().time()
                >= deadline
            ):
                return result

            await asyncio.sleep(
                self.health_interval_seconds
            )

    # ==========================================================
    # DEPLOYMENT
    # ==========================================================

    async def deploy(
        self,
        *,
        authorization: DeploymentAuthorization | None,
        version: str | None = None,
        commit_id: str | None = None,
        branch: str | None = None,
        workspace_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> DeploymentResult:
        """
        Deploy only after explicit authorization.

        Deployment failure automatically triggers rollback when
        a compatible rollback capability exists.
        """

        started_at = _utc_now()

        if authorization is None:

            result = DeploymentResult(
                success=False,
                status="deployment_not_authorized",
                deployment_authorized=False,
                message=(
                    "Deployment requires explicit "
                    "user authorization."
                ),
                started_at=started_at,
                completed_at=_utc_now(),
                metadata=dict(
                    metadata or {}
                ),
            )

            self._last_result = result
            return result

        if not authorization.is_valid():

            result = DeploymentResult(
                success=False,
                status="invalid_authorization",
                deployment_authorized=False,
                message=(
                    "The deployment authorization "
                    "is invalid."
                ),
                started_at=started_at,
                completed_at=_utc_now(),
                metadata={
                    **dict(metadata or {}),
                    "authorization":
                        authorization.to_dict(),
                },
            )

            self._last_result = result
            return result

        method = self._find_method(
            self.deployment,
            self.DEPLOY_METHODS,
        )

        if method is None:

            result = DeploymentResult(
                success=False,
                status="deployment_service_unavailable",
                deployment_authorized=True,
                message=(
                    "No compatible deployment method "
                    "is available."
                ),
                started_at=started_at,
                completed_at=_utc_now(),
                metadata={
                    **dict(metadata or {}),
                    "authorization":
                        authorization.to_dict(),
                },
            )

            self._last_result = result
            return result

        deployment_id = None
        errors: list[str] = []

        try:

            response = await self._call(
                method,
                version=version,
                commit_id=commit_id,
                branch=branch,
                workspace_id=workspace_id,
            )

            deployment_id = self._extract(
                response,
                "deployment_id",
                "id",
                "deployment",
            )

            deployed = self._is_success(
                response
            )

        except Exception as exc:

            errors.append(
                str(exc)
            )

            deployed = False

        if not deployed:

            rollback_result = (
                await self._rollback(
                    deployment_id=(
                        str(deployment_id)
                        if deployment_id
                        else None
                    ),
                    version=version,
                    workspace_id=workspace_id,
                )
            )

            result = DeploymentResult(
                success=False,
                status=(
                    "deployment_failed_rolled_back"
                    if rollback_result["succeeded"]
                    else "deployment_failed"
                ),
                deployment_attempted=True,
                deployment_authorized=True,
                rollback_attempted=True,
                rollback_succeeded=(
                    rollback_result["succeeded"]
                ),
                deployment_id=(
                    str(deployment_id)
                    if deployment_id
                    else None
                ),
                version=version,
                message=(
                    "Deployment failed."
                ),
                errors=tuple(errors),
                started_at=started_at,
                completed_at=_utc_now(),
                metadata={
                    **dict(metadata or {}),
                    "authorization":
                        authorization.to_dict(),
                    "rollback":
                        rollback_result,
                },
            )

            self._last_result = result
            return result

        # ------------------------------------------------------
        # POST-DEPLOYMENT HEALTH CHECK
        # ------------------------------------------------------

        health = await self.check_health(
            deployment_id=(
                str(deployment_id)
                if deployment_id
                else None
            ),
            version=version,
            wait=True,
        )

        if health["healthy"]:

            result = DeploymentResult(
                success=True,
                status="deployment_healthy",
                deployment_attempted=True,
                deployment_authorized=True,
                health_checked=True,
                healthy=True,
                rollback_attempted=False,
                rollback_succeeded=False,
                deployment_id=(
                    str(deployment_id)
                    if deployment_id
                    else None
                ),
                version=version,
                message=(
                    "Deployment completed and "
                    "health check passed."
                ),
                started_at=started_at,
                completed_at=_utc_now(),
                metadata={
                    **dict(metadata or {}),
                    "authorization":
                        authorization.to_dict(),
                    "health":
                        health,
                },
            )

            self._last_result = result
            return result

        # ------------------------------------------------------
        # UNHEALTHY → ROLLBACK
        # ------------------------------------------------------

        rollback_result = (
            await self._rollback(
                deployment_id=(
                    str(deployment_id)
                    if deployment_id
                    else None
                ),
                version=version,
                workspace_id=workspace_id,
            )
        )

        result = DeploymentResult(
            success=False,
            status=(
                "unhealthy_rolled_back"
                if rollback_result["succeeded"]
                else "unhealthy_rollback_failed"
            ),
            deployment_attempted=True,
            deployment_authorized=True,
            health_checked=True,
            healthy=False,
            rollback_attempted=True,
            rollback_succeeded=(
                rollback_result["succeeded"]
            ),
            deployment_id=(
                str(deployment_id)
                if deployment_id
                else None
            ),
            version=version,
            message=(
                "Deployment became unhealthy; "
                "rollback was attempted."
            ),
            errors=tuple(
                errors
            ),
            started_at=started_at,
            completed_at=_utc_now(),
            metadata={
                **dict(metadata or {}),
                "authorization":
                    authorization.to_dict(),
                "health":
                    health,
                "rollback":
                    rollback_result,
            },
        )

        self._last_result = result
        return result

    # ==========================================================
    # ROLLBACK
    # ==========================================================

    async def _rollback(
        self,
        *,
        deployment_id: str | None = None,
        version: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:

        method = self._find_method(
            self.deployment,
            self.ROLLBACK_METHODS,
        )

        if method is None:
            return {
                "attempted": False,
                "succeeded": False,
                "status": "rollback_unavailable",
            }

        try:

            response = await self._call(
                method,
                deployment_id=deployment_id,
                version=version,
                workspace_id=workspace_id,
            )

            succeeded = self._is_success(
                response
            )

            return {
                "attempted": True,
                "succeeded": succeeded,
                "status": (
                    "rollback_completed"
                    if succeeded
                    else "rollback_failed"
                ),
                "response": (
                    response
                    if isinstance(
                        response,
                        Mapping,
                    )
                    else str(response)
                ),
            }

        except Exception as exc:

            return {
                "attempted": True,
                "succeeded": False,
                "status": "rollback_error",
                "error": str(exc),
            }

    async def rollback(
        self,
        *,
        deployment_id: str | None = None,
        version: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Public explicit rollback operation.

        Rollback is delegated to the existing deployment service.
        """

        return await self._rollback(
            deployment_id=deployment_id,
            version=version,
            workspace_id=workspace_id,
        )

    # ==========================================================
    # STATUS / HEALTH
    # ==========================================================

    async def status(
        self,
        *,
        deployment_id: str | None = None,
    ) -> dict[str, Any]:

        method = self._find_method(
            self.deployment,
            self.STATUS_METHODS,
        )

        if method is None:
            return {
                "available": False,
                "status": (
                    "deployment_service_unavailable"
                ),
            }

        try:

            response = await self._call(
                method,
                deployment_id=deployment_id,
            )

            if isinstance(
                response,
                Mapping,
            ):
                return {
                    "available": True,
                    **dict(response),
                }

            return {
                "available": True,
                "status": str(response),
            }

        except Exception as exc:

            return {
                "available": False,
                "status": "error",
                "error": str(exc),
            }

    def health(self) -> dict[str, Any]:
        return {
            "healthy": (
                self.deployment is not None
            ),
            "deployment_service": (
                self.deployment is not None
            ),
            "health_timeout_seconds": (
                self.health_timeout_seconds
            ),
            "health_interval_seconds": (
                self.health_interval_seconds
            ),
            "last_success": (
                self._last_result.success
                if self._last_result is not None
                else None
            ),
        }

    def describe(self) -> dict[str, Any]:
        return {
            "name": (
                "permissioned_deployment_workflow"
            ),
            "purpose": (
                "Controlled deployment with bounded "
                "health verification and rollback."
            ),
            "deployment_requires_explicit_authorization": True,
            "automatic_deployment": False,
            "automatic_rollback_on_failed_health": True,
            "github_push": False,
            "direct_shell_execution": False,
        }


__all__ = [
    "DeploymentAuthorization",
    "DeploymentResult",
    "PermissionedDeploymentWorkflow",
]