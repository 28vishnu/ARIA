from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


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
    error: str | None = None
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
            "requirement": self._serialize(
                self.requirement
            ),
            "knowledge": self._serialize(
                self.knowledge
            ),
            "plan": self._serialize(
                self.plan
            ),
            "task_graph": self._serialize(
                self.task_graph
            ),
            "implementation": self._serialize(
                self.implementation
            ),
            "verification": self._serialize(
                self.verification
            ),
            "error": self.error,
            "metadata": dict(
                self.metadata
            ),
        }

    @staticmethod
    def _serialize(
        value: Any,
    ) -> Any:
        if value is None:
            return None

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
                return method()
            except Exception:
                pass

        return value


class AuthoritativeEngineeringOrchestrator:
    """
    Canonical Phase 1 engineering coordinator.

    The orchestrator owns sequencing.

    It does NOT replace:
      - requirement intelligence
      - knowledge/research
      - repository intelligence
      - planning
      - task graph
      - implementation
      - verification
      - diagnosis
      - recovery
      - acceptance

    Instead, it connects those capabilities through the authoritative
    engineering session and lifecycle.

    Canonical flow:

        REQUEST
          ↓
        REQUIREMENT
          ↓
        KNOWLEDGE
          ↓
        PLAN
          ↓
        TASK GRAPH
          ↓
        IMPLEMENT
          ↓
        VERIFY
          ↓
        ACCEPT / DIAGNOSE / RECOVER

    GitHub and deployment remain outside this orchestration boundary
    and continue to require their existing explicit authorization.
    """

    def __init__(
        self,
        *,
        session_runtime: Any | None = None,
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
    ) -> None:
        self.session_runtime = (
            session_runtime
        )

        self.requirement_engine = (
            requirement_engine
        )

        self.knowledge_engine = (
            knowledge_engine
        )

        self.planning_engine = (
            planning_engine
        )

        self.task_graph_engine = (
            task_graph_engine
        )

        self.implementation_engine = (
            implementation_engine
        )

        self.verification_engine = (
            verification_engine
        )

        self.diagnosis_engine = (
            diagnosis_engine
        )

        self.recovery_engine = (
            recovery_engine
        )

        self.acceptance_engine = (
            acceptance_engine
        )

        self.repository_engine = (
            repository_engine
        )

        self.evidence_recorder = (
            evidence_recorder
        )

        self._active_session: Any | None = None
        self._active_requirement: Any | None = None
        self._active_knowledge: Any | None = None
        self._active_plan: Any | None = None
        self._active_task_graph: Any | None = None
        self._active_implementation: Any | None = None
        self._active_verification: Any | None = None

    # ============================================================
    # Public entry point
    # ============================================================

    async def develop(
        self,
        request: str,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EngineeringOrchestrationResult:
        """
        Start the authoritative engineering lifecycle.

        This method deliberately does not assume that every service
        has identical APIs. Existing Phase 1 components are invoked
        through bounded compatibility adapters.
        """

        raw_request = str(
            request or ""
        ).strip()

        if not raw_request:
            return self._failure(
                session_id or "",
                "empty_request",
                "Engineering request cannot be empty.",
            )

        try:
            session = await self._create_session(
                raw_request,
                session_id=session_id,
                metadata=metadata,
            )

            self._active_session = session

            self._record(
                "orchestration",
                "Engineering orchestration started.",
                {
                    "request": raw_request,
                    "session_id": self._session_id(
                        session,
                        session_id,
                    ),
                },
            )

            self._lifecycle_mark(
                session,
                "mark_created",
                reason="Authoritative engineering session created.",
            )

            # ----------------------------------------------------
            # Requirement
            # ----------------------------------------------------

            self._lifecycle_mark(
                session,
                "mark_understanding",
                reason="Resolving engineering requirement.",
            )

            requirement_result = (
                await self._resolve_requirement(
                    raw_request,
                    metadata=metadata,
                )
            )

            if not self._result_success(
                requirement_result
            ):
                return self._blocked(
                    session,
                    "requirement_resolution_failed",
                    self._result_error(
                        requirement_result
                    ),
                    requirement=requirement_result,
                )

            self._active_requirement = (
                self._extract_requirement(
                    requirement_result
                )
            )

            if not self._ready_for_planning(
                requirement_result
            ):
                return self._blocked(
                    session,
                    "requirement_unclear",
                    "Requirement is not sufficiently specified for safe planning.",
                    requirement=requirement_result,
                )

            # ----------------------------------------------------
            # Knowledge
            # ----------------------------------------------------

            knowledge_result = (
                await self._gather_knowledge(
                    raw_request,
                    requirement=self._active_requirement,
                    metadata=metadata,
                )
            )

            self._active_knowledge = (
                knowledge_result
            )

            # ----------------------------------------------------
            # Planning
            # ----------------------------------------------------

            self._lifecycle_mark(
                session,
                "mark_planning",
                reason="Building adaptive engineering plan.",
            )

            plan_result = (
                await self._build_plan(
                    self._active_requirement,
                    knowledge_result,
                    metadata=metadata,
                )
            )

            if not self._result_success(
                plan_result
            ):
                return self._blocked(
                    session,
                    "planning_failed",
                    self._result_error(
                        plan_result
                    ),
                    requirement=self._active_requirement,
                    knowledge=knowledge_result,
                    plan=plan_result,
                )

            self._active_plan = (
                self._extract_plan(
                    plan_result
                )
            )

            # ----------------------------------------------------
            # Task graph
            # ----------------------------------------------------

            task_graph_result = (
                await self._build_task_graph(
                    self._active_requirement,
                    self._active_plan,
                    knowledge_result,
                    metadata=metadata,
                )
            )

            if not self._result_success(
                task_graph_result
            ):
                return self._blocked(
                    session,
                    "task_graph_failed",
                    self._result_error(
                        task_graph_result
                    ),
                    requirement=self._active_requirement,
                    knowledge=knowledge_result,
                    plan=self._active_plan,
                    task_graph=task_graph_result,
                )

            self._active_task_graph = (
                self._extract_task_graph(
                    task_graph_result
                )
            )

            self._lifecycle_mark(
                session,
                "mark_graph_ready",
                reason="Engineering task graph prepared.",
            )

            # ----------------------------------------------------
            # Implementation
            # ----------------------------------------------------

            self._lifecycle_mark(
                session,
                "mark_implementing",
                reason="Beginning autonomous implementation.",
            )

            implementation_result = (
                await self._implement(
                    self._active_requirement,
                    self._active_plan,
                    self._active_task_graph,
                    knowledge_result,
                    metadata=metadata,
                )
            )

            self._active_implementation = (
                implementation_result
            )

            if not self._result_success(
                implementation_result
            ):
                self._lifecycle_mark(
                    session,
                    "mark_failed",
                    reason=(
                        self._result_error(
                            implementation_result
                        )
                        or
                        "Implementation failed."
                    ),
                )

                return self._failure(
                    self._session_id(
                        session,
                        session_id,
                    ),
                    "implementation_failed",
                    self._result_error(
                        implementation_result
                    ),
                    requirement=self._active_requirement,
                    knowledge=knowledge_result,
                    plan=self._active_plan,
                    task_graph=self._active_task_graph,
                    implementation=implementation_result,
                )

            # ----------------------------------------------------
            # Verification
            # ----------------------------------------------------

            self._lifecycle_mark(
                session,
                "mark_verifying",
                reason="Verifying implementation evidence.",
            )

            verification_result = (
                await self._verify(
                    self._active_requirement,
                    self._active_plan,
                    self._active_task_graph,
                    implementation_result,
                    metadata=metadata,
                )
            )

            self._active_verification = (
                verification_result
            )

            # ----------------------------------------------------
            # Verification failure
            # ----------------------------------------------------

            if not self._result_success(
                verification_result
            ):
                return await self._handle_verification_failure(
                    session=session,
                    requirement=self._active_requirement,
                    knowledge=knowledge_result,
                    plan=self._active_plan,
                    task_graph=self._active_task_graph,
                    implementation=implementation_result,
                    verification=verification_result,
                    metadata=metadata,
                )

            # ----------------------------------------------------
            # Acceptance
            # ----------------------------------------------------

            self._lifecycle_mark(
                session,
                "mark_accepting",
                reason="Evaluating engineering acceptance.",
            )

            acceptance_result = (
                await self._accept(
                    self._active_requirement,
                    verification_result,
                    implementation_result,
                    metadata=metadata,
                )
            )

            accepted = self._accepted(
                acceptance_result
            )

            if accepted:
                self._record(
                    "acceptance",
                    "Engineering requirement accepted.",
                    self._serialize(
                        acceptance_result
                    ),
                )

                self._lifecycle_mark(
                    session,
                    "mark_accepted",
                    reason="Requirement acceptance criteria satisfied.",
                )

                return EngineeringOrchestrationResult(
                    success=True,
                    accepted=True,
                    session_id=self._session_id(
                        session,
                        session_id,
                    ),
                    status="accepted",
                    phase=self._phase(
                        session
                    ),
                    requirement=self._active_requirement,
                    knowledge=knowledge_result,
                    plan=self._active_plan,
                    task_graph=self._active_task_graph,
                    implementation=implementation_result,
                    verification=verification_result,
                    metadata={
                        "acceptance": self._serialize(
                            acceptance_result
                        ),
                    },
                )

            # Acceptance failure is NOT automatically success.
            return await self._handle_acceptance_failure(
                session=session,
                requirement=self._active_requirement,
                knowledge=knowledge_result,
                plan=self._active_plan,
                task_graph=self._active_task_graph,
                implementation=implementation_result,
                verification=verification_result,
                acceptance=acceptance_result,
                metadata=metadata,
            )

        except Exception as exc:
            logger.exception(
                "[AuthoritativeEngineeringOrchestrator] "
                "Engineering orchestration failed."
            )

            if self._active_session is not None:
                try:
                    self._lifecycle_mark(
                        self._active_session,
                        "mark_failed",
                        reason=str(exc),
                    )
                except Exception:
                    logger.exception(
                        "[AuthoritativeEngineeringOrchestrator] "
                        "Could not mark lifecycle failed."
                    )

            return self._failure(
                self._session_id(
                    self._active_session,
                    session_id,
                ),
                "orchestration_failed",
                str(exc),
                requirement=self._active_requirement,
                knowledge=self._active_knowledge,
                plan=self._active_plan,
                task_graph=self._active_task_graph,
                implementation=self._active_implementation,
                verification=self._active_verification,
            )

    # ============================================================
    # Requirement
    # ============================================================

    async def _resolve_requirement(
        self,
        request: str,
        *,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = (
            self.requirement_engine
        )

        if engine is None:
            return self._service_failure(
                "No authoritative requirement engine is connected."
            )

        return await self._call(
            engine,
            (
                "resolve",
                "analyze",
                "understand",
            ),
            request,
            metadata=metadata,
        )

    # ============================================================
    # Knowledge
    # ============================================================

    async def _gather_knowledge(
        self,
        request: str,
        *,
        requirement: Any,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = (
            self.knowledge_engine
        )

        if engine is None:
            return {
                "success": True,
                "items": [],
                "metadata": {
                    "knowledge_engine": "unavailable",
                },
            }

        return await self._call(
            engine,
            (
                "gather",
                "retrieve",
                "research",
            ),
            request,
            requirement=requirement,
            metadata=metadata,
        )

    # ============================================================
    # Planning
    # ============================================================

    async def _build_plan(
        self,
        requirement: Any,
        knowledge: Any,
        *,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = (
            self.planning_engine
        )

        if engine is None:
            return self._service_failure(
                "No authoritative planning engine is connected."
            )

        return await self._call(
            engine,
            (
                "build",
                "create",
                "plan",
                "generate",
                "create_plan",
            ),
            requirement,
            knowledge=knowledge,
            metadata=metadata,
        )

    # ============================================================
    # Task graph
    # ============================================================

    async def _build_task_graph(
        self,
        requirement: Any,
        plan: Any,
        knowledge: Any,
        *,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = (
            self.task_graph_engine
        )

        if engine is None:
            return self._service_failure(
                "No authoritative task graph engine is connected."
            )

        return await self._call(
            engine,
            (
                "build",
                "create",
                "generate",
                "build_graph",
            ),
            requirement,
            plan=plan,
            knowledge=knowledge,
            metadata=metadata,
        )

    # ============================================================
    # Implementation
    # ============================================================

    async def _implement(
        self,
        requirement: Any,
        plan: Any,
        task_graph: Any,
        knowledge: Any,
        *,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = (
            self.implementation_engine
        )

        if engine is None:
            return self._service_failure(
                "No authoritative implementation engine is connected."
            )

        return await self._call(
            engine,
            (
                "implement",
                "execute",
                "run",
                "apply",
            ),
            requirement,
            plan=plan,
            task_graph=task_graph,
            knowledge=knowledge,
            metadata=metadata,
        )

    # ============================================================
    # Verification
    # ============================================================

    async def _verify(
        self,
        requirement: Any,
        plan: Any,
        task_graph: Any,
        implementation: Any,
        *,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = (
            self.verification_engine
        )

        if engine is None:
            return self._service_failure(
                "No authoritative verification engine is connected."
            )

        return await self._call(
            engine,
            (
                "verify",
                "validate",
                "check",
                "run",
            ),
            requirement,
            plan=plan,
            task_graph=task_graph,
            implementation=implementation,
            metadata=metadata,
        )

    # ============================================================
    # Diagnosis
    # ============================================================

    async def _diagnose(
        self,
        requirement: Any,
        verification: Any,
        *,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = (
            self.diagnosis_engine
        )

        if engine is None:
            return self._service_failure(
                "No authoritative diagnosis engine is connected."
            )

        return await self._call(
            engine,
            (
                "diagnose",
                "analyze",
                "classify",
                "run",
            ),
            verification,
            requirement=requirement,
            metadata=metadata,
        )

    # ============================================================
    # Recovery
    # ============================================================

    async def _recover(
        self,
        requirement: Any,
        diagnosis: Any,
        *,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = (
            self.recovery_engine
        )

        if engine is None:
            return self._service_failure(
                "No authoritative recovery engine is connected."
            )

        return await self._call(
            engine,
            (
                "recover",
                "repair",
                "execute",
                "run",
            ),
            requirement,
            diagnosis=diagnosis,
            metadata=metadata,
        )

    # ============================================================
    # Acceptance
    # ============================================================

    async def _accept(
        self,
        requirement: Any,
        verification: Any,
        implementation: Any,
        *,
        metadata: dict[str, Any] | None,
    ) -> Any:
        engine = (
            self.acceptance_engine
        )

        if engine is None:
            return self._service_failure(
                "No authoritative acceptance engine is connected."
            )

        return await self._call(
            engine,
            (
                "accept",
                "evaluate",
                "judge",
                "validate",
                "run",
            ),
            requirement,
            verification=verification,
            implementation=implementation,
            metadata=metadata,
        )

    # ============================================================
    # Failure recovery
    # ============================================================

    async def _handle_verification_failure(
        self,
        *,
        session: Any,
        requirement: Any,
        knowledge: Any,
        plan: Any,
        task_graph: Any,
        implementation: Any,
        verification: Any,
        metadata: dict[str, Any] | None,
    ) -> EngineeringOrchestrationResult:
        self._lifecycle_mark(
            session,
            "mark_diagnosing",
            reason="Verification failed; determining root cause.",
        )

        diagnosis = await self._diagnose(
            requirement,
            verification,
            metadata=metadata,
        )

        if not self._result_success(
            diagnosis
        ):
            return self._failure(
                self._session_id(
                    session,
                    None,
                ),
                "diagnosis_failed",
                self._result_error(
                    diagnosis
                ),
                requirement=requirement,
                knowledge=knowledge,
                plan=plan,
                task_graph=task_graph,
                implementation=implementation,
                verification=verification,
            )

        self._lifecycle_mark(
            session,
            "mark_recovering",
            reason="Root cause identified; attempting bounded recovery.",
        )

        recovery = await self._recover(
            requirement,
            diagnosis,
            metadata=metadata,
        )

        if not self._result_success(
            recovery
        ):
            return self._failure(
                self._session_id(
                    session,
                    None,
                ),
                "recovery_failed",
                self._result_error(
                    recovery
                ),
                requirement=requirement,
                knowledge=knowledge,
                plan=plan,
                task_graph=task_graph,
                implementation=implementation,
                verification=verification,
            )

        self._lifecycle_mark(
            session,
            "mark_retesting",
            reason="Recovery completed; fresh verification required.",
        )

        # Recovery never equals acceptance.
        # A fresh verification is mandatory.
        retest = await self._verify(
            requirement,
            plan,
            task_graph,
            recovery,
            metadata=metadata,
        )

        if not self._result_success(
            retest
        ):
            self._lifecycle_mark(
                session,
                "mark_diagnosing",
                reason="Retest failed after recovery.",
            )

            return self._failure(
                self._session_id(
                    session,
                    None,
                ),
                "retest_failed",
                self._result_error(
                    retest
                ),
                requirement=requirement,
                knowledge=knowledge,
                plan=plan,
                task_graph=task_graph,
                implementation=recovery,
                verification=retest,
            )

        self._lifecycle_mark(
            session,
            "mark_reassessing",
            reason="Retest passed; reassessing requirement.",
        )

        acceptance = await self._accept(
            requirement,
            retest,
            recovery,
            metadata=metadata,
        )

        if self._accepted(
            acceptance
        ):
            self._lifecycle_mark(
                session,
                "mark_accepting",
                reason="Recovered implementation meets acceptance criteria.",
            )

            self._lifecycle_mark(
                session,
                "mark_accepted",
                reason="Requirement accepted after recovery and retest.",
            )

            return EngineeringOrchestrationResult(
                success=True,
                accepted=True,
                session_id=self._session_id(
                    session,
                    None,
                ),
                status="accepted_after_recovery",
                phase=self._phase(
                    session
                ),
                requirement=requirement,
                knowledge=knowledge,
                plan=plan,
                task_graph=task_graph,
                implementation=recovery,
                verification=retest,
                metadata={
                    "diagnosis": self._serialize(
                        diagnosis
                    ),
                    "recovery": self._serialize(
                        recovery
                    ),
                    "acceptance": self._serialize(
                        acceptance
                    ),
                },
            )

        return self._failure(
            self._session_id(
                session,
                None,
            ),
            "acceptance_pending_after_recovery",
            "Retest passed, but acceptance criteria were not explicitly satisfied.",
            requirement=requirement,
            knowledge=knowledge,
            plan=plan,
            task_graph=task_graph,
            implementation=recovery,
            verification=retest,
        )

    async def _handle_acceptance_failure(
        self,
        *,
        session: Any,
        requirement: Any,
        knowledge: Any,
        plan: Any,
        task_graph: Any,
        implementation: Any,
        verification: Any,
        acceptance: Any,
        metadata: dict[str, Any] | None,
    ) -> EngineeringOrchestrationResult:
        self._lifecycle_mark(
            session,
            "mark_reassessing",
            reason="Acceptance criteria were not satisfied.",
        )

        return self._failure(
            self._session_id(
                session,
                None,
            ),
            "acceptance_failed",
            self._result_error(
                acceptance
            )
            or
            "Acceptance criteria were not explicitly satisfied.",
            requirement=requirement,
            knowledge=knowledge,
            plan=plan,
            task_graph=task_graph,
            implementation=implementation,
            verification=verification,
        )

    # ============================================================
    # Session runtime
    # ============================================================

    async def _create_session(
        self,
        request: str,
        *,
        session_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> Any:
        runtime = (
            self.session_runtime
        )

        if runtime is None:
            return _LocalEngineeringSession(
                session_id=session_id
                or self._new_session_id(),
                request=request,
                metadata=metadata,
            )

        for method_name in (
            "create_session",
            "start_session",
            "create",
            "start",
        ):
            method = getattr(
                runtime,
                method_name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                lambda: method(
                    request,
                    session_id=session_id,
                    metadata=metadata,
                ),
                lambda: method(
                    request,
                    metadata=metadata,
                ),
                lambda: method(
                    request
                ),
            )

            for attempt in attempts:
                try:
                    value = attempt()

                    if inspect.isawaitable(
                        value
                    ):
                        value = await value

                    return value

                except TypeError:
                    continue

        return _LocalEngineeringSession(
            session_id=session_id
            or self._new_session_id(),
            request=request,
            metadata=metadata,
        )

    # ============================================================
    # Lifecycle helpers
    # ============================================================

    def _lifecycle_mark(
        self,
        session: Any,
        method_name: str,
        *,
        reason: str,
    ) -> None:
        lifecycle = self._lifecycle(
            session
        )

        if lifecycle is None:
            return

        method = getattr(
            lifecycle,
            method_name,
            None,
        )

        if not callable(method):
            return

        try:
            method(
                reason=reason
            )
        except TypeError:
            method()

    def _lifecycle(
        self,
        session: Any,
    ) -> Any | None:
        lifecycle = getattr(
            session,
            "lifecycle",
            None,
        )

        if lifecycle is not None:
            return lifecycle

        if self.session_runtime is not None:
            lifecycle = getattr(
                self.session_runtime,
                "lifecycle",
                None,
            )

            if lifecycle is not None:
                return lifecycle

        return None

    # ============================================================
    # Generic service invocation
    # ============================================================

    async def _call(
        self,
        service: Any,
        method_names: tuple[str, ...],
        primary: Any,
        **kwargs: Any,
    ) -> Any:
        for method_name in method_names:
            method = getattr(
                service,
                method_name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                lambda: method(
                    primary,
                    **kwargs,
                ),
                lambda: method(
                    primary
                ),
                lambda: method(
                    **kwargs,
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

        return self._service_failure(
            "Connected engineering service does not expose a compatible API."
        )

    # ============================================================
    # Result normalization
    # ============================================================

    @staticmethod
    def _result_success(
        result: Any,
    ) -> bool:
        if result is None:
            return False

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
    def _accepted(
        result: Any,
    ) -> bool:
        if result is None:
            return False

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
    def _result_error(
        result: Any,
    ) -> str | None:
        if result is None:
            return "No result was returned."

        if isinstance(
            result,
            dict,
        ):
            return (
                result.get("error")
                or result.get("reason")
                or result.get("message")
            )

        return (
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
            or getattr(
                result,
                "message",
                None,
            )
        )

    @staticmethod
    def _extract_requirement(
        result: Any,
    ) -> Any:
        if isinstance(
            result,
            dict,
        ):
            return result.get(
                "requirement",
                result,
            )

        return getattr(
            result,
            "requirement",
            result,
        )

    @staticmethod
    def _extract_plan(
        result: Any,
    ) -> Any:
        if isinstance(
            result,
            dict,
        ):
            return result.get(
                "plan",
                result,
            )

        return getattr(
            result,
            "plan",
            result,
        )

    @staticmethod
    def _extract_task_graph(
        result: Any,
    ) -> Any:
        if isinstance(
            result,
            dict,
        ):
            return result.get(
                "task_graph",
                result.get(
                    "graph",
                    result,
                ),
            )

        return getattr(
            result,
            "task_graph",
            getattr(
                result,
                "graph",
                result,
            ),
        )

    @staticmethod
    def _ready_for_planning(
        result: Any,
    ) -> bool:
        if isinstance(
            result,
            dict,
        ):
            return bool(
                result.get(
                    "ready_for_planning",
                    True,
                )
            )

        return bool(
            getattr(
                result,
                "ready_for_planning",
                True,
            )
        )

    # ============================================================
    # Session utilities
    # ============================================================

    @staticmethod
    def _session_id(
        session: Any,
        fallback: str | None,
    ) -> str:
        if session is None:
            return fallback or ""

        if isinstance(
            session,
            dict,
        ):
            return str(
                session.get(
                    "session_id",
                    fallback
                    or "",
                )
            )

        return str(
            getattr(
                session,
                "session_id",
                fallback
                or "",
            )
        )

    @staticmethod
    def _phase(
        session: Any,
    ) -> str:
        lifecycle = getattr(
            session,
            "lifecycle",
            None,
        )

        if lifecycle is None:
            return "unknown"

        phase = getattr(
            lifecycle,
            "phase",
            getattr(
                lifecycle,
                "current_phase",
                "unknown",
            ),
        )

        value = getattr(
            phase,
            "value",
            phase,
        )

        return str(
            value
        )

    def _record(
        self,
        kind: str,
        summary: str,
        details: Any,
    ) -> None:
        recorder = (
            self.evidence_recorder
        )

        if recorder is None:
            return

        try:
            recorder.record(
                kind=kind,
                summary=summary,
                details=self._serialize(
                    details
                ),
                source=(
                    "authoritative_engineering_orchestrator"
                ),
            )
        except Exception:
            logger.exception(
                "[AuthoritativeEngineeringOrchestrator] "
                "Evidence recording failed."
            )

    @staticmethod
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
                str(key): (
                    AuthoritativeEngineeringOrchestrator._serialize(
                        item
                    )
                )
                for key, item in value.items()
            }

        if isinstance(
            value,
            (list, tuple),
        ):
            return [
                AuthoritativeEngineeringOrchestrator._serialize(
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
                return AuthoritativeEngineeringOrchestrator._serialize(
                    method()
                )
            except Exception:
                pass

        return str(
            value
        )

    # ============================================================
    # Result builders
    # ============================================================

    def _blocked(
        self,
        session: Any,
        status: str,
        error: str | None,
        **objects: Any,
    ) -> EngineeringOrchestrationResult:
        try:
            self._lifecycle_mark(
                session,
                "mark_blocked",
                reason=error or status,
            )
        except Exception:
            logger.exception(
                "[AuthoritativeEngineeringOrchestrator] "
                "Could not mark session blocked."
            )

        return EngineeringOrchestrationResult(
            success=False,
            accepted=False,
            session_id=self._session_id(
                session,
                None,
            ),
            status=status,
            phase=self._phase(
                session
            ),
            error=error,
            requirement=objects.get(
                "requirement"
            ),
            knowledge=objects.get(
                "knowledge"
            ),
            plan=objects.get(
                "plan"
            ),
            task_graph=objects.get(
                "task_graph"
            ),
            implementation=objects.get(
                "implementation"
            ),
            verification=objects.get(
                "verification"
            ),
        )

    def _failure(
        self,
        session_id: str,
        status: str,
        error: str | None,
        **objects: Any,
    ) -> EngineeringOrchestrationResult:
        return EngineeringOrchestrationResult(
            success=False,
            accepted=False,
            session_id=session_id,
            status=status,
            phase=(
                self._phase(
                    self._active_session
                )
                if self._active_session
                else "failed"
            ),
            error=error,
            requirement=objects.get(
                "requirement"
            ),
            knowledge=objects.get(
                "knowledge"
            ),
            plan=objects.get(
                "plan"
            ),
            task_graph=objects.get(
                "task_graph"
            ),
            implementation=objects.get(
                "implementation"
            ),
            verification=objects.get(
                "verification"
            ),
        )

    @staticmethod
    def _service_failure(
        message: str,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "accepted": False,
            "error": message,
        }

    @staticmethod
    def _new_session_id() -> str:
        import uuid

        return (
            "eng-"
            + uuid.uuid4().hex[:16]
        )

    # ============================================================
    # Health
    # ============================================================

    def health(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "requirement_engine": (
                self.requirement_engine
                is not None
            ),
            "knowledge_engine": (
                self.knowledge_engine
                is not None
            ),
            "planning_engine": (
                self.planning_engine
                is not None
            ),
            "task_graph_engine": (
                self.task_graph_engine
                is not None
            ),
            "implementation_engine": (
                self.implementation_engine
                is not None
            ),
            "verification_engine": (
                self.verification_engine
                is not None
            ),
            "diagnosis_engine": (
                self.diagnosis_engine
                is not None
            ),
            "recovery_engine": (
                self.recovery_engine
                is not None
            ),
            "acceptance_engine": (
                self.acceptance_engine
                is not None
            ),
        }


class _LocalEngineeringSession:
    """
    Minimal fallback session used only when no external session
    runtime is connected.

    It provides the lifecycle surface required by the orchestrator.
    """

    def __init__(
        self,
        *,
        session_id: str,
        request: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        self.session_id = session_id
        self.request = request
        self.metadata = dict(
            metadata
            or {}
        )
        self.lifecycle = None