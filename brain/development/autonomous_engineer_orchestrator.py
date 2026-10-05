from __future__ import annotations

"""
Canonical Phase 1 autonomous-engineering integration spine.

This module is the execution coordinator, not another development engine.

Every engineering request is normalized into one authoritative lifecycle:

    request
      -> requirement
      -> knowledge/repository context
      -> adaptive plan
      -> authoritative task graph
      -> implementation
      -> verification
      -> diagnosis
      -> recovery/repair
      -> retest
      -> reassessment
      -> acceptance
      -> experience

The existing DevelopmentController/DevelopmentAgent remains the actual
implementation engine.  This coordinator connects the existing services
through the authoritative contracts and lifecycle.
"""

import inspect
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from .authoritative_acceptance import AuthoritativeAcceptanceEngine
from .authoritative_diagnosis import AuthoritativeDiagnosisEngine
from .authoritative_engineering_lifecycle_runtime import (
    AuthoritativeEngineeringLifecycleRuntime,
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
from .authoritative_recovery import AuthoritativeRecoveryEngine
from .authoritative_verification import (
    AuthoritativeVerificationEngine,
)
from .contracts.engineering_acceptance import (
    AcceptanceCriterion,
    AcceptanceRequest,
)
from .contracts.engineering_diagnosis import DiagnosisRequest
from .contracts.engineering_implementation import (
    ImplementationRequest,
)
from .contracts.engineering_recovery import RecoveryRequest
from .contracts.engineering_task_graph import (
    EngineeringTask,
    EngineeringTaskGraph,
    EngineeringTaskKind,
)
from .contracts.engineering_verification import (
    VerificationRequest,
)
from .contracts.engineering_plan import (
    EngineeringPlanStep,
    AdaptiveEngineeringPlan as ContractAdaptivePlan,
)
from .adaptive_engineering_plan import (
    AdaptiveEngineeringPlan as LegacyAdaptivePlan,
)

logger = logging.getLogger("aria")


@dataclass(frozen=True)
class EngineeringOrchestrationResult:
    success: bool
    accepted: bool
    session_id: str
    status: str
    phase: str
    requirement: Any | None = None
    knowledge: Any | None = None
    plan: Any | None = None
    task_graph: Any | None = None
    implementation: Any | None = None
    verification: Any | None = None
    diagnosis: Any | None = None
    recovery: Any | None = None
    acceptance: Any | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "accepted": self.accepted,
            "session_id": self.session_id,
            "status": self.status,
            "phase": self.phase,
            "requirement": _serialize(self.requirement),
            "knowledge": _serialize(self.knowledge),
            "plan": _serialize(self.plan),
            "task_graph": _serialize(self.task_graph),
            "implementation": _serialize(self.implementation),
            "verification": _serialize(self.verification),
            "diagnosis": _serialize(self.diagnosis),
            "recovery": _serialize(self.recovery),
            "acceptance": _serialize(self.acceptance),
            "error": self.error,
            "metadata": _serialize(self.metadata),
        }


