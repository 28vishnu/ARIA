"""
ARIA Phase 1 — Runtime Integration

Compatibility service container for the Phase 1 autonomous-engineering
foundation.

IMPORTANT ARCHITECTURAL RULE
-----------------------------

This module is NOT the owner of autonomous engineering execution.

The single authoritative execution path is:

    Telegram / application
            ↓
    Phase1PersistentRuntimeAdapter
            ↓
    FinalAutonomousEngineer
            ↓
    AuthoritativeEngineeringOrchestrator
            ↓
    Requirement
            ↓
    Knowledge / Repository
            ↓
    Planning
            ↓
    Task Graph
            ↓
    Implementation
            ↓
    Verification
            ↓
    Diagnosis
            ↓
    Recovery
            ↓
    Fresh Verification
            ↓
    Acceptance
            ↓
    Experience

The objects exposed by this module exist only as compatibility services
used internally by the authoritative engines where appropriate.

Legacy engineering adapters MUST NEVER become an alternative execution
owner.

Legacy imports are intentionally lazy so that an obsolete compatibility
module cannot prevent the canonical runtime from starting.
"""

from __future__ import annotations

import logging
import os
from typing import Any


# ==========================================================
# OPTIONAL COMPATIBILITY SERVICES
# ==========================================================

# These are intentionally initialized to None.

# A legacy compatibility module may have been removed, renamed, or
# consolidated into the authoritative Phase 1 architecture.
#
# Therefore these imports MUST NOT happen at module import time.
#
# A broken compatibility adapter must never prevent ARIA bootstrap.

AutonomousCodingLoop = None
AutonomousValidationLoop = None
AutonomousRepairLoop = None
KnowledgeCodingFeedback = None
AutonomousDevelopmentBridge = None
PermissionedGitWorkflow = None
PermissionedDeploymentWorkflow = None
KnowledgeRetriever = None


logger = logging.getLogger("aria")


