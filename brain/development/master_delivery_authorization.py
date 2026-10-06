"""
ARIA Master Delivery Authorization
==================================

Canonical authorization boundary for delivery operations.

Protected operations:

    - GitHub push
    - GitHub merge
    - deployment
    - rollback

Rules:

    1. No protected delivery operation executes without explicit Master
       authorization.

    2. Authorization must be present in the current request/context.
       Historical authorization is never silently reused.

    3. Production direct-write remains disabled.

    4. Automatic delivery remains disabled.

    5. This module does not replace GitManager, GitHubManager,
       DeploymentManager, RollbackManager, ApprovalManager, or the
       existing Phase1DeliveryGateway.

    6. The existing delivery implementation remains the execution owner.

    7. Without authorization, return a deterministic blocked result instead
       of falling through to a generic LLM/GitHub tutorial.

This module is intentionally fail-closed.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Dict, Mapping, Optional


logger = logging.getLogger("aria.master_delivery_authorization")


class MasterDeliveryAuthorization:
    """
    Canonical Master authorization coordinator.

    This object decides whether a protected delivery operation may proceed.
    Actual delivery remains owned by the existing Phase1DeliveryGateway.
    """

    VERSION = "ARIA-MASTER-DELIVERY-AUTHORIZATION-20261006"

    PROTECTED_OPERATIONS = frozenset(
        {
            "github_push",
            "github_merge",
            "deployment",
            "rollback",
        }
    )

    def __init__(
        self,
        delivery_gateway: Any = None,
        *,
        approval_manager: Any = None,
        github_manager: Any = None,
        deployment_manager: Any = None,
        rollback_manager: Any = None,
        deployment_policy: Any = None,
        telegram_approval_interface: Any = None,
    ) -> None:
        self.delivery_gateway = delivery_gateway
        self.approval_manager = approval_manager
        self.github_manager = github_manager
        self.deployment_manager = deployment_manager
        self.rollback_manager = rollback_manager
        self.deployment_policy = deployment_policy
        self.telegram_approval_interface = telegram_approval_interface

        logger.info(
            "[MasterDeliveryAuthorization] Initialized | "
            "gateway=%s | approval=%s | github=%s | deployment=%s | rollback=%s",
            bool(delivery_gateway),
            bool(approval_manager),
            bool(github_manager),
            bool(deployment_manager),
            bool(rollback_manager),
        )

    # ==================================================================
    # PRIMARY API
    # ==================================================================

    async def authorize(
        self,
        request: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
        operation: Optional[str] = None,
        session_id: str = "",
        user_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Evaluate and, when explicitly authorized, execute a protected
        delivery request.

        If authorization is missing, this method ALWAYS blocks.

        It never converts an unauthorized delivery request into a generic
        informational answer.
        """

        request_text = self._request_text(request)
        ctx = dict(context or {})

        resolved_operation = self.detect_operation(
            request_text,
            explicit_operation=operation,
        )

        if resolved_operation is None:
            return {
                "success": False,
                "blocked": True,
                "authorization_required": False,
                "operation": None,
                "request": request_text,
                "message": (
                    "No protected delivery operation could be identified "
                    "from this request."
                ),
                "version": self.VERSION,
            }

        authorization = self._authorization_state(
            request_text,
            ctx,
            operation=resolved_operation,
            session_id=session_id,
            user_id=user_id,
        )

        if not authorization["authorized"]:
            result = self._authorization_required_result(
                request_text,
                resolved_operation,
                authorization,
            )

            logger.warning(
                "[MasterDeliveryAuthorization] BLOCKED | operation=%s | "
                "explicit_master_authorization=%s",
                resolved_operation,
                authorization["explicit"],
            )

            return result

        logger.info(
            "[MasterDeliveryAuthorization] AUTHORIZED | operation=%s",
            resolved_operation,
        )

        return await self._execute_authorized_operation(
            request_text,
            resolved_operation,
            context=ctx,
            session_id=session_id,
            user_id=user_id,
            authorization=authorization,
            **kwargs,
        )

    async def execute(
        self,
        request: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
        operation: Optional[str] = None,
        session_id: str = "",
        user_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Compatibility alias for authorize().
        """

        return await self.authorize(
            request,
            context=context,
            operation=operation,
            session_id=session_id,
            user_id=user_id,
            **kwargs,
        )

    async def request_authorization(
        self,
        request: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
        operation: Optional[str] = None,
        session_id: str = "",
        user_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Return an authorization request without executing delivery.

        Useful when ARIA needs to tell Master exactly what protected action
        requires approval.
        """

        request_text = self._request_text(request)

        resolved_operation = self.detect_operation(
            request_text,
            explicit_operation=operation,
        )

        if resolved_operation is None:
            return {
                "success": False,
                "authorization_required": False,
                "operation": None,
                "request": request_text,
                "message": (
                    "No protected delivery operation was identified."
                ),
                "version": self.VERSION,
            }

        return self._authorization_required_result(
            request_text,
            resolved_operation,
            {
                "authorized": False,
                "explicit": False,
                "source": "authorization_request",
            },
        )

    # ==================================================================
    # OPERATION DETECTION
    # ==================================================================

    def detect_operation(
        self,
        request: Any,
        *,
        explicit_operation: Optional[str] = None,
    ) -> Optional[str]:
        """
        Deterministically identify a protected delivery operation.
        """

        if explicit_operation:
            normalized = self._normalize_operation(
                explicit_operation
            )

            if normalized in self.PROTECTED_OPERATIONS:
                return normalized

        text = self._request_text(request).lower()

        # --------------------------------------------------------------
        # Rollback has highest priority because a rollback request may
        # also contain deployment terminology.
        # --------------------------------------------------------------

        rollback_markers = (
            "rollback",
            "roll back",
            "revert deployment",
            "restore previous deployment",
            "restore the previous deployment",
            "rollback the deployment",
        )

        if any(
            marker in text
            for marker in rollback_markers
        ):
            return "rollback"

        # --------------------------------------------------------------
        # Merge
        # --------------------------------------------------------------

        merge_patterns = (
            r"\bmerge\b.*\b(branch|pull request|pr)\b",
            r"\bmerge\b.*\bgithub\b",
            r"\bmerge\b.*\binto\b",
        )

        if any(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            for pattern in merge_patterns
        ):
            return "github_merge"

        # --------------------------------------------------------------
        # Deployment
        # --------------------------------------------------------------

        deployment_markers = (
            "deploy",
            "deployment",
            "release to production",
            "release the application",
            "ship to production",
            "publish the application",
            "push to production",
        )

        if any(
            marker in text
            for marker in deployment_markers
        ):
            return "deployment"

        # --------------------------------------------------------------
        # GitHub push
        # --------------------------------------------------------------

        github_push_patterns = (
            r"\bpush\b.*\bgithub\b",
            r"\bgithub\b.*\bpush\b",
            r"\bpush\b.*\bremote\b",
            r"\bpush\b.*\borigin\b",
            r"\bsend\b.*\bgithub\b",
        )

        if any(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            for pattern in github_push_patterns
        ):
            return "github_push"

        return None

    # ==================================================================
    # AUTHORIZATION STATE
    # ==================================================================

    def _authorization_state(
        self,
        request: str,
        context: Mapping[str, Any],
        *,
        operation: str,
        session_id: str = "",
        user_id: str = "",
    ) -> Dict[str, Any]:
        """
        Determine whether the current request has explicit Master
        authorization.

        Important:

            "push this to GitHub"

        is NOT authorization.

        The request itself must not be interpreted as both the operation and
        its authorization.

        Explicit authorization must come from an authorization field or an
        approved request state supplied by the Master approval system.
        """

        explicit = False
        source = None
        authorization_id = None

        # --------------------------------------------------------------
        # 1. Canonical context fields
        # --------------------------------------------------------------

        explicit_fields = (
            "master_authorized",
            "master_authorization",
            "explicit_master_authorization",
            "delivery_authorized",
            "authorized_delivery",
            "authorization_granted",
        )

        for field in explicit_fields:
            if field not in context:
                continue

            value = context.get(field)

            if isinstance(value, Mapping):
                granted = value.get(
                    "authorized",
                    value.get(
                        "approved",
                        value.get(
                            "granted",
                            False,
                        ),
                    ),
                )

                if bool(granted):
                    explicit = True
                    source = field
                    authorization_id = (
                        value.get("authorization_id")
                        or value.get("approval_id")
                        or value.get("id")
                    )
                    break

            elif bool(value):
                explicit = True
                source = field
                break

        # --------------------------------------------------------------
        # 2. Authorization object
        # --------------------------------------------------------------

        if not explicit:
            authorization = context.get(
                "authorization"
            )

            if isinstance(
                authorization,
                Mapping,
            ):
                granted = bool(
                    authorization.get(
                        "authorized",
                        authorization.get(
                            "approved",
                            authorization.get(
                                "granted",
                                False,
                            ),
                        ),
                    )
                )

                if granted:
                    explicit = True
                    source = "authorization"
                    authorization_id = (
                        authorization.get(
                            "authorization_id"
                        )
                        or authorization.get(
                            "approval_id"
                        )
                        or authorization.get("id")
                    )

        # --------------------------------------------------------------
        # 3. Approved delivery request
        # --------------------------------------------------------------

        if not explicit:
            approved_request = context.get(
                "approved_delivery_request"
            )

            if isinstance(
                approved_request,
                Mapping,
            ):
                approved_operation = self._normalize_operation(
                    approved_request.get(
                        "operation",
                        "",
                    )
                )

                granted = bool(
                    approved_request.get(
                        "authorized",
                        approved_request.get(
                            "approved",
                            False,
                        ),
                    )
                )

                if (
                    granted
                    and (
                        not approved_operation
                        or approved_operation == operation
                    )
                ):
                    explicit = True
                    source = "approved_delivery_request"
                    authorization_id = (
                        approved_request.get(
                            "authorization_id"
                        )
                        or approved_request.get(
                            "approval_id"
                        )
                    )

        # --------------------------------------------------------------
        # 4. Context metadata
        # --------------------------------------------------------------

        metadata = context.get(
            "metadata"
        )

        if (
            not explicit
            and isinstance(
                metadata,
                Mapping,
            )
        ):
            metadata_authorized = metadata.get(
                "master_authorized"
            )

            if isinstance(
                metadata_authorized,
                Mapping,
            ):
                if bool(
                    metadata_authorized.get(
                        "authorized",
                        False,
                    )
                ):
                    explicit = True
                    source = "metadata"
                    authorization_id = (
                        metadata_authorized.get(
                            "authorization_id"
                        )
                        or metadata_authorized.get(
                            "approval_id"
                        )
                    )

            elif bool(metadata_authorized):
                explicit = True
                source = "metadata"

        # --------------------------------------------------------------
        # 5. Never infer authorization from natural language alone.
        # --------------------------------------------------------------

        return {
            "authorized": explicit,
            "explicit": explicit,
            "source": source,
            "authorization_id": authorization_id,
            "operation": operation,
            "session_id": session_id,
            "user_id": user_id,
            "authorization_required": True,
        }

    # ==================================================================
    # AUTHORIZED EXECUTION
    # ==================================================================

    async def _execute_authorized_operation(
        self,
        request: str,
        operation: str,
        *,
        context: Mapping[str, Any],
        session_id: str,
        user_id: str,
        authorization: Mapping[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Delegate the authorized operation to the existing delivery owner.
        """

        gateway = self.delivery_gateway

        if gateway is None:
            return {
                "success": False,
                "blocked": True,
                "authorization_required": True,
                "authorized": True,
                "operation": operation,
                "request": request,
                "message": (
                    "Master authorization was received, but the canonical "
                    "delivery gateway is unavailable. The operation was "
                    "not executed."
                ),
                "error": "delivery_gateway_unavailable",
                "version": self.VERSION,
            }

        gateway_method = self._find_gateway_method(
            gateway,
            operation,
        )

        if gateway_method is None:
            return {
                "success": False,
                "blocked": True,
                "authorization_required": True,
                "authorized": True,
                "operation": operation,
                "request": request,
                "message": (
                    "Master authorization was received, but the canonical "
                    "delivery gateway does not expose the required "
                    f"{operation} operation. Nothing was executed."
                ),
                "error": "delivery_operation_unavailable",
                "version": self.VERSION,
            }

        execution_context = dict(context)

        execution_context.update(
            {
                "master_authorized": True,
                "explicit_master_authorization": True,
                "delivery_authorized": True,
                "authorization": dict(
                    authorization
                ),
                "authorization_id": authorization.get(
                    "authorization_id"
                ),
                "operation": operation,
                "session_id": session_id,
                "user_id": user_id,
            }
        )

        # --------------------------------------------------------------
        # Hard safety properties are always supplied to the underlying
        # gateway. A caller cannot turn production direct write on by
        # putting a conflicting value into context.
        # --------------------------------------------------------------

        execution_context[
            "github_push_requires_authorization"
        ] = True

        execution_context[
            "merge_requires_authorization"
        ] = True

        execution_context[
            "deployment_requires_authorization"
        ] = True

        execution_context[
            "rollback_requires_authorization"
        ] = True

        execution_context[
            "production_direct_write"
        ] = False

        execution_context[
            "automatic_delivery"
        ] = False

        try:
            result = await self._call_compatible(
                gateway_method,
                request=request,
                query=request,
                context=execution_context,
                operation=operation,
                session_id=session_id,
                user_id=user_id,
                authorization_id=authorization.get(
                    "authorization_id"
                ),
                master_authorized=True,
                **kwargs,
            )

            normalized = self._normalize_result(
                result,
                request=request,
                operation=operation,
            )

            normalized[
                "authorization_required"
            ] = True

            normalized[
                "authorized"
            ] = True

            normalized[
                "authorization_id"
            ] = authorization.get(
                "authorization_id"
            )

            normalized[
                "production_direct_write"
            ] = False

            normalized[
                "automatic_delivery"
            ] = False

            normalized[
                "version"
            ] = self.VERSION

            return normalized

        except Exception as exc:
            logger.exception(
                "[MasterDeliveryAuthorization] Authorized delivery "
                "operation failed: %s",
                operation,
            )

            return {
                "success": False,
                "blocked": False,
                "authorized": True,
                "authorization_required": True,
                "operation": operation,
                "request": request,
                "error": str(exc),
                "message": (
                    "The authorized delivery operation failed. "
                    "No fallback delivery path was used."
                ),
                "version": self.VERSION,
            }

    # ==================================================================
    # GATEWAY METHOD RESOLUTION
    # ==================================================================

    def _find_gateway_method(
        self,
        gateway: Any,
        operation: str,
    ) -> Optional[Any]:
        """
        Resolve the existing delivery gateway method.

        Generic execute() is used only as a compatibility fallback.
        """

        method_candidates = {
            "github_push": (
                "github_push",
                "push",
                "push_to_github",
                "execute_github_push",
            ),
            "github_merge": (
                "github_merge",
                "merge",
                "merge_to_github",
                "execute_merge",
            ),
            "deployment": (
                "deploy",
                "deployment",
                "execute_deployment",
            ),
            "rollback": (
                "rollback",
                "execute_rollback",
            ),
        }

        for method_name in method_candidates.get(
            operation,
            (),
        ):
            method = getattr(
                gateway,
                method_name,
                None,
            )

            if callable(method):
                return method

        generic_execute = getattr(
            gateway,
            "execute",
            None,
        )

        if callable(generic_execute):
            return generic_execute

        return None

    # ==================================================================
    # BLOCKED AUTHORIZATION RESPONSE
    # ==================================================================

    def _authorization_required_result(
        self,
        request: str,
        operation: str,
        authorization: Mapping[str, Any],
    ) -> Dict[str, Any]:
        operation_label = {
            "github_push": "GitHub push",
            "github_merge": "GitHub merge",
            "deployment": "deployment",
            "rollback": "rollback",
        }.get(
            operation,
            operation,
        )

        message = (
            f"{operation_label} requires explicit Master authorization. "
            "I have not executed the operation, modified the remote "
            "repository, deployed anything, or performed a rollback. "
            "Approve this specific delivery action through the Master "
            "authorization flow before I execute it."
        )

        return {
            "success": True,
            "blocked": True,
            "execution_blocked": True,
            "authorization_required": True,
            "authorized": False,
            "operation": operation,
            "request": request,
            "message": message,
            "response": message,
            "authorization": {
                "required": True,
                "granted": False,
                "explicit": bool(
                    authorization.get(
                        "explicit",
                        False,
                    )
                ),
                "source": authorization.get(
                    "source"
                ),
                "authorization_id": authorization.get(
                    "authorization_id"
                ),
            },
            "safety": {
                "github_push_requires_authorization": True,
                "merge_requires_authorization": True,
                "deployment_requires_authorization": True,
                "rollback_requires_authorization": True,
                "production_direct_write": False,
                "automatic_delivery": False,
            },
            "version": self.VERSION,
        }

    # ==================================================================
    # HEALTH / CAPABILITIES
    # ==================================================================

    def health(self) -> Dict[str, Any]:
        """
        Deterministic structural health check.
        """

        gateway_available = (
            self.delivery_gateway is not None
        )

        return {
            "healthy": True,
            "version": self.VERSION,
            "canonical": True,
            "delivery_gateway_available": gateway_available,
            "approval_manager_available": (
                self.approval_manager is not None
            ),
            "github_manager_available": (
                self.github_manager is not None
            ),
            "deployment_manager_available": (
                self.deployment_manager is not None
            ),
            "rollback_manager_available": (
                self.rollback_manager is not None
            ),
            "telegram_approval_interface_available": (
                self.telegram_approval_interface is not None
            ),
            "github_push_requires_authorization": True,
            "merge_requires_authorization": True,
            "deployment_requires_authorization": True,
            "rollback_requires_authorization": True,
            "production_direct_write": False,
            "automatic_delivery": False,
            "fail_closed": True,
        }

    def capabilities(self) -> Dict[str, Any]:
        return {
            "authorize": True,
            "request_authorization": True,
            "detect_operation": True,
            "github_push": True,
            "github_merge": True,
            "deployment": True,
            "rollback": True,
            "github_push_requires_authorization": True,
            "merge_requires_authorization": True,
            "deployment_requires_authorization": True,
            "rollback_requires_authorization": True,
            "production_direct_write": False,
            "automatic_delivery": False,
            "fail_closed": True,
            "generic_llm_fallback": False,
        }

    # ==================================================================
    # COMPATIBILITY ALIASES
    # ==================================================================

    async def gate(
        self,
        request: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
        operation: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Compatibility alias for authorize().
        """

        return await self.authorize(
            request,
            context=context,
            operation=operation,
            **kwargs,
        )

    async def check(
        self,
        request: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
        operation: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Read-only authorization check.

        IMPORTANT:
            This never executes delivery.
        """

        request_text = self._request_text(request)

        resolved_operation = self.detect_operation(
            request_text,
            explicit_operation=operation,
        )

        if resolved_operation is None:
            return {
                "success": True,
                "authorization_required": False,
                "authorized": False,
                "operation": None,
                "version": self.VERSION,
            }

        authorization = self._authorization_state(
            request_text,
            dict(context or {}),
            operation=resolved_operation,
        )

        return {
            "success": True,
            "authorization_required": True,
            "authorized": authorization["authorized"],
            "operation": resolved_operation,
            "authorization_id": authorization.get(
                "authorization_id"
            ),
            "version": self.VERSION,
        }

    # ==================================================================
    # HELPERS
    # ==================================================================

    async def _call_compatible(
        self,
        method: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Call an existing delivery method without assuming one exact
        historical signature.
        """

        if not callable(method):
            raise TypeError(
                "Delivery target is not callable."
            )

        try:
            signature = inspect.signature(method)
        except (
            TypeError,
            ValueError,
        ):
            result = method()

            if inspect.isawaitable(result):
                return await result

            return result

        parameters = signature.parameters

        accepts_kwargs = any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        if accepts_kwargs:
            selected = dict(kwargs)

        else:
            selected = {
                key: value
                for key, value in kwargs.items()
                if key in parameters
            }

        positional_request = None

        for name in (
            "request",
            "query",
            "instruction",
            "operation",
        ):
            if (
                name in selected
                and name in parameters
            ):
                positional_request = selected.pop(
                    name
                )
                break

        if positional_request is not None:
            result = method(
                positional_request,
                **selected,
            )
        else:
            result = method(
                **selected
            )

        if inspect.isawaitable(result):
            return await result

        return result

    @staticmethod
    def _normalize_result(
        result: Any,
        *,
        request: str,
        operation: str,
    ) -> Dict[str, Any]:
        if isinstance(
            result,
            Mapping,
        ):
            normalized = dict(result)

        elif hasattr(
            result,
            "to_dict",
        ):
            try:
                converted = result.to_dict()

                if isinstance(
                    converted,
                    Mapping,
                ):
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

        normalized.setdefault(
            "success",
            True,
        )

        normalized.setdefault(
            "request",
            request,
        )

        normalized.setdefault(
            "operation",
            operation,
        )

        normalized.setdefault(
            "canonical",
            True,
        )

        return normalized

    @staticmethod
    def _normalize_operation(
        operation: Any,
    ) -> str:
        text = str(
            operation or ""
        ).strip().lower()

        aliases = {
            "push": "github_push",
            "github": "github_push",
            "github push": "github_push",
            "push_to_github": "github_push",
            "github_push": "github_push",

            "merge": "github_merge",
            "github merge": "github_merge",
            "github_merge": "github_merge",
            "pull_request_merge": "github_merge",

            "deploy": "deployment",
            "deployment": "deployment",
            "release": "deployment",
            "production_deployment": "deployment",

            "rollback": "rollback",
            "roll_back": "rollback",
            "revert_deployment": "rollback",
        }

        return aliases.get(
            text,
            text,
        )

    @staticmethod
    def _request_text(
        request: Any,
    ) -> str:
        if isinstance(
            request,
            str,
        ):
            return request.strip()

        if isinstance(
            request,
            Mapping,
        ):
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
                    return str(
                        value
                    ).strip()

            return str(
                request
            ).strip()

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
                return str(
                    value
                ).strip()

        return str(
            request or ""
        ).strip()


# ======================================================================
# Compatibility aliases
# ======================================================================

MasterDeliveryAuthorizationGateway = MasterDeliveryAuthorization
DeliveryAuthorizationGateway = MasterDeliveryAuthorization


__all__ = [
    "MasterDeliveryAuthorization",
    "MasterDeliveryAuthorizationGateway",
    "DeliveryAuthorizationGateway",
]