class AuthoritativeEngineeringOrchestrator:
    """
    Single authoritative Phase 1 execution spine.

    The orchestrator owns sequencing and contract translation.  It does
    not replace the existing development engine.
    """

    VERSION = "PHASE1-INTEGRATED-ENGINEERING-SPINE-20261004"

    def __init__(
        self,
        *,
        session_runtime: Any | None = None,
        persistence: Any | None = None,
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
        experience_engine: Any | None = None,
        evidence_recorder: Any | None = None,
        max_recovery_attempts: int = 2,
    ) -> None:
        self.session_runtime = session_runtime
        self.persistence = persistence
        self.requirement_engine = requirement_engine
        self.knowledge_engine = knowledge_engine
        self.planning_engine = planning_engine
        self.task_graph_engine = task_graph_engine
        self.implementation_engine = implementation_engine
        self.verification_engine = verification_engine
        self.diagnosis_engine = diagnosis_engine
        self.recovery_engine = recovery_engine
        self.acceptance_engine = acceptance_engine
        self.repository_engine = repository_engine
        self.experience_engine = experience_engine
        self.evidence_recorder = evidence_recorder
        self.max_recovery_attempts = max(1, min(int(max_recovery_attempts), 5))

        self._active_session: Any | None = None
        self._active_requirement: Any | None = None
        self._active_knowledge: Any | None = None
        self._active_plan: Any | None = None
        self._active_task_graph: Any | None = None
        self._active_implementation: Any | None = None
        self._active_verification: Any | None = None
        self._active_diagnosis: Any | None = None
        self._active_recovery: Any | None = None
        self._active_acceptance: Any | None = None
        self._sessions: dict[str, Any] = {}

    async def develop(
        self,
        request: str,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EngineeringOrchestrationResult:
        raw_request = str(request or "").strip()
        if not raw_request:
            return self._failure("", "empty_request", "Engineering request cannot be empty.")

        session = await self._create_session(
            raw_request,
            session_id=session_id,
            metadata=metadata,
        )
        self._active_session = session
        self._sessions[self._session_id(session, session_id)] = session

        if self.evidence_recorder is None:
            self.evidence_recorder = getattr(session, "evidence", None)

        sid = self._session_id(session, session_id)

        try:
            self._mark(session, "mark_created", "Engineering session created.")
            self._record("orchestration", "Engineering orchestration started.", {"request": raw_request})

            # ---------------------------------------------------------
            # Requirement
            # ---------------------------------------------------------
            self._mark(session, "mark_understanding", "Resolving requirement and permissions.")
            requirement_result = await self._resolve_requirement(raw_request, metadata)
            if not self._success(requirement_result):
                return self._blocked(
                    session,
                    "requirement_resolution_failed",
                    self._error(requirement_result) or "Requirement resolution failed.",
                    requirement=requirement_result,
                )

            requirement = self._extract(requirement_result, "requirement", requirement_result)
            self._active_requirement = requirement

            if not self._ready(requirement_result):
                return self._blocked(
                    session,
                    "requirement_unclear",
                    "Requirement is not sufficiently specified for safe planning.",
                    requirement=requirement,
                )

            self._record("requirement", "Requirement normalized.", requirement)

            # ---------------------------------------------------------
            # Knowledge + repository context
            # ---------------------------------------------------------
            knowledge = await self._gather_knowledge(
                raw_request,
                requirement=requirement,
                metadata=metadata,
            )
            self._active_knowledge = knowledge
            self._record("knowledge", "Engineering knowledge gathered.", knowledge)

            # ---------------------------------------------------------
            # Plan
            # ---------------------------------------------------------
            self._mark(session, "mark_planning", "Building adaptive engineering plan.")
            plan_result = await self._build_plan(requirement, knowledge, metadata)
            if not self._success(plan_result):
                return self._blocked(
                    session,
                    "planning_failed",
                    self._error(plan_result) or "Planning failed.",
                    requirement=requirement,
                    knowledge=knowledge,
                )

            plan = self._extract(plan_result, "plan", plan_result)
            self._active_plan = plan
            self._record("plan", "Adaptive engineering plan prepared.", plan)

            # ---------------------------------------------------------
            # Task graph
            # ---------------------------------------------------------
            graph_result = await self._build_task_graph(
                requirement,
                plan,
                knowledge,
                metadata,
            )
            if not self._success(graph_result):
                return self._blocked(
                    session,
                    "task_graph_failed",
                    self._error(graph_result) or "Task graph construction failed.",
                    requirement=requirement,
                    knowledge=knowledge,
                    plan=plan,
                )

            task_graph = self._extract(
                graph_result,
                "task_graph",
                self._extract(graph_result, "graph", graph_result),
            )
            self._active_task_graph = task_graph
            self._graph_complete("understand")
            self._graph_complete("research")
            self._graph_complete("plan")
            self._mark(session, "mark_graph_ready", "Authoritative task graph prepared.")
            self._record("task_graph", "Task graph prepared.", task_graph)

            # ---------------------------------------------------------
            # Implementation
            # ---------------------------------------------------------
            self._mark(session, "mark_implementing", "Autonomous implementation started.")
            implementation = await self._implement(
                sid,
                raw_request,
                requirement,
                plan,
                task_graph,
                knowledge,
                metadata,
            )
            self._active_implementation = implementation
            if self._success(implementation):
                self._graph_complete("implement")
            self._record("implementation", "Implementation completed or failed.", implementation)

            if not self._success(implementation):
                return await self._recover_until_verified(
                    session,
                    sid,
                    raw_request,
                    requirement,
                    plan,
                    task_graph,
                    knowledge,
                    implementation,
                    metadata,
                )

            # ---------------------------------------------------------
            # Verification / acceptance
            # ---------------------------------------------------------
            verified = await self._verify(
                sid,
                raw_request,
                requirement,
                task_graph,
                implementation,
                metadata,
            )
            self._active_verification = verified
            if self._verification_passed(verified):
                self._graph_complete("verify")
            self._record("verification", "Implementation verification completed.", verified)

            if not self._verification_passed(verified):
                return await self._recover_until_verified(
                    session,
                    sid,
                    raw_request,
                    requirement,
                    plan,
                    task_graph,
                    knowledge,
                    implementation,
                    metadata,
                    initial_verification=verified,
                )

            return await self._accept(
                session,
                sid,
                raw_request,
                requirement,
                implementation,
                verified,
                metadata,
                plan=plan,
                task_graph=task_graph,
                knowledge=knowledge,
            )

        except Exception as exc:
            logger.exception("[AuthoritativeEngineeringOrchestrator] Integrated lifecycle failed.")
            self._record("failure", "Unhandled orchestration failure.", {"error": str(exc)})
            self._mark(session, "mark_failed", str(exc))
            return self._failure(
                sid,
                "engineering_failed",
                f"{type(exc).__name__}: {exc}",
                requirement=self._active_requirement,
                knowledge=self._active_knowledge,
                plan=self._active_plan,
                task_graph=self._active_task_graph,
                implementation=self._active_implementation,
                verification=self._active_verification,
            )

    async def resume(
        self,
        session_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> EngineeringOrchestrationResult:
        """
        Resume a persisted engineering session.

        A resume never invents a new requirement.  If a live in-memory
        session exists, its authoritative state is returned.  If the
        persistence layer can restore a session, the restored state is
        returned for the higher-level runtime to continue safely.
        """
        sid = str(session_id or "").strip()
        if not sid:
            return self._failure("", "invalid_session_id", "A session_id is required.")

        session = self._sessions.get(sid)
        if session is not None:
            return EngineeringOrchestrationResult(
                success=False,
                accepted=False,
                session_id=sid,
                status="resumable",
                phase=self._phase(session),
                requirement=getattr(session, "requirement", None),
                metadata={"resume_required": True, "integration_version": self.VERSION},
            )

        if self.persistence is not None:
            for name in ("load_session", "load", "restore_session", "recover"):
                method = getattr(self.persistence, name, None)
                if not callable(method):
                    continue
                try:
                    value = method(sid)
                    if inspect.isawaitable(value):
                        value = await value
                    if value is not None:
                        return EngineeringOrchestrationResult(
                            success=False,
                            accepted=False,
                            session_id=sid,
                            status="restored",
                            phase="unknown",
                            requirement=value,
                            metadata={"resume_required": True, "integration_version": self.VERSION},
                        )
                except Exception:
                    logger.debug("Could not restore engineering session.", exc_info=True)

        return self._failure(
            sid,
            "session_not_found",
            f"Engineering session '{sid}' was not found.",
        )

    def status(self, session_id: str | None = None) -> dict[str, Any]:
        sid = str(session_id or "")
        session = self._sessions.get(sid) if sid else self._active_session
        if session is None:
            return {
                "healthy": True,
                "active": False,
                "session_id": sid or None,
                "status": "idle",
                "version": self.VERSION,
            }

        lifecycle = getattr(session, "lifecycle", None)
        snapshot = None
        if lifecycle is not None:
            for name in ("snapshot", "to_dict"):
                method = getattr(lifecycle, name, None)
                if callable(method):
                    try:
                        snapshot = method()
                        break
                    except Exception:
                        pass

        return {
            "healthy": True,
            "active": True,
            "session_id": self._session_id(session, sid or None),
            "phase": self._phase(session),
            "status": "active",
            "snapshot": _serialize(snapshot),
            "version": self.VERSION,
        }

    # ------------------------------------------------------------------
    # Requirement
    # ------------------------------------------------------------------

    async def _resolve_requirement(self, request: str, metadata: dict[str, Any] | None) -> Any:
        engine = self.requirement_engine
        if engine is None:
            return {
                "success": False,
                "error": "No authoritative requirement engine is connected.",
            }
        return await self._call(engine, ("resolve", "analyze", "understand"), request, metadata=metadata)

    # ------------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------------

    async def _gather_knowledge(
        self,
        request: str,
        *,
        requirement: Any,
        metadata: dict[str, Any] | None,
    ) -> Any:
        # Repository inspection is a mandatory context input for engineering
        # planning. RepositoryManager is read-only, so this stage cannot mutate
        # the production checkout.
        repository_context = None
        repository_engine = self.repository_engine
        if repository_engine is not None:
            inspect_method = getattr(repository_engine, "inspect", None)
            if callable(inspect_method):
                repository_path = (metadata or {}).get("repository_path")
                if not repository_path:
                    repository_path = os.getcwd()
                try:
                    repository_snapshot = inspect_method(repository_path)
                    repository_context = {
                        "success": True,
                        "repository_path": str(repository_path),
                        "snapshot": repository_snapshot,
                        "source": "repository_manager",
                    }
                except Exception as exc:
                    return {
                        "success": False,
                        "error": f"Repository inspection failed: {type(exc).__name__}: {exc}",
                    }

        engine = self.knowledge_engine
        if engine is None:
            return {
                "success": True,
                "items": [],
                "source": "no_optional_knowledge_service",
                "repository_context": repository_context,
            }

        knowledge = await self._call(
            engine,
            ("gather", "retrieve", "research"),
            request,
            requirement=requirement,
            repository_context=repository_context,
            metadata=metadata,
        )

        return {
            "success": self._success(knowledge),
            "knowledge": knowledge,
            "repository_context": repository_context,
            "items": (
                self._extract(knowledge, "items", ())
                if knowledge is not None
                else ()
            ),
            "source": "authoritative_knowledge_repository_bridge",
        }

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    async def _build_plan(
        self,
        requirement: Any,
        knowledge: Any,
        metadata: dict[str, Any] | None,
    ) -> Any:
        if self.planning_engine is not None:
            return await self._call(
                self.planning_engine,
                ("build", "create", "plan", "generate", "create_plan"),
                requirement,
                knowledge=knowledge,
                metadata=metadata,
            )

        objective = self._text(requirement, "objective", self._text(requirement, "goal", "Implement the requested engineering change."))
        criteria = self._strings(requirement, "acceptance_criteria")
        paths = self._strings(requirement, "requested_paths")

        steps = (
            EngineeringPlanStep(
                step_id="understand",
                title="Understand requirement",
                objective="Normalize the user requirement, constraints, permissions, and acceptance criteria.",
                verification=("requirement_resolution",),
            ),
            EngineeringPlanStep(
                step_id="research",
                title="Research and inspect",
                objective="Gather relevant repository and knowledge evidence before implementation.",
                dependencies=("understand",),
                verification=("knowledge_evidence", "repository_context"),
            ),
            EngineeringPlanStep(
                step_id="implement",
                title="Implement",
                objective=objective,
                dependencies=("research",),
                affected_paths=paths,
                verification=("static_validation", "behavioral_tests"),
            ),
            EngineeringPlanStep(
                step_id="verify",
                title="Verify",
                objective="Verify the implementation against the requirement and acceptance criteria.",
                dependencies=("implement",),
                affected_paths=paths,
                verification=("implementation", "isolation", "static", "behavioral", "acceptance"),
            ),
            EngineeringPlanStep(
                step_id="accept",
                title="Accept",
                objective="Accept only when all required evidence and constraints are satisfied.",
                dependencies=("verify",),
                verification=("acceptance",),
            ),
        )

        plan = ContractAdaptivePlan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            objective=objective,
            steps=steps,
            assumptions=(),
            risks=(),
            confidence=0.85,
            metadata={
                "integration": self.VERSION,
                "requested_paths": list(paths),
                "acceptance_criteria": list(criteria),
            },
        )
        return {"success": True, "plan": plan}

    # ------------------------------------------------------------------
    # Task graph
    # ------------------------------------------------------------------

    async def _build_task_graph(
        self,
        requirement: Any,
        plan: Any,
        knowledge: Any,
        metadata: dict[str, Any] | None,
    ) -> Any:
        if self.task_graph_engine is not None:
            return await self._call(
                self.task_graph_engine,
                ("build", "create", "generate", "build_graph"),
                requirement,
                plan=plan,
                knowledge=knowledge,
                metadata=metadata,
            )

        objective = self._text(requirement, "objective", "Implement the requested engineering change.")
        paths = self._strings(requirement, "requested_paths")

        tasks = (
            EngineeringTask(
                task_id="understand",
                kind=EngineeringTaskKind.UNDERSTAND,
                title="Understand requirement",
                objective="Normalize and validate the engineering requirement.",
            ),
            EngineeringTask(
                task_id="research",
                kind=EngineeringTaskKind.RESEARCH,
                title="Research and inspect",
                objective="Gather repository and knowledge evidence.",
                dependencies=("understand",),
            ),
            EngineeringTask(
                task_id="plan",
                kind=EngineeringTaskKind.PLAN,
                title="Create adaptive plan",
                objective="Create the smallest coherent implementation plan.",
                dependencies=("research",),
            ),
            EngineeringTask(
                task_id="implement",
                kind=EngineeringTaskKind.IMPLEMENT,
                title="Implement requirement",
                objective=objective,
                dependencies=("plan",),
                affected_paths=paths,
                verification=("static_validation", "behavioral_tests"),
            ),
            EngineeringTask(
                task_id="verify",
                kind=EngineeringTaskKind.VERIFY,
                title="Verify implementation",
                objective="Collect independent verification evidence.",
                dependencies=("implement",),
                affected_paths=paths,
                verification=("implementation", "isolation", "static", "behavioral"),
            ),
            EngineeringTask(
                task_id="accept",
                kind=EngineeringTaskKind.ACCEPT,
                title="Accept requirement",
                objective="Accept only with complete authoritative evidence.",
                dependencies=("verify",),
                verification=("acceptance",),
            ),
        )

        graph = EngineeringTaskGraph(
            graph_id=f"graph-{uuid.uuid4().hex[:12]}",
            tasks=tasks,
            confidence=0.90,
            metadata={"integration": self.VERSION},
        )
        return {"success": True, "task_graph": graph}

    # ------------------------------------------------------------------
    # Implementation
    # ------------------------------------------------------------------

    async def _implement(
        self,
        session_id: str,
        raw_request: str,
        requirement: Any,
        plan: Any,
        task_graph: Any,
        knowledge: Any,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = self.implementation_engine
        if engine is None:
            return {"success": False, "error": "No authoritative implementation engine is connected."}

        request = ImplementationRequest(
            session_id=session_id,
            task_id="implement",
            requirement=raw_request,
            objective=self._text(requirement, "objective", raw_request),
            affected_paths=self._strings(requirement, "requested_paths"),
            constraints=self._strings(requirement, "constraints"),
            acceptance_criteria=self._strings(requirement, "acceptance_criteria"),
            evidence_required=("isolated_workspace", "static_validation", "behavioral_tests"),
            verification=("static_validation", "behavioral_tests", "acceptance"),
            workspace_id=None,
            metadata={
                **(metadata or {}),
                "plan": _serialize(plan),
                "task_graph": _serialize(task_graph),
                "knowledge": _serialize(knowledge),
            },
        )
        return await self._call_contract(engine, "execute", request)

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    async def _verify(
        self,
        session_id: str,
        raw_request: str,
        requirement: Any,
        task_graph: Any,
        implementation: Any,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = self.verification_engine
        if engine is None:
            return {"success": False, "error": "No authoritative verification engine is connected."}

        request = VerificationRequest(
            session_id=session_id,
            task_id="verify",
            requirement=raw_request,
            acceptance_criteria=self._strings(requirement, "acceptance_criteria"),
            changed_paths=self._changed_paths(implementation),
            workspace_id=self._workspace_id(implementation),
            implementation_evidence=self._implementation_evidence(implementation),
            metadata={
                **(metadata or {}),
                "task_graph": _serialize(task_graph),
            },
        )
        return await self._call_contract(
            engine,
            "verify",
            request,
            implementation_result=implementation,
        )

    # ------------------------------------------------------------------
    # Recovery / diagnosis / retest
    # ------------------------------------------------------------------

    async def _recover_until_verified(
        self,
        session: Any,
        session_id: str,
        raw_request: str,
        requirement: Any,
        plan: Any,
        task_graph: Any,
        knowledge: Any,
        implementation: Any,
        metadata: dict[str, Any] | None,
        *,
        initial_verification: Any | None = None,
    ) -> EngineeringOrchestrationResult:
        verification = initial_verification

        for attempt in range(self.max_recovery_attempts):
            self._mark(session, "mark_diagnosing", f"Diagnosing engineering failure, attempt {attempt + 1}.")
            diagnosis = await self._diagnose(
                session_id,
                raw_request,
                requirement,
                implementation,
                verification,
                metadata,
            )
            self._active_diagnosis = diagnosis
            self._record("diagnosis", "Root-cause diagnosis completed.", diagnosis)

            if not self._diagnosis_success(diagnosis):
                self._mark(session, "mark_failed", self._error(diagnosis) or "Diagnosis failed.")
                return self._failure(
                    session_id,
                    "diagnosis_failed",
                    self._error(diagnosis) or "Root-cause diagnosis failed.",
                    requirement=requirement,
                    knowledge=knowledge,
                    plan=plan,
                    task_graph=task_graph,
                    implementation=implementation,
                    verification=verification,
                    diagnosis=diagnosis,
                )

            self._mark(session, "mark_recovering", f"Attempting recovery {attempt + 1}.")
            recovery = await self._recover(
                session_id,
                raw_request,
                requirement,
                diagnosis,
                metadata,
            )
            self._active_recovery = recovery
            self._record("recovery", "Recovery operation completed.", recovery)

            if not self._recovery_success(recovery):
                self._mark(session, "mark_reassessing", "Recovery did not produce a verified result.")
                if attempt + 1 >= self.max_recovery_attempts:
                    self._mark(session, "mark_failed", self._error(recovery) or "Recovery exhausted.")
                    return self._failure(
                        session_id,
                        "recovery_exhausted",
                        self._error(recovery) or "Recovery exhausted without verified recovery.",
                        requirement=requirement,
                        knowledge=knowledge,
                        plan=plan,
                        task_graph=task_graph,
                        implementation=implementation,
                        verification=verification,
                        diagnosis=diagnosis,
                        recovery=recovery,
                    )
                continue

            # A repair is never considered recovered until a fresh
            # verification is performed.
            self._mark(session, "mark_retesting", "Running fresh verification after recovery.")
            implementation = self._recovery_implementation(recovery, implementation)

            verification = await self._verify(
                session_id,
                raw_request,
                requirement,
                task_graph,
                implementation,
                metadata,
            )
            self._active_implementation = implementation
            self._active_verification = verification
            self._record("retest", "Fresh verification completed after recovery.", verification)

            if self._verification_passed(verification):
                self._mark(session, "mark_reassessing", "Recovery passed fresh verification.")
                return await self._accept(
                    session,
                    session_id,
                    raw_request,
                    requirement,
                    implementation,
                    verification,
                    metadata,
                    plan=plan,
                    task_graph=task_graph,
                    knowledge=knowledge,
                    diagnosis=diagnosis,
                    recovery=recovery,
                )

        self._mark(session, "mark_failed", "Bounded recovery attempts exhausted.")
        return self._failure(
            session_id,
            "recovery_exhausted",
            "Bounded autonomous recovery attempts were exhausted.",
            requirement=requirement,
            knowledge=knowledge,
            plan=plan,
            task_graph=task_graph,
            implementation=implementation,
            verification=verification,
        )

    async def _diagnose(
        self,
        session_id: str,
        raw_request: str,
        requirement: Any,
        implementation: Any,
        verification: Any,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = self.diagnosis_engine
        if engine is None:
            return {"success": False, "error": "No authoritative diagnosis engine is connected."}

        observed = self._error(verification) or self._error(implementation) or "Engineering verification failed."
        request = DiagnosisRequest(
            session_id=session_id,
            task_id="diagnose",
            requirement=raw_request,
            observed_failure=observed,
            changed_paths=self._changed_paths(implementation),
            verification_status=self._status(verification),
            metadata={
                **(metadata or {}),
                "implementation": _serialize(implementation),
                "verification": _serialize(verification),
                "requirement": _serialize(requirement),
            },
        )
        return await self._call_contract(engine, "diagnose", request)

    async def _recover(
        self,
        session_id: str,
        raw_request: str,
        requirement: Any,
        diagnosis: Any,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = self.recovery_engine
        if engine is None:
            return {"success": False, "error": "No authoritative recovery engine is connected."}

        request = RecoveryRequest(
            session_id=session_id,
            task_id="recover",
            requirement=raw_request,
            failure=self._error(diagnosis) or "Verification failed.",
            diagnosis=_as_mapping(diagnosis),
            affected_paths=self._strings(requirement, "requested_paths"),
            constraints=self._strings(requirement, "constraints"),
            acceptance_criteria=self._strings(requirement, "acceptance_criteria"),
            metadata=dict(metadata or {}),
        )
        return await self._call_contract(engine, "recover", request)

    # ------------------------------------------------------------------
    # Acceptance
    # ------------------------------------------------------------------

    async def _accept(
        self,
        session: Any,
        session_id: str,
        raw_request: str,
        requirement: Any,
        implementation: Any,
        verification: Any,
        metadata: dict[str, Any] | None,
        *,
        plan: Any,
        task_graph: Any,
        knowledge: Any,
        diagnosis: Any | None = None,
        recovery: Any | None = None,
    ) -> EngineeringOrchestrationResult:
        self._mark(session, "mark_accepting", "Evaluating authoritative acceptance.")

        engine = self.acceptance_engine
        if engine is None:
            self._mark(session, "mark_failed", "No acceptance engine is connected.")
            return self._failure(
                session_id,
                "acceptance_engine_missing",
                "No authoritative acceptance engine is connected.",
                requirement=requirement,
                knowledge=knowledge,
                plan=plan,
                task_graph=task_graph,
                implementation=implementation,
                verification=verification,
            )

        criteria = tuple(
            AcceptanceCriterion(
                criterion_id=f"criterion-{index + 1}",
                description=value,
                required=True,
            )
            for index, value in enumerate(
                self._strings(requirement, "acceptance_criteria")
            )
        )

        request = AcceptanceRequest(
            session_id=session_id,
            requirement=raw_request,
            objective=self._text(requirement, "objective", raw_request),
            criteria=criteria,
            verification_status=self._status(verification),
            verification_findings=tuple(
                self._findings(verification)
            ),
            evidence=(
                self._evidence_for_acceptance(
                    implementation,
                    verification,
                    diagnosis,
                    recovery,
                )
            ),
            implementation_summary=self._summary(implementation),
            changed_paths=self._changed_paths(implementation),
            protected_paths=self._strings(requirement, "protected_paths"),
            workspace_id=self._workspace_id(implementation),
            constraints=self._strings(requirement, "constraints"),
            forbidden_actions=self._strings(requirement, "forbidden_actions"),
            metadata=dict(metadata or {}),
        )

        acceptance = await self._call_contract(engine, "evaluate", request)
        self._active_acceptance = acceptance
        self._record("acceptance", "Authoritative acceptance evaluated.", acceptance)

        accepted = self._accepted(acceptance)

        # Learning is downstream of evidence.  Historical experience
        # never participates in the acceptance decision itself.
        if self.experience_engine is not None:
            try:
                learner = getattr(
                    self.experience_engine,
                    "learn_from_session",
                    None,
                )
                if callable(learner):
                    learned = learner(
                        session=getattr(session, "session", session),
                        outcome={
                            "success": True,
                            "accepted": accepted,
                            "status": "accepted" if accepted else "acceptance_failed",
                        },
                        verification=verification,
                        diagnosis=diagnosis,
                        recovery=recovery,
                        acceptance=acceptance,
                    )
                    if inspect.isawaitable(learned):
                        await learned
                    self._record(
                        "experience",
                        "Engineering experience recorded.",
                        learned,
                    )
            except Exception:
                logger.debug(
                    "Experience recording failed; current execution remains authoritative.",
                    exc_info=True,
                )

        if accepted:
            try:
                marker = getattr(session, "mark_accepted", None)
                if callable(marker):
                    marker(
                        reason="Requirement accepted with explicit acceptance evidence.",
                        evidence=_serialize(acceptance),
                    )
                else:
                    self._mark(
                        session,
                        "mark_accepted",
                        "Requirement accepted with explicit acceptance evidence.",
                    )
            except Exception as exc:
                logger.exception(
                    "Authoritative lifecycle could not enter ACCEPTED."
                )
                return self._failure(
                    session_id,
                    "acceptance_transition_failed",
                    str(exc),
                    requirement=requirement,
                    knowledge=knowledge,
                    plan=plan,
                    task_graph=task_graph,
                    implementation=implementation,
                    verification=verification,
                    acceptance=acceptance,
                )

            self._graph_complete("accept")
            return EngineeringOrchestrationResult(
                success=True,
                accepted=True,
                session_id=session_id,
                status="accepted",
                phase=self._phase(session),
                requirement=requirement,
                knowledge=knowledge,
                plan=plan,
                task_graph=task_graph,
                implementation=implementation,
                verification=verification,
                diagnosis=diagnosis,
                recovery=recovery,
                acceptance=acceptance,
                metadata={"integration_version": self.VERSION},
            )

        self._mark(session, "mark_reassessing", "Acceptance criteria were not satisfied.")
        return self._failure(
            session_id,
            "acceptance_failed",
            self._error(acceptance) or "Authoritative acceptance did not pass.",
            requirement=requirement,
            knowledge=knowledge,
            plan=plan,
            task_graph=task_graph,
            implementation=implementation,
            verification=verification,
            diagnosis=diagnosis,
            recovery=recovery,
            acceptance=acceptance,
        )

    def _graph_complete(self, task_id: str) -> None:
        graph = self._active_task_graph
        if graph is None:
            return
        try:
            graph = graph.mark_completed(task_id)
            self._active_task_graph = graph
            self._record(
                "task",
                f"Task '{task_id}' completed.",
                graph.task(task_id),
            )
        except Exception:
            logger.debug(
                "Could not update authoritative task graph for %s.",
                task_id,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Session / lifecycle
    # ------------------------------------------------------------------

    async def _create_session(
        self,
        request: str,
        *,
        session_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> Any:
        if self.session_runtime is not None:
            for name in ("create_session", "start_session", "create", "start"):
                method = getattr(self.session_runtime, name, None)
                if not callable(method):
                    continue
                for kwargs in (
                    {"session_id": session_id, "metadata": metadata},
                    {"metadata": metadata},
                    {},
                ):
                    try:
                        value = method(request, **kwargs)
                        if inspect.isawaitable(value):
                            value = await value
                        return value
                    except TypeError:
                        continue

        # The fallback is not a second state machine: it is the same
        # authoritative lifecycle runtime used by the persistent layer.
        return AuthoritativeEngineeringLifecycleRuntime(
            persistence=self.persistence,
            session_id=session_id,
            requirement=request,
            metadata=metadata,
        )

    def _mark(self, session: Any, method_name: str, reason: str) -> None:
        target = getattr(session, method_name, None)
        if callable(target):
            try:
                target(reason=reason)
                return
            except TypeError:
                try:
                    target()
                    return
                except Exception:
                    pass

        lifecycle = getattr(session, "lifecycle", None)
        target = getattr(lifecycle, method_name, None) if lifecycle is not None else None
        if callable(target):
            try:
                target(reason=reason)
            except TypeError:
                target()

    # ------------------------------------------------------------------
    # Generic invocation
    # ------------------------------------------------------------------

    async def _call(
        self,
        service: Any,
        method_names: tuple[str, ...],
        primary: Any,
        **kwargs: Any,
    ) -> Any:
        for name in method_names:
            method = getattr(service, name, None)
            if not callable(method):
                continue

            attempts = (
                lambda: method(primary, **kwargs),
                lambda: method(primary),
                lambda: method(**kwargs),
            )

            for attempt in attempts:
                try:
                    value = attempt()
                    if inspect.isawaitable(value):
                        value = await value
                    return value
                except TypeError:
                    continue

        return {"success": False, "error": f"{type(service).__name__} exposes no compatible method."}

    async def _call_contract(self, service: Any, method_name: str, request: Any, **kwargs: Any) -> Any:
        method = getattr(service, method_name, None)
        if not callable(method):
            return {"success": False, "error": f"{type(service).__name__}.{method_name} is unavailable."}

        try:
            value = method(request, **kwargs)
        except TypeError:
            value = method(request)

        if inspect.isawaitable(value):
            value = await value
        return value

    # ------------------------------------------------------------------
    # Result helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _success(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, dict):
            return bool(value.get("success", False))
        return bool(getattr(value, "success", False))

    @staticmethod
    def _accepted(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, dict):
            return bool(value.get("accepted", value.get("is_accepted", False)))
        return bool(getattr(value, "accepted", getattr(value, "is_accepted", False)))

    @staticmethod
    def _diagnosis_success(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, dict):
            if "success" in value:
                return bool(value.get("success"))
            decision = value.get("decision")
            return bool(
                isinstance(decision, dict)
                and (
                    decision.get("has_root_cause")
                    or decision.get("repairable")
                )
            )
        return bool(
            getattr(value, "has_root_cause", False)
            or getattr(value, "repairable", False)
        )

    @staticmethod
    def _recovery_success(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, dict):
            status = str(value.get("status", "")).lower()
            return bool(value.get("success", False)) or status in {
                "repairing",
                "retesting",
                "recovered",
            }
        if bool(getattr(value, "recovered", False)):
            return True
        decision = getattr(value, "decision", None)
        status = getattr(decision, "status", "") if decision is not None else ""
        status = getattr(status, "value", status)
        return str(status).lower() in {
            "repairing",
            "retesting",
            "recovered",
        }

    @staticmethod
    def _verification_passed(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, dict):
            status = str(value.get("status", "")).lower()
            return bool(value.get("success", False)) and status in {"passed", "verified", "accepted", "completed"}
        if bool(getattr(value, "passed", False)):
            return True
        status = getattr(value, "status", "")
        if not status:
            decision = getattr(value, "decision", None)
            status = getattr(decision, "status", "") if decision is not None else ""
        status = getattr(status, "value", status)
        return bool(getattr(value, "success", False)) and str(status).lower() in {
            "passed", "verified", "accepted", "completed"
        }

    @staticmethod
    def _error(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get("error") or value.get("reason") or value.get("message")
        return getattr(value, "error", None) or getattr(value, "reason", None) or getattr(value, "message", None)

    @staticmethod
    def _status(value: Any) -> str:
        if value is None:
            return "unknown"
        if isinstance(value, dict):
            raw = value.get("status")
            if raw is None:
                decision = value.get("decision")
                if isinstance(decision, dict):
                    raw = decision.get("status")
            return str(getattr(raw, "value", raw or "unknown"))
        raw = getattr(value, "status", None)
        if raw is None:
            decision = getattr(value, "decision", None)
            raw = getattr(decision, "status", None) if decision is not None else None
        return str(getattr(raw, "value", raw or "unknown"))

    @staticmethod
    def _summary(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            return str(value.get("summary") or value.get("message") or "")
        return str(getattr(value, "summary", getattr(value, "message", "")) or "")

    @staticmethod
    def _extract(value: Any, key: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(key, default)
        return getattr(value, key, default)

    @staticmethod
    def _text(value: Any, key: str, default: str = "") -> str:
        raw = AuthoritativeEngineeringOrchestrator._extract(value, key, default)
        return str(raw or default)

    @staticmethod
    def _strings(value: Any, key: str) -> tuple[str, ...]:
        raw = AuthoritativeEngineeringOrchestrator._extract(value, key, ())
        if raw is None:
            return ()
        if isinstance(raw, str):
            return (raw,) if raw.strip() else ()
        try:
            return tuple(str(item) for item in raw if str(item).strip())
        except TypeError:
            return (str(raw),)

    @staticmethod
    def _changed_paths(value: Any) -> tuple[str, ...]:
        evidence = AuthoritativeEngineeringOrchestrator._extract(value, "evidence", None)
        raw = AuthoritativeEngineeringOrchestrator._extract(value, "changed_paths", None)
        if raw is None and evidence is not None:
            raw = AuthoritativeEngineeringOrchestrator._extract(evidence, "changed_paths", ())
        if raw is None:
            changes = AuthoritativeEngineeringOrchestrator._extract(value, "changes", ())
            raw = tuple(AuthoritativeEngineeringOrchestrator._extract(x, "path", "") for x in changes)
        return tuple(str(x) for x in (raw or ()) if str(x).strip())

    @staticmethod
    def _workspace_id(value: Any) -> str | None:
        raw = AuthoritativeEngineeringOrchestrator._extract(value, "workspace_id", None)
        if raw is None:
            evidence = AuthoritativeEngineeringOrchestrator._extract(value, "evidence", None)
            raw = AuthoritativeEngineeringOrchestrator._extract(evidence, "workspace_id", None)
        return str(raw) if raw else None

    @staticmethod
    def _implementation_evidence(value: Any) -> tuple[str, ...]:
        evidence = AuthoritativeEngineeringOrchestrator._extract(value, "evidence", None)
        items = []
        for key in ("implementation_summary", "diagnostics", "errors"):
            raw = AuthoritativeEngineeringOrchestrator._extract(evidence, key, ())
            if isinstance(raw, str):
                items.append(raw)
            elif raw:
                items.extend(str(x) for x in raw)
        return tuple(items)

    @staticmethod
    def _findings(value: Any) -> tuple[dict[str, Any], ...]:
        raw = AuthoritativeEngineeringOrchestrator._extract(value, "findings", ())
        if raw is None:
            raw = AuthoritativeEngineeringOrchestrator._extract(value, "evidence", ())
        return tuple(_as_mapping(item) for item in (raw or ()))

    @staticmethod
    def _evidence_for_acceptance(*values: Any) -> tuple[dict[str, Any], ...]:
        result: list[dict[str, Any]] = []
        for value in values:
            if value is None:
                continue
            payload = _serialize(value)
            if isinstance(payload, dict):
                result.append(payload)
            else:
                result.append({"value": payload})
        return tuple(result)

    @staticmethod
    def _recovery_implementation(recovery: Any, previous: Any) -> Any:
        candidate = AuthoritativeEngineeringOrchestrator._extract(recovery, "implementation", None)
        return candidate if candidate is not None else previous

    @staticmethod
    def _ready(value: Any) -> bool:
        if isinstance(value, dict):
            return bool(value.get("ready_for_planning", True))
        return bool(getattr(value, "ready_for_planning", True))

    @staticmethod
    def _session_id(session: Any, fallback: str | None) -> str:
        raw = getattr(session, "session_id", None)
        return str(raw or fallback or "")

    def _phase(self, session: Any) -> str:
        lifecycle = getattr(session, "lifecycle", None)
        phase = getattr(lifecycle, "phase", getattr(lifecycle, "current_phase", "unknown")) if lifecycle else "unknown"
        return str(getattr(phase, "value", phase))

    def _record(self, kind: str, summary: str, details: Any) -> None:
        recorder = self.evidence_recorder
        if recorder is None:
            return
        try:
            recorder.record(
                kind=kind,
                summary=summary,
                details=_serialize(details),
                source="authoritative_engineering_orchestrator",
            )
        except Exception:
            logger.debug("Evidence recording failed.", exc_info=True)

    def _blocked(self, session: Any, status: str, error: str, **objects: Any) -> EngineeringOrchestrationResult:
        self._mark(session, "mark_blocked", error)
        return self._failure(
            self._session_id(session, None),
            status,
            error,
            **objects,
        )

    def _failure(self, session_id: str, status: str, error: str, **objects: Any) -> EngineeringOrchestrationResult:
        return EngineeringOrchestrationResult(
            success=False,
            accepted=False,
            session_id=session_id,
            status=status,
            phase="failed",
            error=error,
            requirement=objects.get("requirement"),
            knowledge=objects.get("knowledge"),
            plan=objects.get("plan"),
            task_graph=objects.get("task_graph"),
            implementation=objects.get("implementation"),
            verification=objects.get("verification"),
            diagnosis=objects.get("diagnosis"),
            recovery=objects.get("recovery"),
            acceptance=objects.get("acceptance"),
            metadata={"integration_version": self.VERSION},
        )

    def health(self) -> dict[str, Any]:
        return {
            "healthy": all(
                item is not None
                for item in (
                    self.requirement_engine,
                    self.implementation_engine,
                    self.verification_engine,
                    self.diagnosis_engine,
                    self.recovery_engine,
                    self.acceptance_engine,
                )
            ),
            "version": self.VERSION,
            "requirement_engine": self.requirement_engine is not None,
            "knowledge_engine": self.knowledge_engine is not None,
            "planning_engine": self.planning_engine is not None or True,
            "task_graph_engine": self.task_graph_engine is not None or True,
            "implementation_engine": self.implementation_engine is not None,
            "verification_engine": self.verification_engine is not None,
            "diagnosis_engine": self.diagnosis_engine is not None,
            "recovery_engine": self.recovery_engine is not None,
            "acceptance_engine": self.acceptance_engine is not None,
        }


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    method = getattr(value, "to_dict", None)
    if callable(method):
        try:
            payload = method()
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {"value": str(value)}


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(v) for v in value]
    method = getattr(value, "to_dict", None)
    if callable(method):
        try:
            return _serialize(method())
        except Exception:
            pass
    return str(value)


__all__ = [
    "EngineeringOrchestrationResult",
    "AuthoritativeEngineeringOrchestrator",
]