class Phase1Runtime:
    """
    Runtime-owned Phase 1 compatibility service container.

    The authoritative engineering runtime is supplied by
    Phase1PersistentRuntimeAdapter.

    This object does not own autonomous engineering execution.
    """

    VERSION = "phase1-runtime-20261005-COMPAT-SAFE"

    def __init__(
        self,
        *,
        development_controller: Any,
        git_manager: Any = None,
        github_manager: Any = None,
        deployment_manager: Any = None,
        memory_engine: Any = None,
        knowledge_database: Any = None,
        knowledge_graph: Any = None,
        document_ai: Any = None,
    ) -> None:

        if development_controller is None:
            raise ValueError(
                "development_controller is required."
            )

        self.development_controller = (
            development_controller
        )

        self.git_manager = git_manager
        self.github_manager = github_manager
        self.deployment_manager = deployment_manager

        self.memory_engine = memory_engine

        self.knowledge_database = (
            knowledge_database
        )

        self.knowledge_graph = (
            knowledge_graph
        )

        self.document_ai = document_ai

        self.components: dict[str, Any] = {}

        self.errors: list[str] = []

        self.initialized = False

        # The canonical runtime is bound by
        # Phase1PersistentRuntimeAdapter.
        #
        # The legacy runtime NEVER becomes the execution owner.
        self._authoritative_runtime = None

    # ==========================================================
    # INITIALIZATION
    # ==========================================================

    def initialize(self) -> dict[str, Any]:
        """
        Build the compatibility service graph.

        Legacy/optional subsystem failures are isolated.

        Most importantly, an obsolete legacy engineering module must
        never prevent the authoritative runtime from booting.
        """

        self.components.clear()
        self.errors.clear()

        # ------------------------------------------------------
        # Resolve compatibility services lazily
        # ------------------------------------------------------

        global AutonomousCodingLoop
        global AutonomousValidationLoop
        global AutonomousRepairLoop
        global KnowledgeCodingFeedback
        global AutonomousDevelopmentBridge
        global PermissionedGitWorkflow
        global PermissionedDeploymentWorkflow
        global KnowledgeRetriever

        # ------------------------------------------------------
        # Autonomous Coding Loop
        # ------------------------------------------------------

        try:

            from brain.development.autonomous_coding_loop import (
                AutonomousCodingLoop as _AutonomousCodingLoop,
            )

            AutonomousCodingLoop = (
                _AutonomousCodingLoop
            )

        except Exception as exc:

            self.errors.append(
                "AutonomousCodingLoop compatibility import disabled: "
                f"{exc}"
            )

            logger.warning(
                "[Phase1] Legacy AutonomousCodingLoop unavailable; "
                "authoritative runtime remains active | error=%s",
                exc,
            )

        # ------------------------------------------------------
        # Autonomous Validation Loop
        # ------------------------------------------------------

        try:

            from brain.development.autonomous_validation_loop import (
                AutonomousValidationLoop as _AutonomousValidationLoop,
            )

            AutonomousValidationLoop = (
                _AutonomousValidationLoop
            )

        except Exception as exc:

            self.errors.append(
                "AutonomousValidationLoop compatibility import disabled: "
                f"{exc}"
            )

            logger.warning(
                "[Phase1] Legacy AutonomousValidationLoop unavailable; "
                "authoritative verification remains active | error=%s",
                exc,
            )

        # ------------------------------------------------------
        # Autonomous Repair Loop
        # ------------------------------------------------------

        try:

            from brain.development.autonomous_repair_loop import (
                AutonomousRepairLoop as _AutonomousRepairLoop,
            )

            AutonomousRepairLoop = (
                _AutonomousRepairLoop
            )

        except Exception as exc:

            self.errors.append(
                "AutonomousRepairLoop compatibility import disabled: "
                f"{exc}"
            )

            logger.warning(
                "[Phase1] Legacy AutonomousRepairLoop unavailable; "
                "authoritative recovery remains active | error=%s",
                exc,
            )

        # ------------------------------------------------------
        # Knowledge Coding Feedback
        # ------------------------------------------------------

        try:

            from brain.development.knowledge_coding_feedback import (
                KnowledgeCodingFeedback as _KnowledgeCodingFeedback,
            )

            KnowledgeCodingFeedback = (
                _KnowledgeCodingFeedback
            )

        except Exception as exc:

            self.errors.append(
                "KnowledgeCodingFeedback compatibility import disabled: "
                f"{exc}"
            )

            logger.warning(
                "[Phase1] KnowledgeCodingFeedback compatibility "
                "service unavailable | error=%s",
                exc,
            )

        # ------------------------------------------------------
        # Legacy Autonomous Development Bridge
        # ------------------------------------------------------

        try:

            from brain.integration.autonomous_development_bridge import (
                AutonomousDevelopmentBridge as _AutonomousDevelopmentBridge,
            )

            AutonomousDevelopmentBridge = (
                _AutonomousDevelopmentBridge
            )

        except Exception as exc:

            self.errors.append(
                "AutonomousDevelopmentBridge compatibility import disabled: "
                f"{exc}"
            )

            logger.warning(
                "[Phase1] Legacy AutonomousDevelopmentBridge unavailable. "
                "This does NOT affect the authoritative orchestrator | "
                "error=%s",
                exc,
            )

        # ------------------------------------------------------
        # Permissioned Git Workflow
        # ------------------------------------------------------

        try:

            from brain.integration.permissioned_git_workflow import (
                PermissionedGitWorkflow as _PermissionedGitWorkflow,
            )

            PermissionedGitWorkflow = (
                _PermissionedGitWorkflow
            )

        except Exception as exc:

            self.errors.append(
                "PermissionedGitWorkflow compatibility import disabled: "
                f"{exc}"
            )

            logger.warning(
                "[Phase1] PermissionedGitWorkflow unavailable | error=%s",
                exc,
            )

        # ------------------------------------------------------
        # Permissioned Deployment Workflow
        # ------------------------------------------------------

        try:

            from brain.integration.permissioned_deployment_workflow import (
                PermissionedDeploymentWorkflow
                as _PermissionedDeploymentWorkflow,
            )

            PermissionedDeploymentWorkflow = (
                _PermissionedDeploymentWorkflow
            )

        except Exception as exc:

            self.errors.append(
                "PermissionedDeploymentWorkflow "
                "compatibility import disabled: "
                f"{exc}"
            )

            logger.warning(
                "[Phase1] PermissionedDeploymentWorkflow unavailable | "
                "error=%s",
                exc,
            )

        # ------------------------------------------------------
        # Knowledge Retriever
        # ------------------------------------------------------

        try:

            from brain.memory.knowledge_retriever import (
                KnowledgeRetriever as _KnowledgeRetriever,
            )

            KnowledgeRetriever = (
                _KnowledgeRetriever
            )

        except Exception as exc:

            self.errors.append(
                "KnowledgeRetriever compatibility import disabled: "
                f"{exc}"
            )

            logger.warning(
                "[Phase1] KnowledgeRetriever unavailable | error=%s",
                exc,
            )

        # ======================================================
        # DEVELOPMENT BRIDGE
        # ======================================================

        if AutonomousDevelopmentBridge is not None:

            try:

                bridge = (
                    AutonomousDevelopmentBridge(
                        self.development_controller,
                        timeout_seconds=float(
                            os.getenv(
                                "ARIA_AUTONOMOUS_DEV_TIMEOUT",
                                "3600",
                            )
                        ),
                    )
                )

                self.components[
                    "autonomous_development_bridge"
                ] = bridge

            except Exception as exc:

                self.errors.append(
                    "AutonomousDevelopmentBridge: "
                    f"{exc}"
                )

        # ======================================================
        # AUTONOMOUS CODING LOOP
        # ======================================================

        if AutonomousCodingLoop is not None:

            try:

                bridge = self.components.get(
                    "autonomous_development_bridge"
                )

                if bridge is not None:

                    coding_loop = (
                        AutonomousCodingLoop(
                            bridge,
                            max_attempts=int(
                                os.getenv(
                                    "ARIA_AUTONOMOUS_CODING_ATTEMPTS",
                                    "3",
                                )
                            ),
                        )
                    )

                    self.components[
                        "autonomous_coding_loop"
                    ] = coding_loop

            except Exception as exc:

                self.errors.append(
                    "AutonomousCodingLoop: "
                    f"{exc}"
                )

        # ======================================================
        # AUTONOMOUS VALIDATION LOOP
        # ======================================================

        if AutonomousValidationLoop is not None:

            try:

                validation_loop = (
                    AutonomousValidationLoop(
                        self.development_controller
                    )
                )

                self.components[
                    "autonomous_validation_loop"
                ] = validation_loop

            except Exception as exc:

                self.errors.append(
                    "AutonomousValidationLoop: "
                    f"{exc}"
                )

        # ======================================================
        # AUTONOMOUS REPAIR LOOP
        # ======================================================

        if AutonomousRepairLoop is not None:

            try:

                repair_loop = (
                    AutonomousRepairLoop(
                        self.development_controller,
                        max_cycles=int(
                            os.getenv(
                                "ARIA_AUTONOMOUS_REPAIR_CYCLES",
                                "2",
                            )
                        ),
                    )
                )

                self.components[
                    "autonomous_repair_loop"
                ] = repair_loop

            except Exception as exc:

                self.errors.append(
                    "AutonomousRepairLoop: "
                    f"{exc}"
                )

        # ======================================================
        # KNOWLEDGE RETRIEVER
        # ======================================================

        if KnowledgeRetriever is not None:

            try:

                retriever = KnowledgeRetriever(
                    memory_engine=(
                        self.memory_engine
                    ),
                    document_ai=(
                        self.document_ai
                    ),
                    knowledge_database=(
                        self.knowledge_database
                    ),
                    knowledge_graph=(
                        self.knowledge_graph
                    ),
                )

                self.components[
                    "knowledge_retriever"
                ] = retriever

            except Exception as exc:

                self.errors.append(
                    "KnowledgeRetriever: "
                    f"{exc}"
                )

        # ======================================================
        # KNOWLEDGE → CODING FEEDBACK
        # ======================================================

        if KnowledgeCodingFeedback is not None:

            try:

                retriever = self.components.get(
                    "knowledge_retriever"
                )

                if retriever is not None:

                    knowledge_feedback = (
                        KnowledgeCodingFeedback(
                            retriever
                        )
                    )

                    self.components[
                        "knowledge_coding_feedback"
                    ] = knowledge_feedback

            except Exception as exc:

                self.errors.append(
                    "KnowledgeCodingFeedback: "
                    f"{exc}"
                )

        # ======================================================
        # PERMISSIONED GIT / GITHUB
        # ======================================================

        if PermissionedGitWorkflow is not None:

            try:

                git_workflow = (
                    PermissionedGitWorkflow(
                        git_service=self.git_manager,
                        github_service=self.github_manager,
                    )
                )

                self.components[
                    "permissioned_git_workflow"
                ] = git_workflow

            except Exception as exc:

                self.errors.append(
                    "PermissionedGitWorkflow: "
                    f"{exc}"
                )

        # ======================================================
        # PERMISSIONED DEPLOYMENT
        # ======================================================

        if PermissionedDeploymentWorkflow is not None:

            try:

                deployment_workflow = (
                    PermissionedDeploymentWorkflow(
                        deployment_service=(
                            self.deployment_manager
                        ),
                        health_timeout_seconds=float(
                            os.getenv(
                                "ARIA_DEPLOYMENT_HEALTH_TIMEOUT",
                                "60",
                            )
                        ),
                        health_interval_seconds=float(
                            os.getenv(
                                "ARIA_DEPLOYMENT_HEALTH_INTERVAL",
                                "5",
                            )
                        ),
                    )
                )

                self.components[
                    "permissioned_deployment_workflow"
                ] = deployment_workflow

            except Exception as exc:

                self.errors.append(
                    "PermissionedDeploymentWorkflow: "
                    f"{exc}"
                )

        # ======================================================
        # INITIALIZATION COMPLETE
        # ======================================================

        self.initialized = True

        logger.info(
            "[Phase1] Runtime compatibility integration initialized | "
            "components=%s | compatibility_warnings=%s",
            len(
                self.components
            ),
            len(
                self.errors
            ),
        )

        if self.errors:

            logger.warning(
                "[Phase1] Compatibility services unavailable: %s",
                self.errors,
            )

        return dict(
            self.components
        )

    # ==========================================================
    # SERVICE ACCESS
    # ==========================================================

    def get(
        self,
        name: str,
        default: Any = None,
    ) -> Any:
        """
        Retrieve one Phase 1 compatibility component safely.

        Missing compatibility services return ``default``.

        This is intentional: the authoritative engineering runtime
        must never depend on obsolete legacy components being present.
        """

        return self.components.get(
            name,
            default,
        )

    def has(
        self,
        name: str,
    ) -> bool:

        return (
            name in self.components
        )

    # ==========================================================
    # CANONICAL RUNTIME BINDING
    # ==========================================================

    def bind_authoritative_runtime(
        self,
        runtime: Any,
    ) -> None:
        """
        Bind the single authoritative Phase 1 engineering runtime.
        """

        if runtime is None:

            raise ValueError(
                "authoritative runtime is required."
            )

        self._authoritative_runtime = (
            runtime
        )

    @property
    def authoritative_runtime(
        self,
    ) -> Any:

        return (
            self._authoritative_runtime
        )

    # ==========================================================
    # MAIN DEVELOPMENT ENTRY POINT
    # ==========================================================

    async def develop(
        self,
        requirement: str,
        *,
        changes=None,
        test_paths=None,
        workspace_id=None,
        max_attempts=None,
        metadata=None,
    ):
        """
        Compatibility development entry point.

        ALL engineering execution is delegated to the canonical
        Phase1PersistentRuntimeAdapter.

        The legacy coding loop is never used as an execution owner.
        """

        runtime = (
            self._authoritative_runtime
        )

        if runtime is None:

            raise RuntimeError(
                "Canonical Phase 1 engineering runtime "
                "is not bound."
            )

        develop = getattr(
            runtime,
            "develop",
            None,
        )

        if not callable(
            develop
        ):

            raise RuntimeError(
                "Canonical Phase 1 engineering runtime "
                "has no develop entry point."
            )

        return await develop(
            requirement,
            changes=changes,
            test_paths=test_paths,
            workspace_id=workspace_id,
            max_attempts=max_attempts,
            metadata=metadata,
        )

    # ==========================================================
    # KNOWLEDGE ENRICHMENT
    # ==========================================================

    async def enrich_development_context(
        self,
        requirement: str,
        *,
        development_context=None,
        user_id: str = "",
        session_id: str = "",
        limit: int = 8,
    ):
        """
        Retrieve relevant knowledge and merge it into development
        context.
        """

        feedback = self.components.get(
            "knowledge_coding_feedback"
        )

        if feedback is None:

            raise RuntimeError(
                "Knowledge coding feedback is unavailable."
            )

        return await feedback.enrich(
            development_context,
            requirement,
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )

    # ==========================================================
    # VALIDATION
    # ==========================================================

    async def validate(
        self,
        *,
        workspace_id=None,
        test_paths=None,
        requirement=None,
    ):
        """
        Compatibility guard.

        Verification is owned by the authoritative engineering
        orchestrator and cannot be executed independently.
        """

        raise RuntimeError(
            "Direct Phase1Runtime validation is disabled. "
            "Verification must execute through "
            "AuthoritativeEngineeringOrchestrator."
        )

    # ==========================================================
    # REPAIR
    # ==========================================================

    async def repair(
        self,
        requirement: str,
        *,
        changes=None,
        test_paths=None,
        workspace_id=None,
        max_cycles=None,
        metadata=None,
    ):
        """
        Compatibility guard.

        Diagnosis, recovery, and retest are owned by the
        authoritative engineering orchestrator and cannot execute
        independently.
        """

        raise RuntimeError(
            "Direct Phase1Runtime repair is disabled. "
            "Diagnosis, recovery, and retest must execute through "
            "AuthoritativeEngineeringOrchestrator."
        )

    # ==========================================================
    # STATUS
    # ==========================================================

    def status(
        self,
    ) -> dict[str, Any]:

        return {
            "version": self.VERSION,
            "initialized": self.initialized,
            "component_count": len(
                self.components
            ),
            "components": sorted(
                self.components.keys()
            ),
            "errors": list(
                self.errors
            ),
            "authoritative": True,
            "execution_owner": (
                "Phase1PersistentRuntimeAdapter"
                if self._authoritative_runtime is not None
                else "unbound"
            ),
            "legacy_execution_owner": False,
        }

    # ==========================================================
    # HEALTH
    # ==========================================================

    def health(
        self,
    ) -> dict[str, Any]:
        """
        Compatibility-container health.

        Legacy coding/validation/repair components are deliberately
        NOT required for health because the authoritative runtime
        owns those stages.

        Only permissioned delivery compatibility services are treated
        as required here.
        """

        required = (
            "permissioned_git_workflow",
            "permissioned_deployment_workflow",
        )

        missing = [
            name
            for name in required
            if name not in self.components
        ]

        return {
            "healthy": (
                self.initialized
                and not missing
            ),
            "initialized": self.initialized,
            "missing_components": missing,
            "errors": list(
                self.errors
            ),
            "authoritative": True,
            "execution_owner": (
                "Phase1PersistentRuntimeAdapter"
                if self._authoritative_runtime is not None
                else "unbound"
            ),
            "legacy_execution_owner": False,
            "component_count": len(
                self.components
            ),
        }

    # ==========================================================
    # DESCRIPTION
    # ==========================================================

    def describe(
        self,
    ) -> dict[str, Any]:

        return {
            "name": "phase1_runtime",
            "version": self.VERSION,
            "purpose": (
                "Compatibility service container for ARIA's "
                "authoritative autonomous software-engineering "
                "foundation."
            ),
            "autonomous_development": (
                self.has(
                    "autonomous_coding_loop"
                )
            ),
            "validation": (
                self.has(
                    "autonomous_validation_loop"
                )
            ),
            "repair": (
                self.has(
                    "autonomous_repair_loop"
                )
            ),
            "knowledge_feedback": (
                self.has(
                    "knowledge_coding_feedback"
                )
            ),
            "permissioned_git": (
                self.has(
                    "permissioned_git_workflow"
                )
            ),
            "permissioned_deployment": (
                self.has(
                    "permissioned_deployment_workflow"
                )
            ),
            "github_push_requires_authorization": True,
            "deployment_requires_authorization": True,
            "authoritative_execution_owner": (
                "Phase1PersistentRuntimeAdapter"
                if self._authoritative_runtime is not None
                else None
            ),
            "legacy_execution_entrypoint_disabled": (
                self._authoritative_runtime is not None
            ),
        }


# ==========================================================
# FACTORY
# ==========================================================

def create_phase1_runtime(
    *,
    development_controller: Any,
    git_manager: Any = None,
    github_manager: Any = None,
    deployment_manager: Any = None,
    memory_engine: Any = None,
    knowledge_database: Any = None,
    knowledge_graph: Any = None,
    document_ai: Any = None,
) -> Phase1Runtime:
    """
    Bootstrap convenience factory.
    """

    runtime = Phase1Runtime(
        development_controller=(
            development_controller
        ),
        git_manager=git_manager,
        github_manager=github_manager,
        deployment_manager=deployment_manager,
        memory_engine=memory_engine,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
        document_ai=document_ai,
    )

    runtime.initialize()

    return runtime


__all__ = [
    "Phase1Runtime",
    "create_phase1_runtime",
]
