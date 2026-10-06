"""
ARIA Engineering Request Router
================================

Canonical routing boundary for engineering-related requests.

Routing order:

    Master Request
         |
         v
    Delivery Authorization
         |
         +---- GitHub push / merge
         +---- Deployment
         +---- Rollback
         |
         v
    Engineering Request Router
         |
         +---- Read-only / inspection
         |         -> Readiness Gateway
         |
         +---- Plan-only
         |         -> Planning path
         |
         +---- Autonomous execution
                   -> AutonomousEngineeringLifecycle

Important:

    This module does NOT implement engineering itself.

    It does NOT:
        - write source files
        - execute shell commands
        - commit Git
        - push GitHub
        - deploy
        - rollback
        - call an LLM for routing

    It only selects the already-existing canonical owner.

Safety is fail-closed.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Dict, Mapping, Optional


logger = logging.getLogger("aria.engineering_request_router")


class EngineeringRequestRouter:
    """
    Canonical engineering routing gateway.

    The router is intentionally deterministic.

    It prevents the legacy CognitiveCore/LLM pipeline from competing with
    the authoritative engineering lifecycle.
    """

    VERSION = "ARIA-ENGINEERING-REQUEST-ROUTER-20261006"

    # ------------------------------------------------------------------
    # Strong engineering indicators
    # ------------------------------------------------------------------

    ENGINEERING_MARKERS = (
        "modify the code",
        "modify code",
        "change the code",
        "change code",
        "edit the code",
        "edit code",
        "update the code",
        "update code",
        "fix the code",
        "fix code",
        "write code",
        "create code",
        "implement",
        "implementation",
        "develop",
        "development",
        "build the feature",
        "build a feature",
        "add a feature",
        "add this feature",
        "add capability",
        "add a capability",
        "add functionality",
        "add functionality to aria",
        "change the architecture",
        "modify the architecture",
        "refactor",
        "refactoring",
        "debug",
        "debugging",
        "fix this bug",
        "fix the bug",
        "fix the issue",
        "fix this issue",
        "repair the code",
        "repair code",
        "engineer",
        "engineering",
        "autonomous engineering",
        "software development",
        "software engineering",
        "repository architecture",
        "codebase",
        "repo",
        "repository",
    )

    REPOSITORY_MARKERS = (
        "repository",
        "repo",
        "codebase",
        "code base",
        "project files",
        "project structure",
        "source tree",
        "file tree",
        "architecture",
        "dependency graph",
        "dependencies",
        "existing implementation",
        "existing code",
        "current implementation",
        "current code",
        "inspect the project",
        "inspect the repository",
        "analyze the repository",
        "analyse the repository",
    )

    PLAN_MARKERS = (
        "plan",
        "planning",
        "implementation plan",
        "architecture plan",
        "design plan",
        "roadmap",
        "steps",
        "stages",
        "how would you implement",
        "how should we implement",
        "what files would",
        "which files would",
        "what needs to change",
        "what would need to change",
        "before modifying",
        "before implementation",
        "first understand",
        "first analyze",
        "first inspect",
    )

    READ_ONLY_MARKERS = (
        "do not modify",
        "don't modify",
        "do not change",
        "don't change",
        "do not edit",
        "don't edit",
        "do not create",
        "don't create",
        "do not delete",
        "don't delete",
        "do not execute",
        "don't execute",
        "do not run",
        "don't run",
        "do not commit",
        "don't commit",
        "do not push",
        "don't push",
        "do not deploy",
        "don't deploy",
        "only inspect",
        "only analyze",
        "only analyse",
        "read only",
        "read-only",
        "without modifying",
        "without changing",
        "without executing",
        "without making changes",
        "no changes",
        "nothing should be modified",
        "nothing should change",
    )

    DELIVERY_MARKERS = (
        "github",
        "git hub",
        "deploy",
        "deployment",
        "rollback",
        "roll back",
        "merge",
        "pull request",
        "push",
        "production",
        "release",
    )

    # ==================================================================
    # CONSTRUCTION
    # ==================================================================

    def __init__(
        self,
        runtime: Any = None,
        *,
        lifecycle: Any = None,
        autonomous_engineering_lifecycle: Any = None,
        readiness_gateway: Any = None,
        delivery_authorization: Any = None,
        master_delivery_authorization: Any = None,
        execution_mode: Any = None,
        repository_intelligence: Any = None,
        capability_selector: Any = None,
    ) -> None:
        """
        Parameters intentionally support both the new canonical names and
        older bootstrap names.

        No component is instantiated here.

        Bootstrap remains the owner of dependency construction.
        """

        self.runtime = runtime

        self.lifecycle = (
            autonomous_engineering_lifecycle
            or lifecycle
        )

        self.readiness_gateway = readiness_gateway

        self.delivery_authorization = (
            master_delivery_authorization
            or delivery_authorization
        )

        self.execution_mode = execution_mode
        self.repository_intelligence = repository_intelligence
        self.capability_selector = capability_selector

        logger.info(
            "[EngineeringRequestRouter] Initialized | "
            "lifecycle=%s | readiness=%s | delivery=%s | "
            "execution_mode=%s | repository_intelligence=%s",
            bool(self.lifecycle),
            bool(self.readiness_gateway),
            bool(self.delivery_authorization),
            bool(self.execution_mode),
            bool(self.repository_intelligence),
        )

    # ==================================================================
    # PRIMARY ROUTE
    # ==================================================================

    async def route(
        self,
        query: Any,
        *,
        session_id: str = "",
        user_id: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
        intent: Any = None,
        decision: Any = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Route one request.

        Returns:

            None
                Request is not an engineering/delivery request.

            dict
                Canonical route was selected and CognitiveCore must honor
                the result instead of continuing into a competing pipeline.
        """

        request = self._request_text(query)

        if not request:
            return None

        merged_context = dict(context or {})
        merged_context.update(dict(metadata or {}))

        merged_context.setdefault(
            "query",
            request,
        )

        merged_context.setdefault(
            "session_id",
            session_id,
        )

        merged_context.setdefault(
            "user_id",
            user_id,
        )

        if intent is not None:
            merged_context.setdefault(
                "intent",
                intent,
            )

        if decision is not None:
            merged_context.setdefault(
                "decision",
                decision,
            )

        # ==============================================================
        # 1. DELIVERY HAS ABSOLUTE PRIORITY
        # ==============================================================

        delivery_operation = self._detect_delivery_operation(
            request
        )

        if delivery_operation is not None:
            return await self._route_delivery(
                request,
                operation=delivery_operation,
                context=merged_context,
                session_id=session_id,
                user_id=user_id,
                **kwargs,
            )

        # ==============================================================
        # 2. DETERMINE WHETHER THIS IS ENGINEERING
        # ==============================================================

        classification = self.classify(
            request,
            context=merged_context,
        )

        if not classification["engineering"]:
            return None

        # ==============================================================
        # 3. RESOLVE EXECUTION MODE
        # ==============================================================

        mode = self._resolve_execution_mode(
            request,
            context=merged_context,
        )

        if mode is not None:
            mode_name = self._mode_name(mode)
        else:
            mode_name = self._fallback_mode_name(
                request,
                classification,
            )

        logger.info(
            "[EngineeringRequestRouter] Route selected | "
            "mode=%s | engineering=%s | read_only=%s | plan_only=%s",
            mode_name,
            classification["engineering"],
            classification["read_only"],
            classification["plan_only"],
        )

        # ==============================================================
        # 4. READ-ONLY / INSPECTION
        # ==============================================================

        if (
            classification["read_only"]
            or mode_name in {
                "inspect_only",
                "read_only",
                "inspection",
            }
        ):
            return await self._route_read_only(
                request,
                context=merged_context,
                session_id=session_id,
                user_id=user_id,
                classification=classification,
                **kwargs,
            )

        # ==============================================================
        # 5. PLAN-ONLY
        # ==============================================================

        if (
            classification["plan_only"]
            or mode_name == "plan_only"
        ):
            return await self._route_plan_only(
                request,
                context=merged_context,
                session_id=session_id,
                user_id=user_id,
                classification=classification,
                **kwargs,
            )

        # ==============================================================
        # 6. EXECUTABLE ENGINEERING
        # ==============================================================

        return await self._route_execution(
            request,
            context=merged_context,
            session_id=session_id,
            user_id=user_id,
            classification=classification,
            **kwargs,
        )

    # ==================================================================
    # CLASSIFICATION
    # ==================================================================

    def classify(
        self,
        query: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Deterministically classify engineering intent.

        This function does not execute anything.
        """

        request = self._request_text(query)
        text = self._normalized(request)

        read_only = self._contains_any(
            text,
            self.READ_ONLY_MARKERS,
        )

        explicit_plan = self._contains_any(
            text,
            self.PLAN_MARKERS,
        )

        engineering = self._contains_any(
            text,
            self.ENGINEERING_MARKERS,
        )

        repository = self._contains_any(
            text,
            self.REPOSITORY_MARKERS,
        )

        delivery = self._detect_delivery_operation(
            request
        )

        # Repository architecture/inspection requests are engineering
        # requests even when the user does not explicitly say "engineering".
        if repository:
            engineering = True

        # Planning language combined with an implementation target is
        # engineering planning.
        if explicit_plan and (
            engineering
            or repository
        ):
            engineering = True

        # A direct coding request is always engineering.
        if self._looks_like_code_change(
            text
        ):
            engineering = True

        # Explicit no-action instructions dominate execution.
        plan_only = bool(
            engineering
            and explicit_plan
            and not self._contains_execution_request(
                text
            )
        )

        # Requests explicitly saying "do not modify" are inspection unless
        # they are asking for a pure implementation plan.
        if read_only:
            plan_only = bool(
                explicit_plan
                and not self._contains_execution_request(
                    text
                )
            )

        return {
            "engineering": bool(engineering),
            "repository": bool(repository),
            "delivery": delivery is not None,
            "delivery_operation": delivery,
            "read_only": bool(read_only),
            "plan_only": bool(plan_only),
            "execution_requested": bool(
                self._contains_execution_request(
                    text
                )
            ),
            "mutation_requested": bool(
                self._contains_mutation_request(
                    text
                )
            ),
            "version": self.VERSION,
        }

    # ==================================================================
    # DELIVERY
    # ==================================================================

    async def _route_delivery(
        self,
        request: str,
        *,
        operation: str,
        context: Mapping[str, Any],
        session_id: str,
        user_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Route delivery operations through MasterDeliveryAuthorization.

        This route is always handled.

        If authorization is absent, the result is returned immediately and
        no generic LLM path is allowed to continue.
        """

        if self.delivery_authorization is None:
            message = (
                f"{self._operation_label(operation)} requires explicit "
                "Master authorization, but the canonical authorization "
                "gateway is unavailable. Nothing was executed."
            )

            return {
                "handled": True,
                "success": False,
                "blocked": True,
                "execution_blocked": True,
                "authorization_required": True,
                "authorized": False,
                "route": "master_delivery_authorization",
                "operation": operation,
                "request": request,
                "message": message,
                "response": message,
                "canonical": True,
                "version": self.VERSION,
            }

        try:
            result = await self._call_compatible(
                self.delivery_authorization.authorize,
                request=request,
                context=dict(context),
                operation=operation,
                session_id=session_id,
                user_id=user_id,
                **kwargs,
            )

        except Exception as exc:
            logger.exception(
                "[EngineeringRequestRouter] Delivery authorization failed."
            )

            return {
                "handled": True,
                "success": False,
                "blocked": True,
                "authorization_required": True,
                "authorized": False,
                "route": "master_delivery_authorization",
                "operation": operation,
                "request": request,
                "message": (
                    "The canonical Master delivery authorization gateway "
                    "failed. No delivery fallback was used."
                ),
                "error": str(exc),
                "canonical": True,
                "version": self.VERSION,
            }

        return {
            "handled": True,
            "route": "master_delivery_authorization",
            "operation": operation,
            "result": result,
            "success": self._result_success(
                result
            ),
            "canonical": True,
            "version": self.VERSION,
        }

    # ==================================================================
    # READ-ONLY
    # ==================================================================

    async def _route_read_only(
        self,
        request: str,
        *,
        context: Mapping[str, Any],
        session_id: str,
        user_id: str,
        classification: Mapping[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Route read-only engineering requests to the readiness gateway.

        Never calls the autonomous engineering lifecycle.
        """

        if self.readiness_gateway is None:
            message = (
                "This engineering request is read-only. The canonical "
                "readiness gateway is unavailable, so no implementation "
                "or mutation was attempted."
            )

            return {
                "handled": True,
                "success": False,
                "blocked": True,
                "execution_blocked": True,
                "requires_readiness_gateway": True,
                "route": "phase1_readiness_gateway",
                "request": request,
                "message": message,
                "response": message,
                "canonical": True,
                "version": self.VERSION,
            }

        try:
            result = await self._invoke_readiness(
                request,
                context=context,
                session_id=session_id,
                user_id=user_id,
                **kwargs,
            )

        except Exception as exc:
            logger.exception(
                "[EngineeringRequestRouter] Readiness gateway failed."
            )

            message = (
                "The read-only engineering readiness inspection failed. "
                "No implementation or mutation was attempted."
            )

            return {
                "handled": True,
                "success": False,
                "blocked": True,
                "execution_blocked": True,
                "requires_readiness_gateway": True,
                "route": "phase1_readiness_gateway",
                "request": request,
                "message": message,
                "response": message,
                "error": str(exc),
                "canonical": True,
                "version": self.VERSION,
            }

        return {
            "handled": True,
            "success": True,
            "blocked": False,
            "execution_blocked": True,
            "requires_readiness_gateway": True,
            "route": "phase1_readiness_gateway",
            "request": request,
            "result": result,
            "message": self._readiness_message(
                result
            ),
            "canonical": True,
            "version": self.VERSION,
        }

    # ==================================================================
    # PLAN ONLY
    # ==================================================================

    async def _route_plan_only(
        self,
        request: str,
        *,
        context: Mapping[str, Any],
        session_id: str,
        user_id: str,
        classification: Mapping[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Handle plan-only requests without entering implementation.

        The router first tries the existing planner exposed by the runtime.
        It does not create a new planning engine.
        """

        plan_context = dict(context)

        plan_context.update(
            {
                "plan_only": True,
                "read_only": True,
                "execution_allowed": False,
                "mutation_allowed": False,
                "commit_allowed": False,
                "github_push_allowed": False,
                "deployment_allowed": False,
                "rollback_allowed": False,
                "engineering_plan_request": True,
            }
        )

        planner = self._runtime_component(
            "planner"
        )

        if planner is not None:
            try:
                result = await self._invoke_planner(
                    planner,
                    request,
                    context=plan_context,
                    session_id=session_id,
                    user_id=user_id,
                    **kwargs,
                )

                return {
                    "handled": True,
                    "success": True,
                    "blocked": False,
                    "execution_blocked": True,
                    "plan_only": True,
                    "route": "planner",
                    "request": request,
                    "result": result,
                    "message": self._plan_message(
                        result
                    ),
                    "canonical": True,
                    "version": self.VERSION,
                }

            except Exception as exc:
                logger.warning(
                    "[EngineeringRequestRouter] Planner failed; "
                    "returning deterministic plan envelope: %s",
                    exc,
                )

        # If there is no planner available, still handle the request.
        # This is preferable to accidentally falling through into execution.
        return {
            "handled": True,
            "success": True,
            "blocked": False,
            "execution_blocked": True,
            "plan_only": True,
            "route": "engineering_plan",
            "request": request,
            "message": (
                "This request is plan-only. No files were modified, no "
                "code was executed, no commit was created, no GitHub push "
                "was performed, and nothing was deployed."
            ),
            "planning_context": plan_context,
            "canonical": True,
            "version": self.VERSION,
        }

    # ==================================================================
    # EXECUTION
    # ==================================================================

    async def _route_execution(
        self,
        request: str,
        *,
        context: Mapping[str, Any],
        session_id: str,
        user_id: str,
        classification: Mapping[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Route executable engineering work to the one canonical lifecycle.
        """

        if self.lifecycle is None:
            message = (
                "The canonical autonomous engineering lifecycle is "
                "unavailable. No legacy engineering fallback was used."
            )

            return {
                "handled": True,
                "success": False,
                "blocked": True,
                "execution_blocked": True,
                "route": "autonomous_engineering_lifecycle",
                "request": request,
                "message": message,
                "response": message,
                "canonical": True,
                "version": self.VERSION,
            }

        execution_context = dict(context)

        execution_context.update(
            {
                "engineering_request": True,
                "autonomous_engineering": True,
                "execution_allowed": True,
                "read_only": False,
                "plan_only": False,
                "canonical_engineering_route": True,
                "github_push_requires_authorization": True,
                "deployment_requires_authorization": True,
                "rollback_requires_authorization": True,
                "production_direct_write": False,
                "automatic_delivery": False,
            }
        )

        # --------------------------------------------------------------
        # If an execution-mode selector is present, honor it again at the
        # final routing boundary. This protects against a malformed or
        # stale upstream decision.
        # --------------------------------------------------------------

        mode = self._resolve_execution_mode(
            request,
            context=execution_context,
        )

        if mode is not None:
            allows_execution = self._mode_allows_execution(
                mode
            )

            if not allows_execution:
                return {
                    "handled": True,
                    "success": True,
                    "blocked": True,
                    "execution_blocked": True,
                    "route": "engineering_execution_mode",
                    "request": request,
                    "message": (
                        "The engineering execution mode does not permit "
                        "mutation for this request. No engineering "
                        "execution was started."
                    ),
                    "execution_mode": self._mode_dict(
                        mode
                    ),
                    "canonical": True,
                    "version": self.VERSION,
                }

        try:
            result = await self._call_compatible(
                self.lifecycle.develop,
                request=request,
                context=execution_context,
                session_id=session_id,
                user_id=user_id,
                **kwargs,
            )

        except Exception as exc:
            logger.exception(
                "[EngineeringRequestRouter] Autonomous engineering "
                "lifecycle failed."
            )

            return {
                "handled": True,
                "success": False,
                "blocked": False,
                "route": "autonomous_engineering_lifecycle",
                "request": request,
                "message": (
                    "The canonical autonomous engineering lifecycle "
                    "failed. No legacy engineering fallback was used."
                ),
                "error": str(exc),
                "canonical": True,
                "version": self.VERSION,
            }

        return {
            "handled": True,
            "route": "autonomous_engineering_lifecycle",
            "request": request,
            "result": result,
            "success": self._result_success(
                result
            ),
            "canonical": True,
            "version": self.VERSION,
        }

    # ==================================================================
    # EXECUTION MODE
    # ==================================================================

    def _resolve_execution_mode(
        self,
        request: str,
        *,
        context: Mapping[str, Any],
    ) -> Any:
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
                return method(
                    request,
                    context=context,
                )

            except TypeError:
                try:
                    return method(
                        request
                    )
                except Exception:
                    continue

            except Exception as exc:
                logger.warning(
                    "[EngineeringRequestRouter] "
                    "Execution mode selection failed: %s",
                    exc,
                )
                return None

        return None

    @staticmethod
    def _mode_name(
        mode: Any,
    ) -> str:
        if mode is None:
            return ""

        if isinstance(
            mode,
            Mapping,
        ):
            return str(
                mode.get(
                    "mode",
                    mode.get(
                        "name",
                        "",
                    ),
                )
                or ""
            ).strip().lower()

        return str(
            getattr(
                mode,
                "mode",
                getattr(
                    mode,
                    "name",
                    "",
                ),
            )
            or ""
        ).strip().lower()

    @staticmethod
    def _mode_allows_execution(
        mode: Any,
    ) -> bool:
        if mode is None:
            return True

        if isinstance(
            mode,
            Mapping,
        ):
            return bool(
                mode.get(
                    "execution_allowed",
                    False,
                )
            )

        return bool(
            getattr(
                mode,
                "execution_allowed",
                False,
            )
        )

    @staticmethod
    def _mode_dict(
        mode: Any,
    ) -> Dict[str, Any]:
        if mode is None:
            return {}

        if isinstance(
            mode,
            Mapping,
        ):
            return dict(
                mode
            )

        if hasattr(
            mode,
            "to_dict",
        ):
            try:
                result = mode.to_dict()

                if isinstance(
                    result,
                    Mapping,
                ):
                    return dict(
                        result
                    )
            except Exception:
                pass

        result = {}

        for field in (
            "mode",
            "execution_allowed",
            "read_only",
            "plan_only",
            "mutation_allowed",
            "commit_allowed",
            "github_push_allowed",
            "deployment_allowed",
            "rollback_allowed",
            "authorization_required",
            "reason",
        ):
            if hasattr(
                mode,
                field,
            ):
                result[field] = getattr(
                    mode,
                    field,
                )

        return result

    # ==================================================================
    # READINESS
    # ==================================================================

    async def _invoke_readiness(
        self,
        request: str,
        *,
        context: Mapping[str, Any],
        session_id: str,
        user_id: str,
        **kwargs: Any,
    ) -> Any:
        gateway = self.readiness_gateway

        for method_name in (
            "inspect",
            "check",
            "readiness",
            "assess",
            "validate",
        ):
            method = getattr(
                gateway,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                result = await self._call_compatible(
                    method,
                    request=request,
                    query=request,
                    context=dict(
                        context
                    ),
                    session_id=session_id,
                    user_id=user_id,
                    **kwargs,
                )

                return result

            except TypeError:
                continue

        raise RuntimeError(
            "The readiness gateway exposes no supported inspection method."
        )

    # ==================================================================
    # PLANNING
    # ==================================================================

    async def _invoke_planner(
        self,
        planner: Any,
        request: str,
        *,
        context: Mapping[str, Any],
        session_id: str,
        user_id: str,
        **kwargs: Any,
    ) -> Any:
        for method_name in (
            "plan",
            "create_plan",
            "build_plan",
            "generate_plan",
        ):
            method = getattr(
                planner,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            return await self._call_compatible(
                method,
                request=request,
                query=request,
                context=dict(
                    context
                ),
                session_id=session_id,
                user_id=user_id,
                **kwargs,
            )

        raise RuntimeError(
            "Planner exposes no supported planning method."
        )

    # ==================================================================
    # RUNTIME COMPONENT ACCESS
    # ==================================================================

    def _runtime_component(
        self,
        name: str,
    ) -> Any:
        runtime = self.runtime

        if runtime is None:
            return None

        try:
            getter = getattr(
                runtime,
                "get",
                None,
            )

            if callable(
                getter
            ):
                value = getter(
                    name
                )

                if value is not None:
                    return value

        except Exception:
            pass

        if isinstance(
            runtime,
            Mapping,
        ):
            return runtime.get(
                name
            )

        return getattr(
            runtime,
            name,
            None,
        )

    # ==================================================================
    # COMPATIBLE CALLING
    # ==================================================================

    async def _call_compatible(
        self,
        method: Any,
        **kwargs: Any,
    ) -> Any:
        if not callable(
            method
        ):
            raise TypeError(
                "Target method is not callable."
            )

        try:
            signature = inspect.signature(
                method
            )
        except (
            TypeError,
            ValueError,
        ):
            result = method()

            if inspect.isawaitable(
                result
            ):
                return await result

            return result

        parameters = signature.parameters

        accepts_kwargs = any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        if accepts_kwargs:
            selected = dict(
                kwargs
            )
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
            "goal",
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

        if inspect.isawaitable(
            result
        ):
            return await result

        return result

    # ==================================================================
    # HELPERS
    # ==================================================================

    @staticmethod
    def _request_text(
        query: Any,
    ) -> str:
        if isinstance(
            query,
            str,
        ):
            return query.strip()

        if isinstance(
            query,
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
                value = query.get(
                    key
                )

                if value is not None:
                    return str(
                        value
                    ).strip()

            return str(
                query
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
                query,
                attribute,
                None,
            )

            if value is not None:
                return str(
                    value
                ).strip()

        return str(
            query or ""
        ).strip()

    @staticmethod
    def _normalized(
        value: str,
    ) -> str:
        return re.sub(
            r"\s+",
            " ",
            str(
                value or ""
            ).strip().lower(),
        )

    @staticmethod
    def _contains_any(
        text: str,
        markers: Any,
    ) -> bool:
        return any(
            marker in text
            for marker in markers
        )

    def _looks_like_code_change(
        self,
        text: str,
    ) -> bool:
        code_patterns = (
            r"\bwrite\b.*\bpython\b",
            r"\bwrite\b.*\bjavascript\b",
            r"\bwrite\b.*\btypescript\b",
            r"\bwrite\b.*\bjava\b",
            r"\bwrite\b.*\bcode\b",
            r"\bcreate\b.*\bfile\b",
            r"\bmodify\b.*\bfile\b",
            r"\bedit\b.*\bfile\b",
            r"\breplace\b.*\bfile\b",
            r"\bchange\b.*\bfile\b",
            r"\bfix\b.*\bfile\b",
            r"\bimplement\b.*\bfeature\b",
            r"\bimplement\b.*\bfunction\b",
            r"\bimplement\b.*\bclass\b",
            r"\brefactor\b.*\bcode\b",
        )

        return any(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            for pattern in code_patterns
        )

    @staticmethod
    def _contains_execution_request(
        text: str,
    ) -> bool:
        execution_markers = (
            "implement it",
            "implement this",
            "implement the",
            "build it",
            "build this",
            "create it",
            "create this",
            "make the change",
            "make these changes",
            "modify it",
            "modify this",
            "change it",
            "change this",
            "fix it",
            "fix this",
            "execute the plan",
            "execute this",
            "go ahead",
            "proceed with implementation",
            "start implementation",
            "start coding",
            "write the files",
            "make the files",
            "apply the changes",
        )

        return any(
            marker in text
            for marker in execution_markers
        )

    @staticmethod
    def _contains_mutation_request(
        text: str,
    ) -> bool:
        mutation_markers = (
            "create",
            "modify",
            "change",
            "edit",
            "write",
            "replace",
            "delete",
            "remove",
            "rename",
            "move",
            "refactor",
            "implement",
            "fix",
            "repair",
            "update",
        )

        return any(
            re.search(
                rf"\b{re.escape(marker)}\b",
                text,
                flags=re.IGNORECASE,
            )
            for marker in mutation_markers
        )

    def _detect_delivery_operation(
        self,
        request: str,
    ) -> Optional[str]:
        text = self._normalized(
            request
        )

        # Rollback first.
        if any(
            marker in text
            for marker in (
                "rollback",
                "roll back",
                "revert deployment",
                "restore previous deployment",
            )
        ):
            return "rollback"

        # Merge.
        if (
            "merge" in text
            and (
                "github" in text
                or "branch" in text
                or "pull request" in text
                or "pr " in text
                or text.endswith("pr")
            )
        ):
            return "github_merge"

        # Deployment.
        if any(
            marker in text
            for marker in (
                "deploy",
                "deployment",
                "release to production",
                "ship to production",
                "push to production",
            )
        ):
            return "deployment"

        # GitHub push.
        if (
            (
                "push" in text
                and (
                    "github" in text
                    or "remote" in text
                    or "origin" in text
                )
            )
            or (
                "github" in text
                and "push" in text
            )
        ):
            return "github_push"

        return None

    @staticmethod
    def _operation_label(
        operation: str,
    ) -> str:
        return {
            "github_push": "GitHub push",
            "github_merge": "GitHub merge",
            "deployment": "Deployment",
            "rollback": "Rollback",
        }.get(
            operation,
            operation,
        )

    @staticmethod
    def _result_success(
        result: Any,
    ) -> bool:
        if isinstance(
            result,
            Mapping,
        ):
            return bool(
                result.get(
                    "success",
                    result.get(
                        "ok",
                        result.get(
                            "accepted",
                            True,
                        ),
                    ),
                )
            )

        value = getattr(
            result,
            "success",
            None,
        )

        if value is not None:
            return bool(
                value
            )

        return True

    @staticmethod
    def _readiness_message(
        result: Any,
    ) -> str:
        if isinstance(
            result,
            Mapping,
        ):
            return str(
                result.get(
                    "message",
                    result.get(
                        "summary",
                        result.get(
                            "response",
                            "Read-only engineering inspection completed.",
                        ),
                    ),
                )
            )

        return str(
            result
            or "Read-only engineering inspection completed."
        )

    @staticmethod
    def _plan_message(
        result: Any,
    ) -> str:
        if isinstance(
            result,
            Mapping,
        ):
            return str(
                result.get(
                    "message",
                    result.get(
                        "summary",
                        result.get(
                            "response",
                            "Implementation plan prepared without executing changes.",
                        ),
                    ),
                )
            )

        return str(
            result
            or "Implementation plan prepared without executing changes."
        )

    # ==================================================================
    # HEALTH / CAPABILITIES
    # ==================================================================

    def health(
        self,
    ) -> Dict[str, Any]:
        return {
            "healthy": True,
            "version": self.VERSION,
            "canonical": True,
            "lifecycle_available": (
                self.lifecycle is not None
            ),
            "readiness_gateway_available": (
                self.readiness_gateway is not None
            ),
            "delivery_authorization_available": (
                self.delivery_authorization is not None
            ),
            "execution_mode_available": (
                self.execution_mode is not None
            ),
            "repository_intelligence_available": (
                self.repository_intelligence is not None
            ),
            "legacy_engineering_fallback": False,
            "llm_routing": False,
        }

    def capabilities(
        self,
    ) -> Dict[str, Any]:
        return {
            "engineering": True,
            "repository_inspection": True,
            "plan_only": True,
            "read_only": True,
            "autonomous_execution": True,
            "delivery": True,
            "github_push_authorization": True,
            "deployment_authorization": True,
            "rollback_authorization": True,
            "legacy_engineering_fallback": False,
            "llm_router_fallback": False,
        }


__all__ = [
    "EngineeringRequestRouter",
]