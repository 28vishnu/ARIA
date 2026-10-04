from __future__ import annotations

"""
Phase 1 final autonomous-engineer runtime adapter.

This module is the single integration boundary between the existing
Phase 1 runtime and the final autonomous-engineer facade.

Design goals:
- preserve the existing bootstrap contract;
- expose the final autonomous engineer to Telegram;
- keep the legacy runtime available as a compatibility/fallback path;
- never bypass GitHub/deployment permission boundaries;
- normalize object/dict results safely;
- fail closed on incompatible final-engineer responses;
- keep `.get()` compatibility for the Phase 1 capability registry.
"""

import inspect
import logging
from typing import Any

from .persistent_engineering_runtime import (
    PersistentEngineeringRuntime,
    PersistentEngineeringResult,
)

from .authoritative_engineering_persistence import (
    AuthoritativeEngineeringPersistence,
)
from .authoritative_engineering_requirement import (
    AuthoritativeEngineeringRequirement,
)
from .authoritative_engineering_knowledge import (
    AuthoritativeEngineeringKnowledge,
)
from .authoritative_implementation import (
    AuthoritativeImplementationEngine,
)
from .authoritative_verification import (
    AuthoritativeVerificationEngine,
)
from .authoritative_diagnosis import (
    AuthoritativeDiagnosisEngine,
)
from .authoritative_recovery import (
    AuthoritativeRecoveryEngine,
)
from .authoritative_acceptance import (
    AuthoritativeAcceptanceEngine,
)
from .authoritative_experience import (
    AuthoritativeExperienceEngine,
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

        self.legacy_phase1_runtime = legacy_phase1_runtime
        self.development_controller = development_controller

        # One persistent store is shared by the authoritative lifecycle
        # and the persistent runtime.  This prevents the new engineering
        # spine from creating an independent state store.
        self.engineering_persistence = (
            AuthoritativeEngineeringPersistence()
        )

        self._persistent_runtime = (
            self._build_persistent_runtime()
        )

        self.final_engineer = (
            self._build_final_engineer()
        )

        logger.info(
            "[Phase1][FinalRuntime] Adapter initialized | "
            "final_engineer=%s | persistent_runtime=%s",
            self.final_engineer is not None,
            type(self._persistent_runtime).__name__,
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

            for name in parameters:

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

                elif name in {
                    "persistence",
                    "engineering_persistence",
                }:
                    kwargs[name] = (
                        self.engineering_persistence
                    )

            if kwargs:

                try:
                    return PersistentEngineeringRuntime(
                        **kwargs
                    )

                except Exception:

                    logger.exception(
                        "[Phase1][FinalRuntime] Could not construct "
                        "a secondary persistent runtime; preserving "
                        "legacy runtime."
                    )

        except Exception:

            logger.exception(
                "[Phase1][FinalRuntime] Persistent runtime inspection "
                "failed."
            )

        return self.legacy_phase1_runtime

    def _build_final_engineer(self) -> Any:
        """
        Build the final engineer with the REAL Phase 1 services.

        This is the critical integration boundary.  The final engineer
        must never be constructed as an empty facade with all engines
        set to None.
        """
        try:
            from .final_autonomous_engineer import (
                FinalAutonomousEngineer,
            )

            controller = self.development_controller
            agent = getattr(
                controller,
                "agent",
                None,
            )

            if agent is None:
                raise RuntimeError(
                    "DevelopmentController.agent is unavailable."
                )

            requirement_engine = (
                AuthoritativeEngineeringRequirement(
                    requirement_intelligence=getattr(
                        agent,
                        "requirement_intelligence",
                        None,
                    )
                )
            )

            runtime_components = getattr(
                self.legacy_phase1_runtime,
                "components",
                {},
            ) or {}

            knowledge_engine = (
                AuthoritativeEngineeringKnowledge(
                    knowledge_database=getattr(
                        self.legacy_phase1_runtime,
                        "knowledge_database",
                        None,
                    ),
                    knowledge_graph=getattr(
                        self.legacy_phase1_runtime,
                        "knowledge_graph",
                        None,
                    ),
                    knowledge_engine=runtime_components.get(
                        "knowledge_retriever"
                    ),
                    search_engine=runtime_components.get(
                        "knowledge_retriever"
                    ),
                    research_engine=runtime_components.get(
                        "knowledge_retriever"
                    ),
                    memory_engine=getattr(
                        self.legacy_phase1_runtime,
                        "memory_engine",
                        None,
                    ),
                )
            )

            implementation_engine = (
                AuthoritativeImplementationEngine(
                    development_controller=controller,
                    development_agent=agent,
                )
            )

            verification_engine = (
                AuthoritativeVerificationEngine(
                    verifier=getattr(
                        agent,
                        "intelligent_verification",
                        None,
                    )
                )
            )

            diagnosis_engine = (
                AuthoritativeDiagnosisEngine()
            )

            repair_loop = runtime_components.get(
                "autonomous_repair_loop"
            )

            recovery_engine = (
                AuthoritativeRecoveryEngine(
                    repair_engine=repair_loop,
                )
            )

            acceptance_engine = (
                AuthoritativeAcceptanceEngine(
                    judgment_engine=getattr(
                        agent,
                        "engineering_judgment",
                        None,
                    ),
                    verification_engine=verification_engine,
                )
            )

            experience_engine = (
                AuthoritativeExperienceEngine(
                    knowledge_engine=knowledge_engine,
                )
            )

            # The orchestrator builds the authoritative plan/task graph
            # itself when no independent planner/graph adapter is needed.
            from .authoritative_engineering_orchestrator import (
                AuthoritativeEngineeringOrchestrator,
            )

            orchestrator = (
                AuthoritativeEngineeringOrchestrator(
                    persistence=self.engineering_persistence,
                    requirement_engine=requirement_engine,
                    knowledge_engine=knowledge_engine,
                    implementation_engine=implementation_engine,
                    verification_engine=verification_engine,
                    diagnosis_engine=diagnosis_engine,
                    recovery_engine=recovery_engine,
                    acceptance_engine=acceptance_engine,
                    experience_engine=experience_engine,
                    repository_engine=getattr(
                        agent,
                        "repository_manager",
                        None,
                    ),
                )
            )

            engineer = FinalAutonomousEngineer(
                orchestrator=orchestrator,
                legacy_runtime=self._persistent_runtime,
                session_runtime=None,
            )

            self._integrated_orchestrator = orchestrator

            logger.info(
                "[Phase1][FinalRuntime] Final autonomous engineer "
                "fully integrated | requirement=%s | knowledge=%s | "
                "implementation=%s | verification=%s | diagnosis=%s | "
                "recovery=%s | acceptance=%s | experience=%s",
                type(requirement_engine).__name__,
                type(knowledge_engine).__name__,
                type(implementation_engine).__name__,
                type(verification_engine).__name__,
                type(diagnosis_engine).__name__,
                type(recovery_engine).__name__,
                type(acceptance_engine).__name__,
                type(experience_engine).__name__,
            )

            return engineer

        except Exception:
            logger.exception(
                "[Phase1][FinalRuntime] Final autonomous engineer "
                "could not be fully integrated."
            )
            return None

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

        if inspect.isawaitable(result):

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

        if isinstance(value, dict):
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
                    "[Phase1][FinalRuntime] Object to_dict() "
                    "conversion failed.",
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
                    if not str(key).startswith("_")
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
            return (value,)

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
    # Persistent fallback
    # ------------------------------------------------------------------

    async def _fallback_to_persistent_runtime(
        self,
        requirement: str,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        original_error: BaseException | None = None,
        **kwargs: Any,
    ) -> Any:

        logger.warning(
            "[Phase1][FinalRuntime] Falling back to established "
            "persistent Phase 1 runtime | reason=%s",
            original_error,
        )

        try:

            result = await self._invoke(
                self._persistent_runtime,
                "develop",
                requirement,
                session_id=session_id,
                metadata=metadata,
                **kwargs,
            )

            normalized = self._normalize_result(
                result
            )

            logger.info(
                "[Phase1][FinalRuntime] Persistent fallback completed | "
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

        except TypeError:

            try:

                result = await self._invoke(
                    self._persistent_runtime,
                    "develop",
                    requirement,
                )

                return self._normalize_result(
                    result
                )

            except Exception:

                logger.exception(
                    "[Phase1][FinalRuntime] Persistent fallback "
                    "also failed."
                )

                raise

        except Exception:

            logger.exception(
                "[Phase1][FinalRuntime] Persistent fallback "
                "failed."
            )

            raise

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
        Run the final autonomous engineering pipeline.

        If the final facade encounters a result-contract compatibility
        problem, fall back to the established persistent Phase 1 runtime
        instead of returning an internal implementation error to Telegram.
        """

        if self.final_engineer is not None:

            try:

                logger.info(
                    "[Phase1][FinalRuntime] Starting final autonomous "
                    "engineering | session=%s",
                    session_id or "new",
                )

                result = await self._invoke(
                    self.final_engineer,
                    "develop",
                    requirement,
                    session_id=session_id,
                    metadata=metadata,
                    **kwargs,
                )

                normalized = self._normalize_result(
                    result
                )

                logger.info(
                    "[Phase1][FinalRuntime] Final autonomous engineering "
                    "finished | success=%s | accepted=%s | status=%s",
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

                logger.warning(
                    "[Phase1][FinalRuntime] Final engineer argument "
                    "compatibility fallback: %s",
                    exc,
                )

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

                    if self._is_result_contract_error(
                        retry_exc
                    ):

                        return await (
                            self._fallback_to_persistent_runtime(
                                requirement,
                                session_id=session_id,
                                metadata=metadata,
                                original_error=retry_exc,
                                **kwargs,
                            )
                        )

                    logger.exception(
                        "[Phase1][FinalRuntime] Final engineer execution "
                        "failed after compatibility retry."
                    )

                    raise

            except Exception as exc:

                if self._is_result_contract_error(
                    exc
                ):

                    logger.warning(
                        "[Phase1][FinalRuntime] Final engineer encountered "
                        "a result-contract compatibility error. "
                        "Using persistent Phase 1 fallback."
                    )

                    return await (
                        self._fallback_to_persistent_runtime(
                            requirement,
                            session_id=session_id,
                            metadata=metadata,
                            original_error=exc,
                            **kwargs,
                        )
                    )

                logger.exception(
                    "[Phase1][FinalRuntime] Final autonomous engineer "
                    "execution failed."
                )

                raise

        logger.info(
            "[Phase1][FinalRuntime] Final engineer unavailable; "
            "using established persistent Phase 1 runtime."
        )

        return await self._fallback_to_persistent_runtime(
            requirement,
            session_id=session_id,
            metadata=metadata,
            **kwargs,
        )

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

                    logger.warning(
                        "[Phase1][FinalRuntime] Final engineer resume "
                        "failed; delegating to persistent runtime | "
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

                        return value

                except Exception:

                    logger.debug(
                        "[Phase1][FinalRuntime] Final status unavailable; "
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

                    return value

        return {
            "healthy": False,
            "status": "unavailable",
            "session_id": session_id,
        }

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
                    "[Phase1][FinalRuntime] Persistent health "
                    "check failed.",
                    exc_info=True,
                )

        base_health.update(
            {
                "final_autonomous_engineer": (
                    self.final_engineer is not None
                ),
                "adapter": True,
                "runtime_type": type(
                    self._persistent_runtime
                ).__name__,
            }
        )

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
            f"{type(self).__name__!s} has no attribute {name!r}"
        )


__all__ = [
    "Phase1PersistentRuntimeAdapter",
]