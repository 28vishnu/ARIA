from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any

from .authoritative_engineering_orchestrator import (
    AuthoritativeEngineeringOrchestrator,
    EngineeringOrchestrationResult,
)


logger = logging.getLogger("aria")


@dataclass(frozen=True)
class FinalEngineeringResult:
    """
    Final Phase 1 public engineering result.
    """

    success: bool
    accepted: bool
    session_id: str
    status: str
    phase: str
    error: str | None = None

    requirement: Any | None = None
    knowledge: Any | None = None
    plan: Any | None = None
    task_graph: Any | None = None
    implementation: Any | None = None
    verification: Any | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "accepted": self.accepted,
            "session_id": self.session_id,
            "status": self.status,
            "phase": self.phase,
            "error": self.error,
            "requirement": _serialize(
                self.requirement
            ),
            "knowledge": _serialize(
                self.knowledge
            ),
            "plan": _serialize(
                self.plan
            ),
            "task_graph": _serialize(
                self.task_graph
            ),
            "implementation": _serialize(
                self.implementation
            ),
            "verification": _serialize(
                self.verification
            ),
            "metadata": dict(
                self.metadata
            ),
        }


def _serialize(
    value: Any,
) -> Any:
    if value is None:
        return None

    if isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    if isinstance(
        value,
        dict,
    ):
        return {
            str(key): _serialize(
                item
            )
            for key, item in value.items()
        }

    if isinstance(
        value,
        (list, tuple, set),
    ):
        return [
            _serialize(
                item
            )
            for item in value
        ]

    method = getattr(
        value,
        "to_dict",
        None,
    )

    if callable(method):
        try:
            return _serialize(
                method()
            )
        except Exception:
            pass

    return str(
        value
    )


