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

        loop = self.components.get(
            "autonomous_coding_loop"
        )

        if loop is None:
            raise RuntimeError(
                "Autonomous coding loop is unavailable."
            )

        return await loop.run(
            requirement,
            changes=changes,
            test_paths=test_paths,
            workspace_id=workspace_id,
            max_attempts=max_attempts,
            context=metadata,
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
        Run the autonomous validation layer.
        """

        validator = self.components.get(
            "autonomous_validation_loop"
        )

        if validator is None:
            raise RuntimeError(
                "Autonomous validation loop is unavailable."
            )

        return await validator.validate(
            workspace_id=workspace_id,
            test_paths=test_paths,
            requirement=requirement,
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
        Run the bounded error → repair → retest lifecycle.
        """

        repair_loop = self.components.get(
            "autonomous_repair_loop"
        )

        if repair_loop is None:
            raise RuntimeError(
                "Autonomous repair loop is unavailable."
            )

        return await repair_loop.run(
            requirement,
            changes=changes,
            test_paths=test_paths,
            workspace_id=workspace_id,
            max_cycles=max_cycles,
            metadata=metadata,
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