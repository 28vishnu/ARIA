from __future__ import annotations

import inspect
from typing import Any

from .contracts.engineering_deployment import (
    DeploymentAuthorization,
    DeploymentOperation,
    DeploymentPlan,
    DeploymentRequest,
    DeploymentResult,
    DeploymentRisk,
    DeploymentRollbackPlan,
    DeploymentStatus,
    HealthCheckDefinition,
    HealthCheckResult,
)


class AuthoritativeDeploymentEngine:
    """
    Controlled deployment / health / rollback boundary.

    Deployment, health verification, and rollback are deliberately
    separate operations.

    This engine does not assume that:
        deployment succeeded == service is healthy
        health is healthy == requirement is accepted

    Current engineering evidence remains authoritative.
    """

    def __init__(
        self,
        *,
        deployment_service: Any | None = None,
        health_monitor: Any | None = None,
        rollback_manager: Any | None = None,
        health_timeout_seconds: float = 60.0,
        health_interval_seconds: float = 5.0,
    ) -> None:
        self.deployment_service = deployment_service
        self.health_monitor = health_monitor
        self.rollback_manager = rollback_manager
        self.health_timeout_seconds = max(
            1.0,
            float(health_timeout_seconds),
        )
        self.health_interval_seconds = max(
            0.5,
            float(health_interval_seconds),
        )

    def plan(
        self,
        request: DeploymentRequest,
    ) -> DeploymentPlan:
        environment = request.environment.strip()

        if not environment:
            environment = "unknown"

        risk = self._calculate_risk(request)

        operations = (
            DeploymentOperation.PREPARE,
            DeploymentOperation.DEPLOY,
            DeploymentOperation.HEALTH_CHECK,
        )

        if request.explicit_rollback_authorized:
            operations += (
                DeploymentOperation.ROLLBACK,
            )

        health_checks: list[HealthCheckDefinition] = []

        if request.health_endpoint:
            health_checks.append(
                HealthCheckDefinition(
                    check_id="deployment-endpoint",
                    description=(
                        "Verify that the deployed service responds "
                        "successfully at the configured health endpoint."
                    ),
                    endpoint=request.health_endpoint,
                    timeout_seconds=(
                        request.health_timeout_seconds
                    ),
                )
            )

        if request.health_command:
            health_checks.append(
                HealthCheckDefinition(
                    check_id="deployment-command",
                    description=(
                        "Run the configured deployment health command."
                    ),
                    command=request.health_command,
                    timeout_seconds=(
                        request.health_timeout_seconds
                    ),
                )
            )

        if not health_checks:
            health_checks.append(
                HealthCheckDefinition(
                    check_id="service-health",
                    description=(
                        "Use the configured health monitor to establish "
                        "post-deployment service health."
                    ),
                    timeout_seconds=(
                        request.health_timeout_seconds
                    ),
                )
            )

        rollback = (
            DeploymentRollbackPlan(
                rollback_id="deployment-rollback",
                description=(
                    "Restore the last known healthy deployment."
                ),
                trigger=(
                    "Required health check fails after deployment."
                ),
                required=True,
            ),
        )

        status = (
            DeploymentStatus.READY
            if request.explicit_deploy_authorized
            else DeploymentStatus.AWAITING_APPROVAL
        )

        return DeploymentPlan(
            session_id=request.session_id,
            environment=environment,
            version=request.version,
            status=status,
            risk=risk,
            operations=operations,
            health_checks=tuple(health_checks),
            rollback=rollback,
            approval_required=True,
            branch=request.branch,
            commit_sha=request.commit_sha,
            changed_paths=tuple(
                request.changed_paths
            ),
            rationale=(
                "Deployment requires explicit authorization, followed "
                "by independent health verification and rollback "
                "protection."
            ),
        )

    async def execute(
        self,
        plan: DeploymentPlan,
        *,
        authorization: DeploymentAuthorization | None = None,
        rollback_authorization: DeploymentAuthorization | None = None,
    ) -> DeploymentResult:
        if not plan.session_id:
            return self._failed(
                plan,
                "Deployment requires a session_id.",
            )

        if not self._deployment_authorized(
            authorization
        ):
            return DeploymentResult(
                status=DeploymentStatus.AWAITING_APPROVAL,
                operation=DeploymentOperation.DEPLOY,
                environment=plan.environment,
                version=plan.version,
                warnings=(
                    "Deployment authorization was not granted.",
                ),
            )

        if self.deployment_service is None:
            return self._failed(
                plan,
                "Deployment service is unavailable.",
            )

        deployment_result = await self._deploy(
            plan
        )

        if not deployment_result[0]:
            return self._failed(
                plan,
                deployment_result[1],
                operation=DeploymentOperation.DEPLOY,
            )

        deployment_id = deployment_result[2]

        health = await self._health_check(
            plan,
            deployment_id,
        )

        if health[0]:
            return DeploymentResult(
                status=DeploymentStatus.HEALTHY,
                operation=DeploymentOperation.HEALTH_CHECK,
                environment=plan.environment,
                version=plan.version,
                deployment_id=deployment_id,
                health_results=tuple(
                    health[1]
                ),
                rollback_performed=False,
                evidence=(
                    {
                        "stage": "deployment",
                        "status": "completed",
                        "deployment_id": deployment_id,
                    },
                    {
                        "stage": "health_check",
                        "status": "healthy",
                    },
                ),
            )

        health_results = tuple(
            health[1]
        )

        if not self._rollback_authorized(
            rollback_authorization
        ):
            return DeploymentResult(
                status=DeploymentStatus.UNHEALTHY,
                operation=DeploymentOperation.HEALTH_CHECK,
                environment=plan.environment,
                version=plan.version,
                deployment_id=deployment_id,
                health_results=health_results,
                rollback_performed=False,
                warnings=(
                    "Deployment is unhealthy and rollback authorization "
                    "has not been granted.",
                ),
                errors=(
                    "Post-deployment health verification failed.",
                ),
                evidence=(
                    {
                        "stage": "health_check",
                        "status": "unhealthy",
                    },
                ),
            )

        rollback = await self._rollback(
            plan,
            deployment_id,
        )

        if not rollback[0]:
            return DeploymentResult(
                status=DeploymentStatus.FAILED,
                operation=DeploymentOperation.ROLLBACK,
                environment=plan.environment,
                version=plan.version,
                deployment_id=deployment_id,
                health_results=health_results,
                rollback_performed=False,
                errors=(
                    "Deployment health failed and rollback also failed.",
                    rollback[1],
                ),
            )

        rollback_id = rollback[2]

        rollback_health = await self._health_check(
            plan,
            rollback_id,
        )

        if rollback_health[0]:
            return DeploymentResult(
                status=DeploymentStatus.ROLLED_BACK,
                operation=DeploymentOperation.ROLLBACK,
                environment=plan.environment,
                version=plan.version,
                deployment_id=deployment_id,
                health_results=(
                    health_results
                    + tuple(rollback_health[1])
                ),
                rollback_performed=True,
                rollback_id=rollback_id,
                warnings=(
                    "The new deployment was unhealthy and was "
                    "successfully rolled back.",
                ),
                evidence=(
                    {
                        "stage": "deployment",
                        "status": "unhealthy",
                        "deployment_id": deployment_id,
                    },
                    {
                        "stage": "rollback",
                        "status": "completed",
                        "rollback_id": rollback_id,
                    },
                    {
                        "stage": "rollback_health",
                        "status": "healthy",
                    },
                ),
            )

        return DeploymentResult(
            status=DeploymentStatus.FAILED,
            operation=DeploymentOperation.ROLLBACK,
            environment=plan.environment,
            version=plan.version,
            deployment_id=deployment_id,
            health_results=(
                health_results
                + tuple(rollback_health[1])
            ),
            rollback_performed=True,
            rollback_id=rollback_id,
            errors=(
                "The deployment was unhealthy.",
                "Rollback completed but rollback health verification failed.",
            ),
        )

    async def _deploy(
        self,
        plan: DeploymentPlan,
    ) -> tuple[bool, str, str | None]:
        service = self.deployment_service

        methods = (
            "deploy",
            "deploy_version",
            "start_deployment",
            "execute_deployment",
        )

        for name in methods:
            method = getattr(
                service,
                name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = self._invoke(
                    method,
                    plan,
                )

                if inspect.isawaitable(result):
                    result = await result

                if result is False:
                    return (
                        False,
                        f"Deployment failed using {name}.",
                        None,
                    )

                deployment_id = self._extract_identifier(
                    result,
                    (
                        "deployment_id",
                        "id",
                        "version",
                    ),
                )

                return (
                    True,
                    "",
                    deployment_id,
                )

            except Exception as exc:
                return (
                    False,
                    f"Deployment failed: {exc}",
                    None,
                )

        return (
            False,
            "Deployment service has no supported deployment method.",
            None,
        )

    async def _health_check(
        self,
        plan: DeploymentPlan,
        deployment_id: str | None,
    ) -> tuple[bool, list[HealthCheckResult]]:
        results: list[HealthCheckResult] = []

        for definition in plan.health_checks:
            result = await self._run_health_check(
                definition,
                deployment_id,
            )

            results.append(result)

            if definition.required and not result.passed:
                return False, results

        return True, results

    async def _run_health_check(
        self,
        definition: HealthCheckDefinition,
        deployment_id: str | None,
    ) -> HealthCheckResult:
        monitor = self.health_monitor

        if definition.endpoint and monitor is not None:
            for name in (
                "check",
                "check_health",
                "wait_until_healthy",
                "probe",
            ):
                method = getattr(
                    monitor,
                    name,
                    None,
                )

                if not callable(method):
                    continue

                try:
                    result = self._invoke_health(
                        method,
                        definition,
                        deployment_id,
                    )

                    if inspect.isawaitable(result):
                        result = await result

                    normalized = self._normalize_health_result(
                        definition,
                        result,
                    )

                    if normalized is not None:
                        return normalized

                except Exception as exc:
                    return HealthCheckResult(
                        check_id=definition.check_id,
                        passed=False,
                        error=str(exc),
                    )

        if definition.command and monitor is not None:
            for name in (
                "run_check",
                "execute_check",
                "check_command",
            ):
                method = getattr(
                    monitor,
                    name,
                    None,
                )

                if not callable(method):
                    continue

                try:
                    result = method(
                        definition.command,
                        timeout=definition.timeout_seconds,
                    )

                    if inspect.isawaitable(result):
                        result = await result

                    normalized = self._normalize_health_result(
                        definition,
                        result,
                    )

                    if normalized is not None:
                        return normalized

                except Exception as exc:
                    return HealthCheckResult(
                        check_id=definition.check_id,
                        passed=False,
                        error=str(exc),
                    )

        if monitor is None:
            return HealthCheckResult(
                check_id=definition.check_id,
                passed=False,
                error=(
                    "Health monitor is unavailable; health cannot "
                    "be assumed."
                ),
            )

        return HealthCheckResult(
            check_id=definition.check_id,
            passed=False,
            error=(
                "No compatible health-monitor operation was available."
            ),
        )

    async def _rollback(
        self,
        plan: DeploymentPlan,
        deployment_id: str | None,
    ) -> tuple[bool, str, str | None]:
        manager = self.rollback_manager

        if manager is None:
            return (
                False,
                "Rollback manager is unavailable.",
                None,
            )

        methods = (
            "rollback",
            "rollback_deployment",
            "restore_previous",
            "restore_last_known_good",
        )

        for name in methods:
            method = getattr(
                manager,
                name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = self._invoke_rollback(
                    method,
                    plan,
                    deployment_id,
                )

                if inspect.isawaitable(result):
                    result = await result

                if result is False:
                    return (
                        False,
                        f"Rollback failed using {name}.",
                        None,
                    )

                rollback_id = self._extract_identifier(
                    result,
                    (
                        "rollback_id",
                        "deployment_id",
                        "id",
                        "version",
                    ),
                )

                return (
                    True,
                    "",
                    rollback_id,
                )

            except Exception as exc:
                return (
                    False,
                    f"Rollback failed: {exc}",
                    None,
                )

        return (
            False,
            "Rollback manager has no supported rollback method.",
            None,
        )

    @staticmethod
    def _deployment_authorized(
        authorization: DeploymentAuthorization | None,
    ) -> bool:
        return bool(
            authorization
            and authorization.granted
            and authorization.authority == "user"
        )

    @staticmethod
    def _rollback_authorized(
        authorization: DeploymentAuthorization | None,
    ) -> bool:
        return bool(
            authorization
            and authorization.granted
            and authorization.authority == "user"
        )

    @staticmethod
    def _calculate_risk(
        request: DeploymentRequest,
    ) -> DeploymentRisk:
        environment = request.environment.lower()

        if environment in {
            "production",
            "prod",
            "live",
        }:
            return DeploymentRisk.CRITICAL

        if request.changed_paths and len(
            request.changed_paths
        ) > 20:
            return DeploymentRisk.HIGH

        if request.commit_sha:
            return DeploymentRisk.MEDIUM

        return DeploymentRisk.LOW

    @staticmethod
    def _invoke(
        method: Any,
        plan: DeploymentPlan,
    ) -> Any:
        candidates = (
            {
                "environment": plan.environment,
                "version": plan.version,
                "branch": plan.branch,
                "commit_sha": plan.commit_sha,
            },
            {
                "environment": plan.environment,
                "version": plan.version,
            },
            {
                "version": plan.version,
            },
        )

        last_error: Exception | None = None

        for kwargs in candidates:
            try:
                return method(**kwargs)
            except TypeError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error

        return method()

    @staticmethod
    def _invoke_health(
        method: Any,
        definition: HealthCheckDefinition,
        deployment_id: str | None,
    ) -> Any:
        candidates = (
            {
                "endpoint": definition.endpoint,
                "timeout": definition.timeout_seconds,
                "deployment_id": deployment_id,
            },
            {
                "endpoint": definition.endpoint,
                "timeout_seconds": definition.timeout_seconds,
            },
            {
                "endpoint": definition.endpoint,
            },
        )

        last_error: Exception | None = None

        for kwargs in candidates:
            try:
                return method(**kwargs)
            except TypeError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error

        return method()

    @staticmethod
    def _invoke_rollback(
        method: Any,
        plan: DeploymentPlan,
        deployment_id: str | None,
    ) -> Any:
        candidates = (
            {
                "environment": plan.environment,
                "deployment_id": deployment_id,
            },
            {
                "deployment_id": deployment_id,
            },
            {
                "environment": plan.environment,
            },
        )

        last_error: Exception | None = None

        for kwargs in candidates:
            try:
                return method(**kwargs)
            except TypeError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error

        return method()

    @staticmethod
    def _normalize_health_result(
        definition: HealthCheckDefinition,
        result: Any,
    ) -> HealthCheckResult | None:
        if result is None:
            return None

        if isinstance(result, HealthCheckResult):
            return result

        if isinstance(result, bool):
            return HealthCheckResult(
                check_id=definition.check_id,
                passed=result,
            )

        if isinstance(result, dict):
            status_code = result.get(
                "status_code"
            )

            passed = result.get(
                "passed"
            )

            if passed is None:
                if status_code is not None:
                    passed = (
                        status_code
                        == definition.expected_status
                    )
                else:
                    passed = bool(
                        result.get("healthy", False)
                    )

            return HealthCheckResult(
                check_id=definition.check_id,
                passed=bool(passed),
                status_code=status_code,
                stdout=str(
                    result.get("stdout", "")
                ),
                stderr=str(
                    result.get("stderr", "")
                ),
                duration_seconds=float(
                    result.get(
                        "duration_seconds",
                        0.0,
                    )
                ),
                error=(
                    str(result["error"])
                    if result.get("error")
                    else None
                ),
                metadata=dict(result),
            )

        passed = getattr(
            result,
            "passed",
            None,
        )

        if passed is None:
            passed = getattr(
                result,
                "healthy",
                None,
            )

        if passed is None:
            return None

        return HealthCheckResult(
            check_id=definition.check_id,
            passed=bool(passed),
            status_code=getattr(
                result,
                "status_code",
                None,
            ),
            stdout=str(
                getattr(
                    result,
                    "stdout",
                    "",
                )
            ),
            stderr=str(
                getattr(
                    result,
                    "stderr",
                    "",
                )
            ),
            duration_seconds=float(
                getattr(
                    result,
                    "duration_seconds",
                    0.0,
                )
            ),
            error=getattr(
                result,
                "error",
                None,
            ),
        )

    @staticmethod
    def _extract_identifier(
        result: Any,
        fields: tuple[str, ...],
    ) -> str | None:
        if result is None:
            return None

        if isinstance(result, str):
            return result

        if isinstance(result, dict):
            for field in fields:
                value = result.get(field)

                if value:
                    return str(value)

        for field in fields:
            value = getattr(
                result,
                field,
                None,
            )

            if value:
                return str(value)

        return None

    @staticmethod
    def _failed(
        plan: DeploymentPlan,
        error: str,
        *,
        operation: DeploymentOperation = DeploymentOperation.DEPLOY,
    ) -> DeploymentResult:
        return DeploymentResult(
            status=DeploymentStatus.FAILED,
            operation=operation,
            environment=plan.environment,
            version=plan.version,
            errors=(error,),
        )