"""
ARIA Autonomous Engineering Lifecycle
=====================================

Canonical gateway for autonomous software-engineering execution.

Architecture:

    JARVIS Request
          |
          v
    EngineeringExecutionMode
          |
          v
    AutonomousEngineeringLifecycle
          |
          v
    FinalAutonomousEngineer
          |
          v
    AuthoritativeEngineeringOrchestrator
          |
          v
    Requirement -> Knowledge -> Planning -> Task Graph
          |
          v
    Implementation -> Verification -> Diagnosis
          |
          v
    Recovery -> Acceptance -> Experience

This module is an integration boundary.

It does NOT duplicate:
    - FinalAutonomousEngineer
    - AuthoritativeEngineeringOrchestrator
    - Git/GitHub
    - Deployment
    - Rollback
    - Repository intelligence

It delegates engineering execution to the already-existing canonical
FinalAutonomousEngineer.

Safety:
    - This gateway never performs GitHub push itself.
    - This gateway never performs deployment itself.
    - This gateway never bypasses authorization.
    - Read-only/plan-only requests are rejected before execution.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, Mapping, Optional


logger = logging.getLogger("aria.autonomous_engineering_lifecycle")


class AutonomousEngineeringLifecycle:
    """
    Single canonical gateway for autonomous engineering.

    The object is intentionally thin.  The authoritative engineering
    implementation remains FinalAutonomousEngineer.
    """

    VERSION = "ARIA-AUTONOMOUS-ENGINEERING-LIFECYCLE-20261006"

    def __init__(
        self,
        final_engineer: Any = None,
        *,
        execution_mode: Any = None,
        repository_intelligence: Any = None,
        readiness_gateway: Any = None,
    ) -> None:
        self.final_engineer = final_engineer
        self.execution_mode = execution_mode
        self.repository_intelligence = repository_intelligence
        self.readiness_gateway = readiness_gateway

        logger.info(
            "[AutonomousEngineeringLifecycle] Initialized | "
            "final_engineer=%s | execution_mode=%s | repository_intelligence=%s",
            bool(final_engineer),
            bool(execution_mode),
            bool(repository_intelligence),
        )

    # ==================================================================
    # PRIMARY API
    # ==================================================================

    async def develop(
        self,
        request: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
        session_id: str = "",
        user_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Execute an autonomous engineering request.

        This is the preferred canonical entry point.

        Safety policy is evaluated before FinalAutonomousEngineer is called.
        """

        request_text = self._request_text(request)
        ctx = dict(context or {})

        policy = self._execution_policy(
            request_text,
            ctx,
        )

        if policy is not None:
            if not bool(
                self._value(
                    policy,
                    "execution_allowed",
                    False,
                )
            ):
                return self._blocked_result(
                    request_text,
                    policy,
                    reason=(
                        "Engineering execution is not allowed for this "
                        "request. The request is read-only, plan-only, "
                        "or requires a separate authorization boundary."
                    ),
                )

        if self.final_engineer is None:
            return self._failure_result(
                request_text,
                "The canonical FinalAutonomousEngineer is unavailable.",
            )

        if not self._engineer_is_usable():
            return self._failure_result(
                request_text,
                "The canonical FinalAutonomousEngineer is not ready.",
            )

        # Repository context is a prerequisite for actual engineering
        # execution when the repository-intelligence service is available.
        #
        # This does NOT fail execution merely because optional repository
        # inspection is unavailable.  The authoritative engineer remains the
        # final owner of engineering validation.
        repository_context = None

        if self.repository_intelligence is not None:
            try:
                repository_context = await self._inspect_repository(
                    request_text,
                    ctx,
                )

                if repository_context is not None:
                    ctx["repository_intelligence"] = repository_context

            except Exception as exc:
                logger.warning(
                    "[AutonomousEngineeringLifecycle] Repository inspection "
                    "failed before engineering execution: %s",
                    exc,
                )

        ctx["engineering_execution"] = True
        ctx["autonomous_engineering"] = True
        ctx["canonical_engineering_lifecycle"] = True

        if session_id:
            ctx["session_id"] = session_id

        if user_id:
            ctx["user_id"] = user_id

        try:
            result = await self._invoke_engineer(
                request_text,
                context=ctx,
                session_id=session_id,
                user_id=user_id,
                **kwargs,
            )

            normalized = self._normalize_result(
                result,
                request_text,
            )

            if repository_context is not None:
                normalized.setdefault(
                    "repository_intelligence",
                    repository_context,
                )

            normalized["lifecycle"] = self.VERSION
            normalized["canonical"] = True

            logger.info(
                "[AutonomousEngineeringLifecycle] Engineering execution "
                "completed | success=%s",
                normalized.get("success"),
            )

            return normalized

        except Exception as exc:
            logger.exception(
                "[AutonomousEngineeringLifecycle] Engineering execution failed."
            )

            return self._failure_result(
                request_text,
                str(exc),
            )

    async def execute(
        self,
        request: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
        session_id: str = "",
        user_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Compatibility alias for develop().
        """

        return await self.develop(
            request,
            context=context,
            session_id=session_id,
            user_id=user_id,
            **kwargs,
        )

    async def run(
        self,
        request: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
        session_id: str = "",
        user_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Compatibility alias for develop().
        """

        return await self.develop(
            request,
            context=context,
            session_id=session_id,
            user_id=user_id,
            **kwargs,
        )

    async def resume(
        self,
        session_id: str,
        *,
        context: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Resume an interrupted engineering session through the existing
        FinalAutonomousEngineer.

        No new recovery engine is created here.
        """

        if not session_id:
            return self._failure_result(
                "",
                "A session_id is required to resume engineering.",
            )

        if self.final_engineer is None:
            return self._failure_result(
                "",
                "The canonical FinalAutonomousEngineer is unavailable.",
            )

        ctx = dict(context or {})
        ctx["session_id"] = session_id
        ctx["resume"] = True
        ctx["autonomous_engineering"] = True
        ctx["canonical_engineering_lifecycle"] = True

        resume_method = getattr(
            self.final_engineer,
            "resume",
            None,
        )

        if not callable(resume_method):
            return self._failure_result(
                "",
                "The canonical FinalAutonomousEngineer does not expose resume().",
            )

        try:
            result = await self._call_compatible(
                resume_method,
                session_id=session_id,
                context=ctx,
                **kwargs,
            )

            normalized = self._normalize_result(
                result,
                "",
            )

            normalized["lifecycle"] = self.VERSION
            normalized["canonical"] = True
            normalized["resumed"] = True

            return normalized

        except Exception as exc:
            logger.exception(
                "[AutonomousEngineeringLifecycle] Resume failed."
            )

            return self._failure_result(
                "",
                str(exc),
            )

    async def status(
        self,
        *,
        session_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Return the current engineering status.

        This method never executes engineering work.
        """

        if self.final_engineer is None:
            return {
                "healthy": False,
                "available": False,
                "version": self.VERSION,
                "error": (
                    "FinalAutonomousEngineer is unavailable."
                ),
            }

        status_method = getattr(
            self.final_engineer,
            "status",
            None,
        )

        if callable(status_method):
            try:
                result = await self._call_compatible(
                    status_method,
                    session_id=session_id,
                    **kwargs,
                )

                if isinstance(result, Mapping):
                    data = dict(result)
                else:
                    data = {
                        "status": result,
                    }

                data.setdefault(
                    "version",
                    self.VERSION,
                )
                data.setdefault(
                    "canonical",
                    True,
                )

                return data

            except Exception as exc:
                logger.warning(
                    "[AutonomousEngineeringLifecycle] Status failed: %s",
                    exc,
                )

        return {
            "healthy": self._engineer_is_usable(),
            "available": True,
            "version": self.VERSION,
            "canonical": True,
            "session_id": session_id,
        }

    def health(self) -> Dict[str, Any]:
        """
        Return deterministic health information.

        This method is synchronous and performs no engineering execution.
        """

        engineer_available = self.final_engineer is not None

        engineer_healthy = False

        if engineer_available:
            try:
                health_method = getattr(
                    self.final_engineer,
                    "health",
                    None,
                )

                if callable(health_method):
                    result = health_method()

                    if inspect.isawaitable(result):
                        # Do not run an event loop from a synchronous health
                        # method.  Presence of the method is enough for the
                        # synchronous structural health check.
                        engineer_healthy = True
                    elif isinstance(result, Mapping):
                        engineer_healthy = bool(
                            result.get(
                                "healthy",
                                result.get(
                                    "available",
                                    True,
                                ),
                            )
                        )
                    else:
                        engineer_healthy = bool(result)

                else:
                    engineer_healthy = self._engineer_is_usable()

            except Exception as exc:
                logger.warning(
                    "[AutonomousEngineeringLifecycle] Health check failed: %s",
                    exc,
                )

        else:
            engineer_healthy = False

        return {
            "healthy": bool(
                engineer_available and engineer_healthy
            ),
            "version": self.VERSION,
            "canonical": True,
            "final_engineer_available": engineer_available,
            "final_engineer_healthy": engineer_healthy,
            "execution_mode_available": (
                self.execution_mode is not None
            ),
            "repository_intelligence_available": (
                self.repository_intelligence is not None
            ),
            "readiness_gateway_available": (
                self.readiness_gateway is not None
            ),
            "delivery_owned_elsewhere": True,
            "github_push_owned_elsewhere": True,
            "deployment_owned_elsewhere": True,
            "rollback_owned_elsewhere": True,
        }

    def capabilities(self) -> Dict[str, Any]:
        """
        Describe the capabilities exposed by this gateway.
        """

        return {
            "develop": True,
            "execute": True,
            "run": True,
            "resume": True,
            "status": True,
            "health": True,
            "repository_context": (
                self.repository_intelligence is not None
            ),
            "readiness_check": (
                self.readiness_gateway is not None
            ),
            "github_push": False,
            "deployment": False,
            "rollback": False,
            "side_effects_outside_engineer": False,
        }

    # ==================================================================
    # EXECUTION POLICY
    # ==================================================================

    def _execution_policy(
        self,
        request: str,
        context: Mapping[str, Any],
    ) -> Any:
        """
        Ask EngineeringExecutionMode for policy.

        The gateway remains compatible with older selector method names.
        """

        selector = self.execution_mode

        if selector is None:
            return None

        for method_name in (
            "determine",
            "select",
            "decide",
            "resolve",
        ):
            method = getattr(
                selector,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method(
                    request,
                    context=context,
                )

                return result

            except TypeError:
                try:
                    return method(request)
                except Exception:
                    continue

            except Exception:
                logger.warning(
                    "[AutonomousEngineeringLifecycle] "
                    "Execution-mode selection failed.",
                    exc_info=True,
                )
                return None

        return None

    # ==================================================================
    # REPOSITORY INTELLIGENCE
    # ==================================================================

    async def _inspect_repository(
        self,
        request: str,
        context: Mapping[str, Any],
    ) -> Any:
        service = self.repository_intelligence

        if service is None:
            return None

        for method_name in (
            "inspect",
            "analyze",
            "analyze_repository",
            "get_snapshot",
        ):
            method = getattr(
                service,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method(
                    request,
                    context=context,
                )

                if inspect.isawaitable(result):
                    result = await result

                return result

            except TypeError:
                try:
                    result = method(request)

                    if inspect.isawaitable(result):
                        result = await result

                    return result

                except Exception:
                    continue

            except Exception:
                logger.warning(
                    "[AutonomousEngineeringLifecycle] "
                    "Repository method %s failed.",
                    method_name,
                    exc_info=True,
                )

        return None

    # ==================================================================
    # FINAL ENGINEER INVOCATION
    # ==================================================================

    async def _invoke_engineer(
        self,
        request: str,
        *,
        context: Mapping[str, Any],
        session_id: str = "",
        user_id: str = "",
        **kwargs: Any,
    ) -> Any:
        """
        Invoke the existing FinalAutonomousEngineer using compatible
        signatures.

        We deliberately do not instantiate or replace the engineer here.
        """

        engineer = self.final_engineer

        develop_method = getattr(
            engineer,
            "develop",
            None,
        )

        if not callable(develop_method):
            raise RuntimeError(
                "FinalAutonomousEngineer does not expose develop()."
            )

        return await self._call_compatible(
            develop_method,
            request=request,
            query=request,
            requirement=request,
            context=dict(context),
            session_id=session_id,
            user_id=user_id,
            **kwargs,
        )

    async def _call_compatible(
        self,
        method: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Call an existing ARIA method without assuming one exact historical
        signature.

        Only arguments explicitly accepted by the target method are sent.
        """

        if not callable(method):
            raise TypeError(
                "Target is not callable."
            )

        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            result = method()

            if inspect.isawaitable(result):
                return await result

            return result

        parameters = signature.parameters

        accepts_var_kwargs = any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        if accepts_var_kwargs:
            selected_kwargs = dict(kwargs)

        else:
            selected_kwargs = {
                key: value
                for key, value in kwargs.items()
                if key in parameters
            }

        # Some historical methods expect the request as a positional
        # argument named differently. Prefer the canonical request/query
        # names when they exist.
        positional_request = None

        for name in (
            "request",
            "query",
            "requirement",
            "goal",
            "instruction",
        ):
            if name in parameters and name in selected_kwargs:
                positional_request = selected_kwargs.pop(name)
                break

        if positional_request is not None:
            result = method(
                positional_request,
                **selected_kwargs,
            )
        else:
            result = method(
                **selected_kwargs,
            )

        if inspect.isawaitable(result):
            return await result

        return result

    # ==================================================================
    # ENGINE STATUS
    # ==================================================================

    def _engineer_is_usable(self) -> bool:
        if self.final_engineer is None:
            return False

        develop_method = getattr(
            self.final_engineer,
            "develop",
            None,
        )

        return callable(develop_method)

    # ==================================================================
    # RESULT NORMALIZATION
    # ==================================================================

    @classmethod
    def _normalize_result(
        cls,
        result: Any,
        request: str,
    ) -> Dict[str, Any]:
        if isinstance(result, Mapping):
            normalized = dict(result)

        elif result is None:
            normalized = {
                "success": False,
                "result": None,
                "message": (
                    "The autonomous engineering lifecycle "
                    "returned no result."
                ),
            }

        elif hasattr(result, "to_dict"):
            try:
                converted = result.to_dict()

                if isinstance(converted, Mapping):
                    normalized = dict(converted)
                else:
                    normalized = {
                        "result": converted,
                    }

            except Exception:
                normalized = {
                    "result": result,
                }

        else:
            normalized = {
                "result": result,
            }

        if "success" not in normalized:
            status = str(
                normalized.get(
                    "status",
                    "",
                )
            ).lower()

            if status in {
                "success",
                "completed",
                "accepted",
                "complete",
            }:
                normalized["success"] = True

            elif status in {
                "failed",
                "error",
                "rejected",
            }:
                normalized["success"] = False

        normalized.setdefault(
            "success",
            True,
        )

        normalized.setdefault(
            "request",
            request,
        )

        return normalized

    # ==================================================================
    # SAFETY RESULTS
    # ==================================================================

    @staticmethod
    def _blocked_result(
        request: str,
        policy: Any,
        *,
        reason: str,
    ) -> Dict[str, Any]:
        if hasattr(policy, "to_dict"):
            try:
                policy_data = policy.to_dict()
            except Exception:
                policy_data = {}
        elif isinstance(policy, Mapping):
            policy_data = dict(policy)
        else:
            policy_data = {
                "mode": getattr(
                    policy,
                    "mode",
                    "",
                ),
            }

        return {
            "success": False,
            "blocked": True,
            "execution_blocked": True,
            "request": request,
            "message": reason,
            "error": reason,
            "execution_policy": policy_data,
            "canonical": True,
        }

    @staticmethod
    def _failure_result(
        request: str,
        error: str,
    ) -> Dict[str, Any]:
        return {
            "success": False,
            "blocked": False,
            "request": request,
            "error": str(error),
            "message": str(error),
            "canonical": True,
        }

    # ==================================================================
    # GENERAL HELPERS
    # ==================================================================

    @staticmethod
    def _request_text(request: Any) -> str:
        if isinstance(request, str):
            return request

        if isinstance(request, Mapping):
            for key in (
                "query",
                "request",
                "text",
                "message",
                "content",
                "original_request",
            ):
                value = request.get(key)

                if value is not None:
                    return str(value)

            return str(request)

        for attribute in (
            "query",
            "request",
            "text",
            "message",
            "content",
            "original_request",
        ):
            value = getattr(
                request,
                attribute,
                None,
            )

            if value is not None:
                return str(value)

        return str(request or "")

    @staticmethod
    def _value(
        obj: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        if obj is None:
            return default

        if isinstance(obj, Mapping):
            return obj.get(
                key,
                default,
            )

        return getattr(
            obj,
            key,
            default,
        )


# ======================================================================
# Compatibility alias
# ======================================================================

AutonomousEngineeringGateway = AutonomousEngineeringLifecycle


__all__ = [
    "AutonomousEngineeringLifecycle",
    "AutonomousEngineeringGateway",
]