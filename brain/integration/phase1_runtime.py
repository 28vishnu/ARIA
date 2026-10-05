"""
ARIA Phase 1 — Runtime Integration

Connects the Phase 1 autonomous-engineering components to the
already-running ServiceRegistry.

This module does NOT create a second development system.

Existing authoritative services remain:

    DevelopmentController
    GitManager
    GitHubManager
    DeploymentManager
    KnowledgeRetriever

This module only creates the orchestration adapters around them.

Runtime flow:

    Telegram / application
            ↓
    AutonomousCodingLoop
            ↓
    AutonomousDevelopmentBridge
            ↓
    DevelopmentController
            ↓
    DevelopmentAgent

Additional capabilities:

    KnowledgeRetriever
            ↓
    KnowledgeCodingFeedback

    GitManager + GitHubManager
            ↓
    PermissionedGitWorkflow

    DeploymentManager
            ↓
    PermissionedDeploymentWorkflow
"""

from __future__ import annotations

import logging
import os
from typing import Any

from brain.development.autonomous_coding_loop import (
    AutonomousCodingLoop,
)

from brain.development.autonomous_validation_loop import (
    AutonomousValidationLoop,
)

from brain.development.autonomous_repair_loop import (
    AutonomousRepairLoop,
)

from brain.development.knowledge_coding_feedback import (
    KnowledgeCodingFeedback,
)

from brain.integration.autonomous_development_bridge import (
    AutonomousDevelopmentBridge,
)

from brain.integration.permissioned_git_workflow import (
    PermissionedGitWorkflow,
)

from brain.integration.permissioned_deployment_workflow import (
    PermissionedDeploymentWorkflow,
)

from brain.memory.knowledge_retriever import (
    KnowledgeRetriever,
)


logger = logging.getLogger("aria")


class Phase1Runtime:
    """
    Runtime-owned Phase 1 integration container.

    All underlying authoritative services are supplied by bootstrap.
    """

    VERSION = "phase1-runtime-20261004"

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
        self.knowledge_graph = knowledge_graph
        self.document_ai = document_ai

        self.components: dict[str, Any] = {}

        self.errors: list[str] = []

        self.initialized = False

        # Canonical Phase 1 runtime is bound by
        # Phase1PersistentRuntimeAdapter after construction.
        # This prevents the legacy runtime from becoming a competing
        # engineering execution entry point.
        self._authoritative_runtime = None

    # ==========================================================
    # INITIALIZATION
    # ==========================================================

    def initialize(self) -> dict[str, Any]:
        """
        Build the runtime Phase 1 integration graph.

        Each adapter is isolated so one optional subsystem failure
        does not prevent ARIA itself from starting.
        """

        self.components.clear()
        self.errors.clear()

        # ------------------------------------------------------
        # Development bridge
        # ------------------------------------------------------

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

        # ------------------------------------------------------
        # Autonomous coding loop
        # ------------------------------------------------------

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

        # ------------------------------------------------------
        # Validation loop
        # ------------------------------------------------------

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

        # ------------------------------------------------------
        # Repair loop
        # ------------------------------------------------------

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

        # ------------------------------------------------------
        # Knowledge retriever
        # ------------------------------------------------------

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

        # ------------------------------------------------------
        # Knowledge → coding feedback
        # ------------------------------------------------------

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

        # ------------------------------------------------------
        # Permissioned Git / GitHub
        # ------------------------------------------------------

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

        # ------------------------------------------------------
        # Permissioned deployment
        # ------------------------------------------------------

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

        self.initialized = True

        logger.info(
            "[Phase1] Runtime integration initialized | "
            "components=%s | errors=%s",
            len(
                self.components
            ),
            len(
                self.errors
            ),
        )

        if self.errors:

            logger.warning(
                "[Phase1] Runtime integration warnings: %s",
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
    ) -> Any:
        """
        Retrieve one Phase 1 runtime component.
        """

        if name not in self.components:
            raise KeyError(
                f"Phase 1 runtime component "
                f"'{name}' is not available."
            )

        return self.components[
            name
        ]

    def has(
        self,
        name: str,
    ) -> bool:
        return name in self.components

    # ==========================================================
    # CANONICAL RUNTIME BINDING
    # ==========================================================

    def bind_authoritative_runtime(self, runtime: Any) -> None:
        """Bind the single authoritative Phase 1 engineering runtime."""
        if runtime is None:
            raise ValueError("authoritative runtime is required.")
        self._authoritative_runtime = runtime

    @property
    def authoritative_runtime(self) -> Any:
        return self._authoritative_runtime

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
        Main autonomous development entry point.

        Telegram and future orchestration layers should use this
        component rather than directly rebuilding the lower-level
        development graph.
        """

        # Compatibility callers must enter the canonical runtime.
        # The legacy AutonomousCodingLoop remains available as an internal
        # implementation component, but it is no longer an execution owner.
        runtime = self._authoritative_runtime
        if runtime is None:
            raise RuntimeError(
                "Canonical Phase 1 engineering runtime is not bound."
            )

        develop = getattr(runtime, "develop", None)
        if not callable(develop):
            raise RuntimeError(
                "Canonical Phase 1 engineering runtime has no develop entry point."
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
        Compatibility guard: verification is owned by the authoritative
        engineering orchestrator and cannot be executed independently.
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
        Compatibility guard: diagnosis/recovery/retest is owned by the
        authoritative engineering orchestrator and cannot be executed
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

    def status(self) -> dict[str, Any]:
        result = {
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

        return result

    # ==========================================================
    # HEALTH
    # ==========================================================

    def health(self) -> dict[str, Any]:
        required = (
            "autonomous_development_bridge",
            "autonomous_coding_loop",
            "autonomous_validation_loop",
            "autonomous_repair_loop",
            "knowledge_coding_feedback",
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

    def describe(self) -> dict[str, Any]:
        return {
            "name": "phase1_runtime",
            "version": self.VERSION,
            "purpose": (
                "Runtime integration for ARIA's autonomous "
                "software-engineering foundation."
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