class FinalAutonomousEngineer:
    """
    Final Phase 1 autonomous software engineer.

    Canonical engineering lifecycle:

        requirement
            ↓
        knowledge/research
            ↓
        repository understanding
            ↓
        adaptive planning
            ↓
        task graph
            ↓
        implementation
            ↓
        verification
            ↓
        diagnosis
            ↓
        recovery
            ↓
        retest
            ↓
        reassessment
            ↓
        acceptance

    GitHub push and deployment remain behind their
    existing explicit authorization boundaries.
    """

    VERSION = (
        "ARIA-PHASE1-FINAL-AUTONOMOUS-ENGINEER-20261004"
    )

    def __init__(
        self,
        *,
        orchestrator: Any | None = None,
        legacy_runtime: Any | None = None,
        persistent_runtime: Any | None = None,
        development_controller: Any | None = None,
        requirement_engine: Any | None = None,
        knowledge_engine: Any | None = None,
        planning_engine: Any | None = None,
        task_graph_engine: Any | None = None,
        implementation_engine: Any | None = None,
        verification_engine: Any | None = None,
        diagnosis_engine: Any | None = None,
        recovery_engine: Any | None = None,
        acceptance_engine: Any | None = None,
        repository_engine: Any | None = None,
        evidence_recorder: Any | None = None,
        session_runtime: Any | None = None,
    ) -> None:

        self.legacy_runtime = (
            legacy_runtime
        )

        # IMPORTANT:
        # This must be the canonical persistent runtime supplied
        # by Phase1PersistentRuntimeAdapter.
        #
        # Never create another PersistentEngineeringRuntime here.
        self.persistent_runtime = (
            persistent_runtime
        )

        self.development_controller = (
            development_controller
            or getattr(
                legacy_runtime,
                "development_controller",
                None,
            )
        )

        self.orchestrator = (
            orchestrator
            or self._build_orchestrator(
                requirement_engine=(
                    requirement_engine
                ),
                knowledge_engine=(
                    knowledge_engine
                ),
                planning_engine=(
                    planning_engine
                ),
                task_graph_engine=(
                    task_graph_engine
                ),
                implementation_engine=(
                    implementation_engine
                ),
                verification_engine=(
                    verification_engine
                ),
                diagnosis_engine=(
                    diagnosis_engine
                ),
                recovery_engine=(
                    recovery_engine
                ),
                acceptance_engine=(
                    acceptance_engine
                ),
                repository_engine=(
                    repository_engine
                ),
                evidence_recorder=(
                    evidence_recorder
                ),
                session_runtime=(
                    session_runtime
                    or persistent_runtime
                ),
                persistent_runtime=(
                    persistent_runtime
                ),
                development_controller=(
                    self.development_controller
                ),
            )
        )

        self._active_session_id: str | None = (
            None
        )

    # ============================================================
    # FINAL PUBLIC API
    # ============================================================

    async def develop(
        self,
        request: str,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FinalEngineeringResult:

        request = str(
            request or ""
        ).strip()

        if not request:
            return FinalEngineeringResult(
                success=False,
                accepted=False,
                session_id=(
                    session_id
                    or ""
                ),
                status="empty_request",
                phase="created",
                error=(
                    "Engineering request cannot be empty."
                ),
            )

        self._active_session_id = (
            session_id
        )

        try:
            result = await self._run_orchestrator(
                request,
                session_id=session_id,
                metadata=metadata,
            )

            return self._normalize_result(
                result,
                session_id=session_id,
            )

        except Exception as exc:
            logger.exception(
                "[FinalAutonomousEngineer] "
                "Autonomous engineering failed."
            )

            return FinalEngineeringResult(
                success=False,
                accepted=False,
                session_id=(
                    session_id
                    or self._active_session_id
                    or ""
                ),
                status="engineering_failed",
                phase="failed",
                error=str(exc),
            )

    async def execute(
        self,
        request: str,
        **kwargs: Any,
    ) -> FinalEngineeringResult:

        return await self.develop(
            request,
            **kwargs,
        )

    async def run(
        self,
        request: str,
        **kwargs: Any,
    ) -> FinalEngineeringResult:

        return await self.develop(
            request,
            **kwargs,
        )

    # ============================================================
    # RESUME
    # ============================================================

    async def resume(
        self,
        session_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> FinalEngineeringResult:

        normalized_id = str(
            session_id or ""
        ).strip()

        if not normalized_id:
            return FinalEngineeringResult(
                success=False,
                accepted=False,
                session_id="",
                status="invalid_session_id",
                phase="created",
                error=(
                    "A session_id is required."
                ),
            )

        runtime = (
            self._session_runtime()
        )

        if runtime is not None:
            for method_name in (
                "resume",
                "resume_session",
                "continue_session",
            ):

                method = getattr(
                    runtime,
                    method_name,
                    None,
                )

                if not callable(
                    method
                ):
                    continue

                try:
                    result = method(
                        normalized_id,
                        metadata=metadata,
                    )

                    if inspect.isawaitable(
                        result
                    ):
                        result = await result

                    return self._normalize_result(
                        result,
                        session_id=normalized_id,
                    )

                except TypeError:
                    try:
                        result = method(
                            normalized_id
                        )

                        if inspect.isawaitable(
                            result
                        ):
                            result = await result

                        return self._normalize_result(
                            result,
                            session_id=normalized_id,
                        )

                    except Exception as exc:
                        return FinalEngineeringResult(
                            success=False,
                            accepted=False,
                            session_id=normalized_id,
                            status="resume_failed",
                            phase="failed",
                            error=str(exc),
                        )

                except Exception as exc:
                    logger.exception(
                        "[FinalAutonomousEngineer] "
                        "Session resume failed."
                    )

                    return FinalEngineeringResult(
                        success=False,
                        accepted=False,
                        session_id=normalized_id,
                        status="resume_failed",
                        phase="failed",
                        error=str(exc),
                    )

        return FinalEngineeringResult(
            success=False,
            accepted=False,
            session_id=normalized_id,
            status="resume_unavailable",
            phase="unknown",
            error=(
                "No connected engineering session runtime "
                "supports session resume."
            ),
        )

    # ============================================================
    # STATUS
    # ============================================================

    def status(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:

        runtime = (
            self._session_runtime()
        )

        target = (
            session_id
            or self._active_session_id
        )

        if runtime is not None:

            for method_name in (
                "engineering_status",
                "status",
                "get_status",
            ):

                method = getattr(
                    runtime,
                    method_name,
                    None,
                )

                if not callable(
                    method
                ):
                    continue

                try:

                    if target:
                        try:
                            value = method(
                                target
                            )
                        except TypeError:
                            value = method()
                    else:
                        value = method()

                    if inspect.isawaitable(
                        value
                    ):
                        logger.warning(
                            "[FinalAutonomousEngineer] "
                            "Async status method requires await."
                        )

                        return {
                            "healthy": True,
                            "status": (
                                "async_status_available"
                            ),
                            "session_id": target,
                        }

                    return _serialize(
                        value
                    )

                except Exception:
                    logger.exception(
                        "[FinalAutonomousEngineer] "
                        "Status lookup failed."
                    )

        return {
            "healthy": True,
            "phase1_version": self.VERSION,
            "session_id": target,
            "status": "idle",
            "autonomous_engineer": True,
        }

    # ============================================================
    # HEALTH
    # ============================================================

    def health(
        self,
    ) -> dict[str, Any]:

        orchestrator_health = {}

        health_method = getattr(
            self.orchestrator,
            "health",
            None,
        )

        if callable(
            health_method
        ):
            try:
                orchestrator_health = (
                    _serialize(
                        health_method()
                    )
                )

            except Exception as exc:
                orchestrator_health = {
                    "healthy": False,
                    "error": str(exc),
                }

        return {
            "healthy": bool(
                orchestrator_health.get(
                    "healthy",
                    True,
                )
            ),
            "phase1_final_engineer": True,
            "version": self.VERSION,
            "orchestrator": (
                orchestrator_health
            ),
            "github_push_requires_authorization": True,
            "deployment_requires_authorization": True,
            "production_direct_write": False,
        }

    # ============================================================
    # ORCHESTRATOR
    # ============================================================

    async def _run_orchestrator(
        self,
        request: str,
        *,
        session_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> Any:

        orchestrator = (
            self.orchestrator
        )

        if orchestrator is None:
            raise RuntimeError(
                "Final autonomous engineer has no "
                "engineering orchestrator."
            )

        for method_name in (
            "develop",
            "execute",
            "run",
        ):

            method = getattr(
                orchestrator,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            attempts = (
                lambda: method(
                    request,
                    session_id=session_id,
                    metadata=metadata,
                ),
                lambda: method(
                    request,
                    session_id=session_id,
                ),
                lambda: method(
                    request
                ),
            )

            for attempt in attempts:

                try:
                    result = attempt()

                    if inspect.isawaitable(
                        result
                    ):
                        result = await result

                    return result

                except TypeError:
                    continue

        raise RuntimeError(
            "Engineering orchestrator does not expose "
            "a compatible develop/execute/run method."
        )

    # ============================================================
    # AUTHORITATIVE ORCHESTRATOR CONSTRUCTION
    # ============================================================

    def _build_orchestrator(
        self,
        **services: Any,
    ) -> AuthoritativeEngineeringOrchestrator:
        """
        Construct the authoritative Phase 1 execution spine.

        All authoritative engines are bound to existing Phase 1
        services.

        IMPORTANT:
        No second persistent runtime is created here.
        """

        legacy = self.legacy_runtime

        def component(
            name: str,
            default: Any = None,
        ) -> Any:
            """
            Return an existing Phase 1 runtime component safely.
            """

            if legacy is None:
                return default

            getter = getattr(
                legacy,
                "get",
                None,
            )

            if callable(
                getter
            ):
                try:
                    return getter(
                        name
                    )

                except (
                    KeyError,
                    TypeError,
                    AttributeError,
                ):
                    pass

                except Exception:
                    logger.debug(
                        "[FinalAutonomousEngineer] "
                        "Component lookup failed: %s",
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
                return components.get(
                    name,
                    default,
                )

            return getattr(
                legacy,
                name,
                default,
            )

        # --------------------------------------------------------
        # DEVELOPMENT CONTROLLER
        # --------------------------------------------------------

        development_controller = (
            services.get(
                "development_controller"
            )
            or getattr(
                legacy,
                "development_controller",
                None,
            )
        )

        # --------------------------------------------------------
        # DEVELOPMENT AGENT
        # --------------------------------------------------------

        development_agent = (
            getattr(
                development_controller,
                "agent",
                None,
            )
            if development_controller is not None
            else None
        )

        if development_agent is None:
            development_agent = services.get(
                "development_agent"
            )

        # --------------------------------------------------------
        # REQUIREMENT INTELLIGENCE
        # --------------------------------------------------------

        requirement_intelligence = (
            services.get(
                "requirement_intelligence"
            )
            or getattr(
                development_agent,
                "requirement_intelligence",
                None,
            )
        )

        # --------------------------------------------------------
        # KNOWLEDGE RETRIEVER
        # --------------------------------------------------------

        knowledge_retriever = (
            services.get(
                "knowledge_retriever"
            )
            or component(
                "knowledge_retriever"
            )
        )

        # --------------------------------------------------------
        # VERIFICATION SERVICE
        # --------------------------------------------------------

        verification_service = (
            services.get(
                "verification_service"
            )
            or getattr(
                development_agent,
                "intelligent_verification",
                None,
            )
        )

        # --------------------------------------------------------
        # REPAIR SERVICE
        # --------------------------------------------------------

        repair_service = (
            services.get(
                "repair_service"
            )
            or component(
                "autonomous_repair_loop"
            )
        )

        # --------------------------------------------------------
        # ENGINEERING JUDGMENT
        # --------------------------------------------------------

        judgment_engine = (
            services.get(
                "judgment_engine"
            )
            or getattr(
                development_agent,
                "engineering_judgment",
                None,
            )
        )

        # --------------------------------------------------------
        # AUTHORITATIVE KNOWLEDGE ENGINE
        # --------------------------------------------------------

        knowledge_engine = services.get(
            "knowledge_engine"
        )

        if knowledge_engine is None:

            from .authoritative_engineering_knowledge import (
                AuthoritativeEngineeringKnowledge,
            )

            knowledge_engine = (
                AuthoritativeEngineeringKnowledge(
                    knowledge_database=getattr(
                        legacy,
                        "knowledge_database",
                        None,
                    ),
                    knowledge_graph=getattr(
                        legacy,
                        "knowledge_graph",
                        None,
                    ),
                    knowledge_engine=(
                        knowledge_retriever
                    ),
                    search_engine=component(
                        "search_tool"
                    ),
                    research_engine=component(
                        "research_service"
                    ),
                    memory_engine=getattr(
                        legacy,
                        "memory_engine",
                        None,
                    ),
                )
            )

        # --------------------------------------------------------
        # AUTHORITATIVE REQUIREMENT ENGINE
        # --------------------------------------------------------

        requirement_engine = services.get(
            "requirement_engine"
        )

        if requirement_engine is None:

            from .authoritative_engineering_requirement import (
                AuthoritativeEngineeringRequirement,
            )

            requirement_engine = (
                AuthoritativeEngineeringRequirement(
                    requirement_intelligence=(
                        requirement_intelligence
                    ),
                )
            )

        # --------------------------------------------------------
        # AUTHORITATIVE IMPLEMENTATION ENGINE
        # --------------------------------------------------------

        implementation_engine = services.get(
            "implementation_engine"
        )

        if (
            implementation_engine is None
            and development_controller is not None
        ):

            from .authoritative_implementation import (
                AuthoritativeImplementationEngine,
            )

            implementation_engine = (
                AuthoritativeImplementationEngine(
                    development_controller,
                    development_agent=(
                        development_agent
                    ),
                )
            )

        # --------------------------------------------------------
        # AUTHORITATIVE VERIFICATION ENGINE
        # --------------------------------------------------------

        verification_engine = services.get(
            "verification_engine"
        )

        if verification_engine is None:

            from .authoritative_verification import (
                AuthoritativeVerificationEngine,
            )

            verification_engine = (
                AuthoritativeVerificationEngine(
                    verifier=(
                        verification_service
                    ),
                )
            )

        # --------------------------------------------------------
        # AUTHORITATIVE DIAGNOSIS ENGINE
        # --------------------------------------------------------

        diagnosis_engine = services.get(
            "diagnosis_engine"
        )

        if diagnosis_engine is None:

            from .authoritative_diagnosis import (
                AuthoritativeDiagnosisEngine,
            )

            diagnosis_engine = (
                AuthoritativeDiagnosisEngine()
            )

        # --------------------------------------------------------
        # AUTHORITATIVE RECOVERY ENGINE
        # --------------------------------------------------------

        recovery_engine = services.get(
            "recovery_engine"
        )

        if recovery_engine is None:

            from .authoritative_recovery import (
                AuthoritativeRecoveryEngine,
            )

            recovery_engine = (
                AuthoritativeRecoveryEngine(
                    repair_engine=(
                        repair_service
                    ),
                )
            )

        # --------------------------------------------------------
        # AUTHORITATIVE REPOSITORY / PLANNING / TASK GRAPH
        # --------------------------------------------------------
        # Reuse the DevelopmentAgent's existing read-only repository
        # manager, conservative ChangePlanner, and IntelligentTaskGraph.
        # These are wrapped so the authoritative orchestrator remains the
        # only lifecycle owner and no competing planning state machine is
        # introduced.
        repository_engine = (
            services.get("repository_engine")
            or getattr(development_agent, "repository_manager", None)
        )

        planning_engine = services.get("planning_engine")
        task_graph_engine = services.get("task_graph_engine")

        if planning_engine is None or task_graph_engine is None:
            from .authoritative_engineering_planning import (
                AuthoritativeRepositoryContext,
                AuthoritativePlanningAdapter,
                AuthoritativeTaskGraphAdapter,
            )

            repository_context = AuthoritativeRepositoryContext(
                repository_engine
            )

            if planning_engine is None:
                planning_engine = AuthoritativePlanningAdapter(
                    change_planner=getattr(
                        development_agent, "change_planner", None
                    ),
                    repository_context=repository_context,
                )

            if task_graph_engine is None:
                task_graph_engine = AuthoritativeTaskGraphAdapter(
                    task_graph_engine=getattr(
                        development_agent, "intelligent_task_graph", None
                    ),
                )

        # --------------------------------------------------------
        # AUTHORITATIVE ACCEPTANCE ENGINE
        # --------------------------------------------------------

        acceptance_engine = services.get(
            "acceptance_engine"
        )

        if acceptance_engine is None:

            from .authoritative_acceptance import (
                AuthoritativeAcceptanceEngine,
            )

            acceptance_engine = (
                AuthoritativeAcceptanceEngine(
                    judgment_engine=(
                        judgment_engine
                    ),
                    verification_engine=(
                        verification_engine
                    ),
                )
            )

        # --------------------------------------------------------
        # AUTHORITATIVE EXPERIENCE ENGINE
        # --------------------------------------------------------

        experience_engine = services.get(
            "experience_engine"
        )

        if experience_engine is None:

            from .authoritative_experience import (
                AuthoritativeExperienceEngine,
            )

            experience_engine = (
                AuthoritativeExperienceEngine(
                    knowledge_engine=(
                        knowledge_engine
                    ),
                )
            )

        # --------------------------------------------------------
        # CANONICAL PERSISTENT RUNTIME
        # --------------------------------------------------------

        persistent_runtime = (
            services.get(
                "persistent_runtime"
            )
            or services.get(
                "session_runtime"
            )
            or self.persistent_runtime
        )

        # IMPORTANT:
        #
        # The Phase1PersistentRuntimeAdapter already owns the
        # canonical PersistentEngineeringRuntime.
        #
        # NEVER instantiate another PersistentEngineeringRuntime
        # here.
        #
        # Creating another instance would split:
        #
        #   session state
        #   persistence state
        #   lifecycle state
        #   recovery state
        #
        # between two independent runtime objects.

        persistence = (
            services.get(
                "persistence"
            )
            or getattr(
                persistent_runtime,
                "persistence",
                None,
            )
        )

        # --------------------------------------------------------
        # REPOSITORY ENGINE
        # --------------------------------------------------------

        repository_engine = (
            services.get(
                "repository_engine"
            )
            or getattr(
                development_agent,
                "repository_manager",
                None,
            )
        )

        # --------------------------------------------------------
        # EVIDENCE RECORDER
        # --------------------------------------------------------

        # DO NOT construct EngineeringEvidenceRecorder during
        # bootstrap.
        #
        # Its authoritative constructor requires an active
        # EngineeringSession.
        #
        # The authoritative orchestrator attaches the session
        # evidence registry after the session is created.

        evidence_recorder = services.get(
            "evidence_recorder"
        )

        # --------------------------------------------------------
        # FINAL ORCHESTRATOR SERVICES
        # --------------------------------------------------------

        orchestrator_services = {
            **services,

            "session_runtime": (
                persistent_runtime
            ),

            "persistence": (
                persistence
            ),

            "requirement_engine": (
                requirement_engine
            ),

            "knowledge_engine": (
                knowledge_engine
            ),

            "planning_engine": planning_engine,

            "task_graph_engine": task_graph_engine,

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

            "repository_engine": (
                repository_engine
            ),

            "experience_engine": (
                experience_engine
            ),

            "evidence_recorder": (
                evidence_recorder
            ),
        }

        return (
            AuthoritativeEngineeringOrchestrator(
                **orchestrator_services
            )
        )

    # ============================================================
    # SESSION RUNTIME
    # ============================================================

    def _session_runtime(
        self,
    ) -> Any | None:

        # The authoritative orchestrator owns canonical
        # engineering session state.

        if self.orchestrator is not None and (
            callable(
                getattr(
                    self.orchestrator,
                    "status",
                    None,
                )
            )
            or callable(
                getattr(
                    self.orchestrator,
                    "resume",
                    None,
                )
            )
        ):
            return self.orchestrator

        if self.legacy_runtime is not None:
            return self.legacy_runtime

        runtime = getattr(
            self.orchestrator,
            "session_runtime",
            None,
        )

        if runtime is not None:
            return runtime

        return None

    # ============================================================
    # RESULT NORMALIZATION
    # ============================================================

    def _normalize_result(
        self,
        result: Any,
        *,
        session_id: str | None,
    ) -> FinalEngineeringResult:

        if isinstance(
            result,
            FinalEngineeringResult,
        ):
            return result

        if isinstance(
            result,
            EngineeringOrchestrationResult,
        ):
            return self._from_orchestration_result(
                result,
                session_id=session_id,
            )

        if isinstance(
            result,
            dict,
        ):

            return FinalEngineeringResult(
                success=bool(
                    result.get(
                        "success",
                        False,
                    )
                ),

                accepted=bool(
                    result.get(
                        "accepted",
                        result.get(
                            "is_accepted",
                            False,
                        ),
                    )
                ),

                session_id=str(
                    result.get(
                        "session_id",
                        session_id
                        or "",
                    )
                ),

                status=str(
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
                ),

                phase=str(
                    result.get(
                        "phase",
                        "unknown",
                    )
                ),

                error=(
                    result.get(
                        "error"
                    )
                    or result.get(
                        "reason"
                    )
                ),

                requirement=result.get(
                    "requirement"
                ),

                knowledge=result.get(
                    "knowledge"
                ),

                plan=result.get(
                    "plan"
                ),

                task_graph=result.get(
                    "task_graph"
                ),

                implementation=result.get(
                    "implementation"
                ),

                verification=result.get(
                    "verification"
                ),

                metadata=dict(
                    result.get(
                        "metadata",
                        {},
                    )
                    or {}
                ),
            )

        success = bool(
            getattr(
                result,
                "success",
                False,
            )
        )

        accepted = bool(
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

        return FinalEngineeringResult(
            success=success,

            accepted=accepted,

            session_id=str(
                getattr(
                    result,
                    "session_id",
                    session_id
                    or "",
                )
            ),

            status=str(
                getattr(
                    result,
                    "status",
                    (
                        "completed"
                        if success
                        else "failed"
                    ),
                )
            ),

            phase=str(
                getattr(
                    result,
                    "phase",
                    "unknown",
                )
            ),

            error=(
                getattr(
                    result,
                    "error",
                    None,
                )
                or getattr(
                    result,
                    "reason",
                    None,
                )
            ),

            requirement=getattr(
                result,
                "requirement",
                None,
            ),

            knowledge=getattr(
                result,
                "knowledge",
                None,
            ),

            plan=getattr(
                result,
                "plan",
                None,
            ),

            task_graph=getattr(
                result,
                "task_graph",
                None,
            ),

            implementation=getattr(
                result,
                "implementation",
                None,
            ),

            verification=getattr(
                result,
                "verification",
                None,
            ),

            metadata=dict(
                getattr(
                    result,
                    "metadata",
                    {},
                )
                or {}
            ),
        )

    def _from_orchestration_result(
        self,
        result: EngineeringOrchestrationResult,
        *,
        session_id: str | None,
    ) -> FinalEngineeringResult:

        return FinalEngineeringResult(
            success=result.success,

            accepted=result.accepted,

            session_id=(
                result.session_id
                or session_id
                or ""
            ),

            status=result.status,

            phase=result.phase,

            error=result.error,

            requirement=result.requirement,

            knowledge=result.knowledge,

            plan=result.plan,

            task_graph=result.task_graph,

            implementation=result.implementation,

            verification=result.verification,

            metadata=dict(
                result.metadata
            ),
        )

    # ============================================================
    # COMPATIBILITY
    # ============================================================

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:

        if key in {
            "final_autonomous_engineer",
            "autonomous_engineer",
            "engineering_orchestrator",
        }:

            if key == "engineering_orchestrator":
                return self.orchestrator

            return self

        if self.legacy_runtime is not None:

            getter = getattr(
                self.legacy_runtime,
                "get",
                None,
            )

            if callable(
                getter
            ):

                try:
                    return getter(
                        key,
                        default,
                    )

                except TypeError:

                    try:
                        return getter(
                            key
                        )

                    except Exception:
                        pass

        return default

    def __getattr__(
        self,
        name: str,
    ) -> Any:

        legacy = object.__getattribute__(
            self,
            "legacy_runtime",
        )

        if legacy is not None:

            try:
                return getattr(
                    legacy,
                    name,
                )

            except AttributeError:
                pass

        raise AttributeError(
            name
        )
