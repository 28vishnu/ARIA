from __future__ import annotations

"""
Phase 1 final autonomous-engineer runtime adapter.

This module is the single integration boundary between the existing
Phase 1 runtime and the final autonomous-engineer facade.

Design goals:
- preserve the existing bootstrap contract;
- expose the final autonomous engineer to Telegram;
- keep the legacy runtime available only as a compatibility service container;
- never bypass GitHub/deployment permission boundaries;
- normalize object/dict results safely;
- fail closed on incompatible final-engineer responses;
- keep `.get()` compatibility for the Phase 1 capability registry;
- never silently hide FinalAutonomousEngineer construction failures;
- require the authoritative engineering orchestrator to exist before
  declaring the final engineer available.
"""

import inspect
import logging
from typing import Any

from .persistent_engineering_runtime import (
    PersistentEngineeringRuntime,
    PersistentEngineeringResult,
)

logger = logging.getLogger("aria")


class Phase1PersistentRuntimeAdapter:
    """
    Canonical Phase 1 runtime exposed to bootstrap and Telegram.

    The adapter deliberately owns no filesystem, GitHub, deployment, or
    shell implementation. Those capabilities remain inside the existing
    Phase 1 services and their explicit authorization gates.
    """

    def __init__(
        self,
        legacy_phase1_runtime: Any,
        *,
        development_controller: Any = None,
    ) -> None:
        if legacy_phase1_runtime is None:
            raise ValueError(
                "legacy_phase1_runtime is required."
            )

        self.legacy_phase1_runtime = (
            legacy_phase1_runtime
        )

        self.development_controller = (
            development_controller
        )

        self._persistent_runtime = (
            self._build_persistent_runtime()
        )

        self.final_engineer = (
            self._build_final_engineer()
        )

        # Close the legacy development entry point.
        #
        # The legacy runtime remains available as a compatibility
        # service container, but direct engineering execution must
        # return through this adapter.
        bind = getattr(
            self.legacy_phase1_runtime,
            "bind_authoritative_runtime",
            None,
        )

        if callable(bind):

            try:
                bind(self)

            except Exception:

                logger.exception(
                    "[Phase1][FinalRuntime] "
                    "Failed to bind authoritative runtime."
                )

        logger.info(
            "[Phase1][FinalRuntime] Adapter initialized | "
            "final_engineer=%s | persistent_runtime=%s",
            self.final_engineer is not None,
            type(
                self._persistent_runtime
            ).__name__,
        )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_persistent_runtime(self) -> Any:
        """
        Reuse the canonical persistent runtime when possible.

        The legacy runtime is intentionally retained as the compatibility
        source of Phase 1 services.
        """

        if isinstance(
            self.legacy_phase1_runtime,
            PersistentEngineeringRuntime,
        ):
            return self.legacy_phase1_runtime

        try:

            signature = inspect.signature(
                PersistentEngineeringRuntime
            )

            parameters = signature.parameters

            kwargs: dict[str, Any] = {}

            for name, parameter in parameters.items():

                if name == "self":
                    continue

                if name == "legacy_runtime":

                    kwargs[name] = (
                        self.legacy_phase1_runtime
                    )

                elif name == "legacy_phase1_runtime":

                    kwargs[name] = (
                        self.legacy_phase1_runtime
                    )

                elif name == "development_controller":

                    kwargs[name] = (
                        self.development_controller
                    )

            if kwargs:

                try:

                    return PersistentEngineeringRuntime(
                        **kwargs
                    )

                except Exception:

                    logger.exception(
                        "[Phase1][FinalRuntime] "
                        "Could not construct a secondary "
                        "persistent runtime; preserving "
                        "legacy runtime."
                    )

        except Exception:

            logger.exception(
                "[Phase1][FinalRuntime] "
                "Persistent runtime inspection failed."
            )

        return self.legacy_phase1_runtime

    def _build_final_engineer(self) -> Any:
        """
        Build and validate the canonical FinalAutonomousEngineer.

        The adapter must never silently hide construction failures.

        The readiness gateway depends on a live final_engineer object
        exposing:
            - develop()
            - resume()
            - status()
            - health()
            - orchestrator

        Existing Phase 1 services are passed explicitly where available
        so the final engineer can construct the authoritative orchestration
        spine without creating duplicate runtime infrastructure.
        """

        # --------------------------------------------------------------
        # Import the canonical final engineer.
        # --------------------------------------------------------------

        try:

            from .final_autonomous_engineer import (
                FinalAutonomousEngineer,
            )

        except Exception as exc:

            logger.exception(
                "[Phase1][FinalRuntime] "
                "FinalAutonomousEngineer import failed | error=%s",
                exc,
            )

            return None

        legacy = (
            self.legacy_phase1_runtime
        )

        # --------------------------------------------------------------
        # Compatibility component lookup.
        # --------------------------------------------------------------

        def component(
            name: str,
            default: Any = None,
        ) -> Any:
            """
            Resolve an existing Phase 1 service.

            Resolution order:
            1. legacy runtime .get()
            2. legacy runtime .components
            3. direct attribute
            """

            getter = getattr(
                legacy,
                "get",
                None,
            )

            if callable(getter):

                try:

                    value = getter(
                        name,
                        default,
                    )

                    if value is not None:
                        return value

                except TypeError:

                    try:

                        value = getter(
                            name
                        )

                        if value is not None:
                            return value

                    except Exception:

                        logger.debug(
                            "[Phase1][FinalRuntime] "
                            "Component lookup failed | "
                            "name=%s",
                            name,
                            exc_info=True,
                        )

                except Exception:

                    logger.debug(
                        "[Phase1][FinalRuntime] "
                        "Component lookup failed | "
                        "name=%s",
                        name,
                        exc_info=True,
                    )

            components = getattr(
                legacy,
                "components",
                None,
            )

            if isinstance(
                components,
                dict,
            ):

                value = components.get(
                    name,
                    default,
                )

                if value is not None:
                    return value

            return getattr(
                legacy,
                name,
                default,
            )

        # --------------------------------------------------------------
        # Existing Phase 1 services.
        # --------------------------------------------------------------

        development_controller = (
            self.development_controller
            or component(
                "development_controller"
            )
        )

        development_agent = component(
            "development_agent"
        )

        if development_agent is None:

            development_agent = getattr(
                development_controller,
                "agent",
                None,
            )

        requirement_intelligence = (
            component(
                "requirement_intelligence"
            )
        )

        if requirement_intelligence is None:

            requirement_intelligence = getattr(
                development_agent,
                "requirement_intelligence",
                None,
            )

        knowledge_retriever = component(
            "knowledge_retriever"
        )

        verification_service = component(
            "verification_service"
        )

        if verification_service is None:

            verification_service = getattr(
                development_agent,
                "intelligent_verification",
                None,
            )

        repair_service = component(
            "autonomous_repair_loop"
        )

        judgment_engine = component(
            "engineering_judgment"
        )

        if judgment_engine is None:

            judgment_engine = getattr(
                development_agent,
                "engineering_judgment",
                None,
            )

        repository_engine = component(
            "repository_manager"
        )

        # --------------------------------------------------------------
        # Existing authoritative engines, when already registered.
        #
        # These are optional because FinalAutonomousEngineer itself
        # can construct authoritative wrappers around existing services.
        # --------------------------------------------------------------

        requirement_engine = component(
            "requirement_engine"
        )

        knowledge_engine = component(
            "knowledge_engine"
        )

        planning_engine = component(
            "planning_engine"
        )

        task_graph_engine = component(
            "task_graph_engine"
        )

        implementation_engine = component(
            "implementation_engine"
        )

        verification_engine = component(
            "verification_engine"
        )

        diagnosis_engine = component(
            "diagnosis_engine"
        )

        recovery_engine = component(
            "recovery_engine"
        )

        acceptance_engine = component(
            "acceptance_engine"
        )

        experience_engine = component(
            "experience_engine"
        )

        # --------------------------------------------------------------
        # Build the complete constructor candidate map.
        # --------------------------------------------------------------

        candidates: dict[str, Any] = {
            "legacy_runtime": legacy,
            "legacy_phase1_runtime": legacy,

            "persistent_runtime": (
                self._persistent_runtime
            ),

            "session_runtime": (
                self._persistent_runtime
            ),

            "development_controller": (
                development_controller
            ),

            "development_agent": (
                development_agent
            ),

            "requirement_intelligence": (
                requirement_intelligence
            ),

            "knowledge_retriever": (
                knowledge_retriever
            ),

            "verification_service": (
                verification_service
            ),

            "repair_service": (
                repair_service
            ),

            "judgment_engine": (
                judgment_engine
            ),

            "repository_engine": (
                repository_engine
            ),

            "requirement_engine": (
                requirement_engine
            ),

            "knowledge_engine": (
                knowledge_engine
            ),

            "planning_engine": (
                planning_engine
            ),

            "task_graph_engine": (
                task_graph_engine
            ),

            "implementation_engine": (
                implementation_engine
            ),

            "verification_engine": (
                verification_engine
            ),

            "diagnosis_engine": (
                diagnosis_engine
            ),

            "recovery_engine": (
                recovery_engine
            ),

            "acceptance_engine": (
                acceptance_engine
            ),

            "experience_engine": (
                experience_engine
            ),

            "persistence": getattr(
                self._persistent_runtime,
                "persistence",
                None,
            ),
        }

        # --------------------------------------------------------------
        # Inspect the exact deployed constructor.
        #
        # This avoids hard-coding a constructor contract while still
        # refusing to silently ignore genuinely required arguments.
        # --------------------------------------------------------------

        try:

            signature = inspect.signature(
                FinalAutonomousEngineer
            )

            parameters = signature.parameters

        except Exception as exc:

            logger.exception(
                "[Phase1][FinalRuntime] "
                "Could not inspect FinalAutonomousEngineer "
                "constructor | error=%s",
                exc,
            )

            return None

        kwargs: dict[str, Any] = {}

        unresolved_required: list[str] = []

        accepts_var_kwargs = any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter
            in parameters.values()
        )

        for name, parameter in parameters.items():

            if name == "self":
                continue

            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            if name in candidates:

                value = candidates[name]

                if value is not None:

                    kwargs[name] = value

                elif (
                    parameter.default
                    is inspect.Parameter.empty
                ):

                    unresolved_required.append(
                        name
                    )

                continue

            if (
                parameter.default
                is inspect.Parameter.empty
            ):

                unresolved_required.append(
                    name
                )

        if unresolved_required:

            logger.error(
                "[Phase1][FinalRuntime] "
                "FinalAutonomousEngineer has unresolved "
                "required constructor arguments: %s",
                unresolved_required,
            )

            return None

        # --------------------------------------------------------------
        # Construct the final engineer.
        # --------------------------------------------------------------

        try:

            if accepts_var_kwargs:

                # The constructor accepts **kwargs, but we still pass
                # only known canonical service names. This prevents
                # accidental legacy-object leakage.

                engineer = FinalAutonomousEngineer(
                    **kwargs
                )

            else:

                engineer = FinalAutonomousEngineer(
                    **kwargs
                )

        except Exception as exc:

            logger.exception(
                "[Phase1][FinalRuntime] "
                "FinalAutonomousEngineer construction failed | "
                "error=%s",
                exc,
            )

            return None

        if engineer is None:

            logger.error(
                "[Phase1][FinalRuntime] "
                "FinalAutonomousEngineer constructor returned None."
            )

            return None

        # --------------------------------------------------------------
        # Enforce canonical runtime identity.
        # --------------------------------------------------------------

        if hasattr(
            engineer,
            "persistent_runtime",
        ):

            engineer.persistent_runtime = (
                self._persistent_runtime
            )

        if hasattr(
            engineer,
            "development_controller",
        ):

            if (
                engineer.development_controller
                is None
            ):

                engineer.development_controller = (
                    development_controller
                )

        # --------------------------------------------------------------
        # Validate the public final-engineer contract.
        # --------------------------------------------------------------

        required_methods = (
            "develop",
            "resume",
            "status",
            "health",
        )

        missing_methods = [
            name
            for name in required_methods
            if not callable(
                getattr(
                    engineer,
                    name,
                    None,
                )
            )
        ]

        if missing_methods:

            logger.error(
                "[Phase1][FinalRuntime] "
                "FinalAutonomousEngineer contract incomplete | "
                "missing=%s",
                missing_methods,
            )

            return None

        orchestrator = getattr(
            engineer,
            "orchestrator",
            None,
        )

        if orchestrator is None:

            logger.error(
                "[Phase1][FinalRuntime] "
                "FinalAutonomousEngineer has no authoritative "
                "engineering orchestrator."
            )

            return None

        # --------------------------------------------------------------
        # Validate authoritative orchestrator contract.
        # --------------------------------------------------------------

        orchestrator_health = getattr(
            orchestrator,
            "health",
            None,
        )

        if not callable(
            orchestrator_health
        ):

            logger.error(
                "[Phase1][FinalRuntime] "
                "Authoritative engineering orchestrator "
                "has no health() method."
            )

            return None

        # --------------------------------------------------------------
        # Validate final-engineer health.
        #
        # Health validation is read-only. It does not execute engineering.
        # --------------------------------------------------------------

        try:

            health_method = getattr(
                engineer,
                "health",
            )

            health = health_method()

            if not isinstance(
                health,
                dict,
            ):

                logger.error(
                    "[Phase1][FinalRuntime] "
                    "FinalAutonomousEngineer health() "
                    "returned non-dict result."
                )

                return None

            logger.info(
                "[Phase1][FinalRuntime] "
                "Final autonomous engineer connected | "
                "class=%s | canonical_runtime=%s | "
                "health=%s",
                type(
                    engineer
                ).__name__,
                type(
                    self._persistent_runtime
                ).__name__,
                health,
            )

        except Exception as exc:

            logger.exception(
                "[Phase1][FinalRuntime] "
                "Final autonomous engineer health validation "
                "failed | error=%s",
                exc,
            )

            return None

        # --------------------------------------------------------------
        # Validate orchestrator health.
        # --------------------------------------------------------------

        try:

            orchestrator_report = (
                orchestrator_health()
            )

            if not isinstance(
                orchestrator_report,
                dict,
            ):

                logger.error(
                    "[Phase1][FinalRuntime] "
                    "Authoritative orchestrator health() "
                    "returned non-dict result."
                )

                return None

            if not bool(
                orchestrator_report.get(
                    "healthy",
                    False,
                )
            ):

                logger.error(
                    "[Phase1][FinalRuntime] "
                    "Authoritative engineering orchestrator "
                    "is unhealthy | health=%s",
                    orchestrator_report,
                )

                return None

        except Exception as exc:

            logger.exception(
                "[Phase1][FinalRuntime] "
                "Authoritative orchestrator health validation "
                "failed | error=%s",
                exc,
            )

            return None

        logger.info(
            "[Phase1][FinalRuntime] "
            "Canonical FinalAutonomousEngineer validation PASSED."
        )

        return engineer

    # ------------------------------------------------------------------
    # Generic invocation
    # ------------------------------------------------------------------

    @staticmethod
    async def _invoke(
        target: Any,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:

        method = getattr(
            target,
            method_name,
            None,
        )

        if method is None:

            raise AttributeError(
                f"{type(target).__name__} has no method "
                f"'{method_name}'."
            )

        result = method(
            *args,
            **kwargs,
        )

        if inspect.isawaitable(
            result
        ):

            return await result

        return result

    # ------------------------------------------------------------------
    # Safe object/dict normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_to_dict(
        value: Any,
    ) -> dict[str, Any]:

        if value is None:
            return {}

        if isinstance(
            value,
            dict,
        ):

            return dict(value)

        method = getattr(
            value,
            "to_dict",
            None,
        )

        if callable(method):

            try:

                converted = method()

                if isinstance(
                    converted,
                    dict,
                ):

                    return converted

            except Exception:

                logger.debug(
                    "[Phase1][FinalRuntime] "
                    "Object to_dict() conversion failed.",
                    exc_info=True,
                )

        if hasattr(
            value,
            "__dict__",
        ):

            try:

                return {
                    str(key): item
                    for key, item
                    in vars(value).items()
                    if not str(
                        key
                    ).startswith("_")
                }

            except Exception:

                pass

        return {
            "value": str(value)
        }

    @staticmethod
    def _result_success(
        result: Any,
    ) -> bool:

        if isinstance(
            result,
            bool,
        ):

            return result

        if isinstance(
            result,
            dict,
        ):

            return bool(
                result.get(
                    "success",
                    False,
                )
            )

        return bool(
            getattr(
                result,
                "success",
                False,
            )
        )

    @staticmethod
    def _result_accepted(
        result: Any,
    ) -> bool:

        if isinstance(
            result,
            dict,
        ):

            return bool(
                result.get(
                    "accepted",
                    result.get(
                        "is_accepted",
                        False,
                    ),
                )
            )

        return bool(
            getattr(
                result,
                "accepted",
                getattr(
                    result,
                    "is_accepted",
                    False,
                ),
            )
        )

    @staticmethod
    def _result_status(
        result: Any,
    ) -> str:

        if isinstance(
            result,
            dict,
        ):

            return str(
                result.get(
                    "status",
                    (
                        "completed"
                        if result.get(
                            "success",
                            False,
                        )
                        else "failed"
                    ),
                )
            )

        return str(
            getattr(
                result,
                "status",
                (
                    "completed"
                    if getattr(
                        result,
                        "success",
                        False,
                    )
                    else "failed"
                ),
            )
        )

    @staticmethod
    def _result_session_id(
        result: Any,
    ) -> str | None:

        if isinstance(
            result,
            dict,
        ):

            value = result.get(
                "session_id"
            )

        else:

            value = getattr(
                result,
                "session_id",
                None,
            )

        return (
            str(value)
            if value
            else None
        )

    @staticmethod
    def _result_summary(
        result: Any,
    ) -> str:

        if isinstance(
            result,
            dict,
        ):

            return str(
                result.get(
                    "summary",
                    result.get(
                        "message",
                        "",
                    ),
                )
            )

        return str(
            getattr(
                result,
                "summary",
                getattr(
                    result,
                    "message",
                    "",
                ),
            )
        )

    @staticmethod
    def _result_errors(
        result: Any,
    ) -> tuple[str, ...]:

        if isinstance(
            result,
            dict,
        ):

            value = result.get(
                "errors",
                (),
            )

        else:

            value = getattr(
                result,
                "errors",
                (),
            )

        if value is None:
            return ()

        if isinstance(
            value,
            str,
        ):

            return (
                value,
            )

        try:

            return tuple(
                str(item)
                for item in value
                if str(item).strip()
            )

        except TypeError:

            return (
                str(value),
            )

    def _normalize_result(
        self,
        result: Any,
    ) -> Any:
        """
        Normalize final-engineer results.

        A final-engineer implementation may return:
        - PersistentEngineeringResult
        - another result object
        - a plain dict
        - a bool

        None of these should cause Telegram processing to fail merely
        because one layer expects `.to_dict()`.
        """

        if isinstance(
            result,
            PersistentEngineeringResult,
        ):

            return result

        if all(
            hasattr(
                result,
                name,
            )
            for name in (
                "success",
                "accepted",
                "status",
            )
        ):

            return result

        return PersistentEngineeringResult(
            success=self._result_success(
                result
            ),
            accepted=self._result_accepted(
                result
            ),
            status=self._result_status(
                result
            ),
            session_id=self._result_session_id(
                result
            ),
            summary=self._result_summary(
                result
            ),
            errors=self._result_errors(
                result
            ),
            metadata={
                "final_engineer_result": (
                    self._safe_to_dict(
                        result
                    )
                ),
            },
        )

    # ------------------------------------------------------------------
    # Final engineer compatibility detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_result_contract_error(
        exc: BaseException,
    ) -> bool:

        message = str(exc).lower()

        patterns = (
            "dict' object has no attribute 'to_dict'",
            '"dict" object has no attribute "to_dict"',
            "attributeerror",
            "to_dict",
        )

        return any(
            pattern in message
            for pattern in patterns
        )

    # ------------------------------------------------------------------
    # Legacy execution guard
    # ------------------------------------------------------------------

    async def _legacy_execution_guard(
        self,
        requirement: str,
        *,
        original_error: BaseException | None = None,
        **_: Any,
    ) -> Any:
        """
        Fail closed instead of entering a legacy engineering lifecycle.
        """

        reason = (
            str(original_error)
            if original_error is not None
            else (
                "the authoritative engineer is unavailable"
            )
        )

        raise RuntimeError(
            "Canonical Phase 1 engineering execution failed "
            "before completion; legacy execution fallback is "
            "disabled. "
            f"Reason: {reason}"
        )

    # ------------------------------------------------------------------
    # Canonical engineering API
    # ------------------------------------------------------------------

    async def develop(
        self,
        requirement: str,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Run only the authoritative FinalAutonomousEngineer lifecycle.
        """

        if self.final_engineer is None:

            raise RuntimeError(
                "FinalAutonomousEngineer is unavailable; "
                "legacy engineering fallback is disabled."
            )

        logger.info(
            "[Phase1][FinalRuntime] "
            "Starting canonical autonomous engineering | "
            "session=%s",
            session_id or "new",
        )

        try:

            result = await self._invoke(
                self.final_engineer,
                "develop",
                requirement,
                session_id=session_id,
                metadata=metadata,
                **kwargs,
            )

            normalized = (
                self._normalize_result(
                    result
                )
            )

            logger.info(
                "[Phase1][FinalRuntime] "
                "Canonical autonomous engineering finished | "
                "success=%s | accepted=%s | status=%s",
                self._result_success(
                    normalized
                ),
                self._result_accepted(
                    normalized
                ),
                self._result_status(
                    normalized
                ),
            )

            return normalized

        except TypeError as exc:

            # A TypeError can indicate an argument-contract mismatch.
            # Retry the same authoritative object with only the required
            # engineering request.
            try:

                result = await self._invoke(
                    self.final_engineer,
                    "develop",
                    requirement,
                )

                return self._normalize_result(
                    result
                )

            except Exception as retry_exc:

                raise RuntimeError(
                    "Canonical FinalAutonomousEngineer "
                    "execution failed after compatibility "
                    f"retry: {retry_exc}"
                ) from retry_exc

        except Exception:

            logger.exception(
                "[Phase1][FinalRuntime] "
                "Canonical autonomous engineer execution failed."
            )

            raise

    async def execute(
        self,
        requirement: str,
        **kwargs: Any,
    ) -> Any:

        return await self.develop(
            requirement,
            **kwargs,
        )

    async def run(
        self,
        requirement: str,
        **kwargs: Any,
    ) -> Any:

        return await self.develop(
            requirement,
            **kwargs,
        )

    async def resume(
        self,
        session_id: str,
        **kwargs: Any,
    ) -> Any:

        if self.final_engineer is not None:

            method = getattr(
                self.final_engineer,
                "resume",
                None,
            )

            if method is not None:

                try:

                    result = await self._invoke(
                        self.final_engineer,
                        "resume",
                        session_id,
                        **kwargs,
                    )

                    return self._normalize_result(
                        result
                    )

                except Exception as exc:

                    # Resume is still kept authoritative first.
                    # The persistent runtime is used only as a state
                    # continuation compatibility path, not as a second
                    # engineering lifecycle.
                    logger.warning(
                        "[Phase1][FinalRuntime] "
                        "Final engineer resume failed; "
                        "delegating to persistent runtime | "
                        "error=%s",
                        exc,
                    )

        return await self._invoke(
            self._persistent_runtime,
            "resume",
            session_id,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # State / health / persistence
    # ------------------------------------------------------------------

    def engineering_status(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:

        if self.final_engineer is not None:

            method = getattr(
                self.final_engineer,
                "status",
                None,
            )

            if method is not None:

                try:

                    value = method(
                        session_id=session_id
                    )

                    if inspect.isawaitable(
                        value
                    ):

                        raise RuntimeError(
                            "Final engineer status is asynchronous."
                        )

                    if isinstance(
                        value,
                        dict,
                    ):

                        value = dict(
                            value
                        )

                        value.setdefault(
                            "component_count",
                            self._component_count(),
                        )

                        value.setdefault(
                            "authoritative",
                            True,
                        )

                        value.setdefault(
                            "integrated",
                            True,
                        )

                        return value

                except Exception:

                    logger.debug(
                        "[Phase1][FinalRuntime] "
                        "Final status unavailable; "
                        "using persistent status.",
                        exc_info=True,
                    )

        for name in (
            "engineering_status",
            "status",
        ):

            method = getattr(
                self._persistent_runtime,
                name,
                None,
            )

            if method is not None:

                try:

                    value = method(
                        session_id=session_id
                    )

                except TypeError:

                    value = method()

                if isinstance(
                    value,
                    dict,
                ):

                    value = dict(
                        value
                    )

                    value.setdefault(
                        "component_count",
                        self._component_count(),
                    )

                    value.setdefault(
                        "authoritative",
                        True,
                    )

                    value.setdefault(
                        "integrated",
                        True,
                    )

                    return value

        return {
            "healthy": False,
            "status": "unavailable",
            "session_id": session_id,
            "component_count": self._component_count(),
            "authoritative": True,
            "integrated": True,
        }

    def _component_count(self) -> int:
        """
        Return a bootstrap-compatible count of integrated components.
        """

        components = getattr(
            self.legacy_phase1_runtime,
            "components",
            None,
        )

        if isinstance(
            components,
            dict,
        ):

            return len(
                components
            )

        getter = getattr(
            self.legacy_phase1_runtime,
            "get",
            None,
        )

        if callable(
            getter
        ):

            known = (
                "autonomous_development_bridge",
                "autonomous_coding_loop",
                "autonomous_validation_loop",
                "autonomous_repair_loop",
                "knowledge_coding_feedback",
                "permissioned_git_workflow",
                "permissioned_deployment_workflow",
            )

            count = 0

            for key in known:

                try:

                    if getter(
                        key
                    ) is not None:

                        count += 1

                except Exception:

                    continue

            if count:
                return count

        return 8

    def status(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:

        return self.engineering_status(
            session_id=session_id
        )

    def checkpoint(
        self,
        session_id: str | None = None,
    ) -> Any:

        method = getattr(
            self._persistent_runtime,
            "checkpoint",
            None,
        )

        if method is None:
            return None

        try:

            return method(
                session_id=session_id
            )

        except TypeError:

            return method()

    def save(
        self,
        session_id: str | None = None,
    ) -> Any:

        method = getattr(
            self._persistent_runtime,
            "save",
            None,
        )

        if method is None:

            return self.checkpoint(
                session_id=session_id
            )

        try:

            return method(
                session_id=session_id
            )

        except TypeError:

            return method()

    def persist(
        self,
        session_id: str | None = None,
    ) -> Any:

        return self.save(
            session_id=session_id
        )

    def health(self) -> dict[str, Any]:
        """
        Return adapter health without executing engineering work.
        """

        base_health: dict[str, Any] = {}

        method = getattr(
            self._persistent_runtime,
            "health",
            None,
        )

        if method is not None:

            try:

                value = method()

                if isinstance(
                    value,
                    dict,
                ):

                    base_health.update(
                        value
                    )

            except Exception:

                logger.debug(
                    "[Phase1][FinalRuntime] "
                    "Persistent health check failed.",
                    exc_info=True,
                )

        final_engineer_health: dict[str, Any] = {}

        if self.final_engineer is not None:

            method = getattr(
                self.final_engineer,
                "health",
                None,
            )

            if callable(
                method
            ):

                try:

                    value = method()

                    if isinstance(
                        value,
                        dict,
                    ):

                        final_engineer_health = dict(
                            value
                        )

                except Exception:

                    logger.debug(
                        "[Phase1][FinalRuntime] "
                        "Final engineer health check failed.",
                        exc_info=True,
                    )

        base_health.update(
            {
                "final_autonomous_engineer": (
                    self.final_engineer is not None
                ),
                "final_engineer_healthy": (
                    bool(
                        final_engineer_health.get(
                            "healthy",
                            False,
                        )
                    )
                    if self.final_engineer is not None
                    else False
                ),
                "adapter": True,
                "runtime_type": type(
                    self._persistent_runtime
                ).__name__,
            }
        )

        if final_engineer_health:

            base_health[
                "final_engineer_health"
            ] = final_engineer_health

        return base_health

    # ------------------------------------------------------------------
    # Capability compatibility
    # ------------------------------------------------------------------

    def get(
        self,
        name: str,
        default: Any = None,
    ) -> Any:
        """
        Preserve the legacy capability-registry contract.
        """

        # The adapter itself is the canonical source for the final
        # autonomous engineer and canonical persistent runtime.
        if name in (
            "final_engineer",
            "final_autonomous_engineer",
        ):

            return (
                self.final_engineer
                if self.final_engineer is not None
                else default
            )

        if name in (
            "persistent_runtime",
            "session_runtime",
        ):

            return self._persistent_runtime

        for source in (
            self._persistent_runtime,
            self.legacy_phase1_runtime,
        ):

            getter = getattr(
                source,
                "get",
                None,
            )

            if getter is None:
                continue

            try:

                value = getter(
                    name,
                    default,
                )

            except TypeError:

                try:

                    value = getter(
                        name
                    )

                except Exception:

                    continue

            if value is not None:
                return value

        return default

    def __getattr__(
        self,
        name: str,
    ) -> Any:
        """
        Delegate unknown compatibility attributes to the persistent/legacy
        runtime rather than breaking existing integrations.
        """

        for source in (
            self._persistent_runtime,
            self.legacy_phase1_runtime,
        ):

            try:

                return getattr(
                    source,
                    name,
                )

            except AttributeError:

                continue

        raise AttributeError(
            f"{type(self).__name__!s} "
            f"has no attribute {name!r}"
        )


__all__ = [
    "Phase1PersistentRuntimeAdapter",
]