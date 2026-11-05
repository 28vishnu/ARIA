"""
ARIA Phase 1 System Integration
================================

Phase 1 - Step 19

Integration facade for the autonomous ARIA architecture.

This module connects:

    GoalManager
        ↓
    PhasePlanner
        ↓
    AutonomousExecutionController
        ↓
    SelfCorrectionEngine
        ↓
    ExperienceEngine
        ↓
    ExperienceAdapter
        ↓
    ExperienceConsolidator
        ↓
    PermissionGuard
        ↓
    AutonomousOrchestrator

Important
---------
This module does NOT replace the canonical:
    - Executor
    - Planner
    - Task
    - Plan
    - LearningEngine
    - Memory systems

It only provides one controlled integration point.

The application/bootstrap layer can instantiate this class
and call:

    system.run(request)

or inspect:

    system.health()
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


logger = logging.getLogger("aria")


# ============================================================================
# OPTIONAL IMPORTS
# ============================================================================

# Goal management
try:
    from brain.goals.goal_manager import (
        GoalManager,
    )
except Exception:
    GoalManager = None


# Planning
try:
    from brain.planning.phase_planner import (
        PhasePlanner,
    )
except Exception:
    PhasePlanner = None


# Autonomous execution
try:
    from brain.execution.autonomous_executor import (
        AutonomousExecutionController,
    )
except Exception:
    AutonomousExecutionController = None


# Verification / self correction
try:
    from brain.verification.self_correction import (
        SelfCorrectionEngine,
    )
except Exception:
    SelfCorrectionEngine = None


# Experience
try:
    from brain.learning.experience_engine import (
        ExperienceEngine,
    )
except Exception:
    ExperienceEngine = None


# Experience adaptation
try:
    from brain.learning.experience_adapter import (
        ExperienceAdapter,
    )
except Exception:
    ExperienceAdapter = None


# Memory consolidation
try:
    from brain.memory.experience_consolidator import (
        ExperienceConsolidator,
    )
except Exception:
    ExperienceConsolidator = None


# Safety
try:
    from brain.safety.permission_guard import (
        PermissionGuard,
    )
except Exception:
    PermissionGuard = None


# Orchestration
try:
    from brain.orchestration.autonomous_orchestrator import (
        AutonomousOrchestrator,
    )
except Exception:
    AutonomousOrchestrator = None


# ============================================================================
# DATA MODEL
# ============================================================================

@dataclass
class Phase1Components:
    """
    Container holding all Phase 1 components.
    """

    goal_manager: Any = None

    phase_planner: Any = None

    execution_controller: Any = None

    verification_engine: Any = None

    experience_engine: Any = None

    experience_adapter: Any = None

    experience_consolidator: Any = None

    permission_guard: Any = None

    orchestrator: Any = None

    initialized: bool = False

    errors: list = field(
        default_factory=list
    )


# ============================================================================
# SYSTEM
# ============================================================================

class Phase1System:
    """
    Main integration facade for ARIA Phase 1.

    The system can operate partially if some optional dependencies
    are unavailable. Missing components are reported through
    health() instead of silently pretending they exist.
    """

    VERSION = "phase-1"

    def __init__(
        self,
        *,
        mongo_db=None,
        learning_engine=None,
        knowledge_database=None,
        canonical_executor=None,
        canonical_planner=None,
        auto_initialize: bool = True,
        max_cycles: int = 5,
        max_replans: int = 3,
    ):
        self.mongo_db = mongo_db

        self.learning_engine = (
            learning_engine
        )

        self.knowledge_database = (
            knowledge_database
        )

        self.canonical_executor = (
            canonical_executor
        )

        self.canonical_planner = (
            canonical_planner
        )

        self.max_cycles = max(
            1,
            min(
                int(max_cycles),
                5,
            ),
        )

        self.max_replans = max(
            0,
            min(
                int(max_replans),
                3,
            ),
        )

        self.components = (
            Phase1Components()
        )

        self.initialized = False

        self.statistics = {
            "initializations": 0,
            "runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "permission_blocks": 0,
            "permission_requests": 0,
            "consolidations": 0,
        }

        if auto_initialize:
            self.initialize()

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    def initialize(self) -> Phase1Components:
        """
        Build the Phase 1 component graph.

        Existing canonical planner/executor instances can be injected.
        """

        self.statistics[
            "initializations"
        ] += 1

        self.components = (
            Phase1Components()
        )

        # ------------------------------------------------------------
        # Goal Manager
        # ------------------------------------------------------------

        try:

            if GoalManager is not None:

                self.components.goal_manager = (
                    GoalManager()
                )

            else:

                self.components.errors.append(
                    "GoalManager unavailable."
                )

        except Exception as exc:

            self.components.errors.append(
                f"GoalManager: {exc}"
            )

        # ------------------------------------------------------------
        # Phase Planner
        # ------------------------------------------------------------

        try:

            if self.canonical_planner is not None:

                self.components.phase_planner = (
                    self.canonical_planner
                )

            elif PhasePlanner is not None:

                self.components.phase_planner = (
                    PhasePlanner()
                )

            else:

                self.components.errors.append(
                    "PhasePlanner unavailable."
                )

        except Exception as exc:

            self.components.errors.append(
                f"PhasePlanner: {exc}"
            )

        # ------------------------------------------------------------
        # Experience Engine
        # ------------------------------------------------------------

        try:

            if ExperienceEngine is not None:

                self.components.experience_engine = (
                    ExperienceEngine(
                        mongo_db=self.mongo_db,
                        learning_engine=(
                            self.learning_engine
                        ),
                        knowledge_database=(
                            self.knowledge_database
                        ),
                    )
                )

            else:

                self.components.errors.append(
                    "ExperienceEngine unavailable."
                )

        except Exception as exc:

            self.components.errors.append(
                f"ExperienceEngine: {exc}"
            )

        # ------------------------------------------------------------
        # Experience Adapter
        # ------------------------------------------------------------

        try:

            if (
                ExperienceAdapter is not None
                and self.components.experience_engine
                is not None
            ):

                self.components.experience_adapter = (
                    ExperienceAdapter(
                        experience_engine=(
                            self.components.experience_engine
                        )
                    )
                )

            elif ExperienceAdapter is None:

                self.components.errors.append(
                    "ExperienceAdapter unavailable."
                )

        except Exception as exc:

            self.components.errors.append(
                f"ExperienceAdapter: {exc}"
            )

        # ------------------------------------------------------------
        # Experience Consolidator
        # ------------------------------------------------------------

        try:

            if ExperienceConsolidator is not None:

                self.components.experience_consolidator = (
                    ExperienceConsolidator(
                        experience_engine=(
                            self.components.experience_engine
                        ),
                        knowledge_database=(
                            self.knowledge_database
                        ),
                        learning_engine=(
                            self.learning_engine
                        ),
                        mongo_db=self.mongo_db,
                    )
                )

            else:

                self.components.errors.append(
                    "ExperienceConsolidator unavailable."
                )

        except Exception as exc:

            self.components.errors.append(
                f"ExperienceConsolidator: {exc}"
            )

        # ------------------------------------------------------------
        # Permission Guard
        # ------------------------------------------------------------

        try:

            if PermissionGuard is not None:

                self.components.permission_guard = (
                    PermissionGuard()
                )

            else:

                self.components.errors.append(
                    "PermissionGuard unavailable."
                )

        except Exception as exc:

            self.components.errors.append(
                f"PermissionGuard: {exc}"
            )

        # ------------------------------------------------------------
        # Verification
        # ------------------------------------------------------------

        try:

            if SelfCorrectionEngine is not None:

                self.components.verification_engine = (
                    SelfCorrectionEngine()
                )

            else:

                self.components.errors.append(
                    "SelfCorrectionEngine unavailable."
                )

        except Exception as exc:

            self.components.errors.append(
                f"SelfCorrectionEngine: {exc}"
            )

        # ------------------------------------------------------------
        # Autonomous Executor
        # ------------------------------------------------------------

        try:

            if self.canonical_executor is not None:

                self.components.execution_controller = (
                    self.canonical_executor
                )

            elif (
                AutonomousExecutionController
                is not None
            ):

                self.components.execution_controller = (
                    AutonomousExecutionController()
                )

            else:

                self.components.errors.append(
                    "AutonomousExecutionController unavailable."
                )

        except Exception as exc:

            self.components.errors.append(
                f"AutonomousExecutionController: {exc}"
            )

        # ------------------------------------------------------------
        # Orchestrator
        # ------------------------------------------------------------

        try:

            if AutonomousOrchestrator is not None:

                self.components.orchestrator = (
                    AutonomousOrchestrator(
                        goal_manager=(
                            self.components.goal_manager
                        ),
                        phase_planner=(
                            self.components.phase_planner
                        ),
                        execution_controller=(
                            self.components.execution_controller
                        ),
                        verification_engine=(
                            self.components.verification_engine
                        ),
                        experience_engine=(
                            self.components.experience_engine
                        ),
                        experience_adapter=(
                            self.components.experience_adapter
                        ),
                        max_cycles=self.max_cycles,
                        max_replans=self.max_replans,
                    )
                )

            else:

                self.components.errors.append(
                    "AutonomousOrchestrator unavailable."
                )

        except Exception as exc:

            self.components.errors.append(
                f"AutonomousOrchestrator: {exc}"
            )

        self.components.initialized = True

        self.initialized = True

        return self.components

    # ========================================================================
    # COMPONENT ACCESS
    # ========================================================================

    def get(
        self,
        name: str,
    ) -> Any:
        """
        Get a Phase 1 component by name.
        """

        if not self.initialized:
            self.initialize()

        return getattr(
            self.components,
            name,
            None,
        )

    # ========================================================================
    # PERMISSION
    # ========================================================================

    def check_permission(
        self,
        action: str,
        *,
        resource: str = "",
        approved: bool = False,
        approval_token: str = "",
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Dict[str, Any]:
        """
        Check whether an action may proceed.
        """

        guard = (
            self.components.permission_guard
        )

        if guard is None:

            # Conservative fallback.
            self.statistics[
                "permission_requests"
            ] += 1

            return {
                "decision": "ask",
                "allowed": False,
                "approval_required": True,
                "blocked": False,
                "reason": (
                    "PermissionGuard unavailable; "
                    "explicit approval required."
                ),
            }

        decision = guard.check(
            action=action,
            resource=resource,
            approved=approved,
            approval_token=approval_token,
            metadata=metadata,
        )

        result = decision.to_dict()

        if decision.blocked():

            self.statistics[
                "permission_blocks"
            ] += 1

        elif decision.needs_approval():

            self.statistics[
                "permission_requests"
            ] += 1

        return result

    # ========================================================================
    # RUN
    # ========================================================================

    async def run(
        self,
        request: str,
        *,
        context: Optional[
            Dict[str, Any]
        ] = None,
        goal_id: Optional[
            str
        ] = None,
        goal_kwargs: Optional[
            Dict[str, Any]
        ] = None,
        permission_action: Optional[
            str
        ] = None,
        permission_resource: str = "",
        approved: bool = False,
        approval_token: str = "",
    ) -> Dict[str, Any]:
        """
        Main Phase 1 entry point.

        Before orchestration, an optional permission action can be
        checked. This allows callers to prevent sensitive operations
        from entering the autonomous pipeline.
        """

        if not self.initialized:
            self.initialize()

        self.statistics[
            "runs"
        ] += 1

        # ------------------------------------------------------------
        # Permission gate
        # ------------------------------------------------------------

        if permission_action:

            permission = self.check_permission(
                action=permission_action,
                resource=permission_resource,
                approved=approved,
                approval_token=approval_token,
            )

            if permission.get(
                "blocked",
                False,
            ):

                self.statistics[
                    "failed_runs"
                ] += 1

                return {
                    "success": False,
                    "status": "blocked",
                    "request": request,
                    "permission": permission,
                    "error": (
                        permission.get(
                            "reason",
                            "Action blocked.",
                        )
                    ),
                }

            if permission.get(
                "approval_required",
                False,
            ):

                self.statistics[
                    "failed_runs"
                ] += 1

                return {
                    "success": False,
                    "status": "approval_required",
                    "request": request,
                    "permission": permission,
                    "error": (
                        "User approval is required "
                        "before this action can execute."
                    ),
                }

        # ------------------------------------------------------------
        # Orchestrator
        # ------------------------------------------------------------

        orchestrator = (
            self.components.orchestrator
        )

        if orchestrator is None:

            self.statistics[
                "failed_runs"
            ] += 1

            return {
                "success": False,
                "status": "unavailable",
                "request": request,
                "error": (
                    "AutonomousOrchestrator "
                    "is not available."
                ),
            }

        try:

            result = await orchestrator.run(
                request=request,
                goal_id=goal_id,
                context=context,
                goal_kwargs=goal_kwargs,
            )

            result_dict = (
                result.to_dict()
                if hasattr(
                    result,
                    "to_dict",
                )
                else dict(
                    result
                    if isinstance(
                        result,
                        dict,
                    )
                    else {}
                )
            )

            if result_dict.get(
                "success",
                False,
            ):

                self.statistics[
                    "successful_runs"
                ] += 1

            else:

                self.statistics[
                    "failed_runs"
                ] += 1

            return result_dict

        except Exception as exc:

            logger.exception(
                "[Phase1System] "
                "System execution failed."
            )

            self.statistics[
                "failed_runs"
            ] += 1

            return {
                "success": False,
                "status": "failed",
                "request": request,
                "error": str(
                    exc
                ),
            }

    # ========================================================================
    # CONSOLIDATION
    # ========================================================================

    async def consolidate_experience(
        self,
    ) -> List[Dict[str, Any]]:
        """
        Consolidate accumulated execution experiences.
        """

        consolidator = (
            self.components.experience_consolidator
        )

        if consolidator is None:
            return []

        try:

            memories = await consolidator.consolidate()

            self.statistics[
                "consolidations"
            ] += 1

            return [
                memory.to_dict()
                if hasattr(
                    memory,
                    "to_dict",
                )
                else dict(
                    memory
                )
                for memory in memories
            ]

        except Exception:

            logger.exception(
                "[Phase1System] "
                "Experience consolidation failed."
            )

            return []

    # ========================================================================
    # CANCELLATION
    # ========================================================================

    def cancel(self) -> bool:
        """
        Cancel the current orchestration run.
        """

        orchestrator = (
            self.components.orchestrator
        )

        if orchestrator is None:
            return False

        try:

            cancel = getattr(
                orchestrator,
                "cancel",
                None,
            )

            if callable(cancel):

                cancel()

                return True

        except Exception:

            logger.exception(
                "[Phase1System] "
                "Cancellation failed."
            )

        return False

    # ========================================================================
    # STATUS
    # ========================================================================

    def status(self) -> Dict[str, Any]:

        orchestrator = (
            self.components.orchestrator
        )

        if orchestrator is None:

            return {
                "initialized": self.initialized,
                "state": "unavailable",
            }

        try:

            status_method = getattr(
                orchestrator,
                "status",
                None,
            )

            if callable(status_method):

                return {
                    "initialized": (
                        self.initialized
                    ),
                    **status_method(),
                }

        except Exception:
            pass

        return {
            "initialized": self.initialized,
            "state": "unknown",
        }

    # ========================================================================
    # HEALTH
    # ========================================================================

    def health(
        self,
    ) -> Dict[str, Any]:
        """
        Return system-wide health.
        """

        if not self.initialized:
            self.initialize()

        components = {}

        for name in (
            "goal_manager",
            "phase_planner",
            "execution_controller",
            "verification_engine",
            "experience_engine",
            "experience_adapter",
            "experience_consolidator",
            "permission_guard",
            "orchestrator",
        ):

            component = getattr(
                self.components,
                name,
                None,
            )

            if component is None:

                components[name] = {
                    "available": False,
                    "status": "unavailable",
                }

                continue

            health_method = getattr(
                component,
                "health",
                None,
            )

            if callable(
                health_method
            ):

                try:

                    components[name] = {
                        "available": True,
                        **dict(
                            health_method()
                        ),
                    }

                    continue

                except Exception as exc:

                    components[name] = {
                        "available": True,
                        "status": "error",
                        "error": str(
                            exc
                        ),
                    }

                    continue

            components[name] = {
                "available": True,
                "status": "loaded",
            }

        required = (
            "goal_manager",
            "phase_planner",
            "execution_controller",
            "verification_engine",
            "experience_engine",
            "experience_adapter",
            "permission_guard",
            "orchestrator",
        )

        missing_required = [
            name
            for name in required
            if not components[
                name
            ].get(
                "available",
                False,
            )
        ]

        system_status = (
            "healthy"
            if not missing_required
            else "partial"
        )

        return {
            "component": "phase1_system",
            "version": self.VERSION,
            "status": system_status,
            "initialized": self.initialized,
            "missing_required": (
                missing_required
            ),
            "initialization_errors": list(
                self.components.errors
            ),
            "components": components,
            "statistics": dict(
                self.statistics
            ),
        }

    # ========================================================================
    # DESCRIPTION
    # ========================================================================

    def describe(
        self,
    ) -> Dict[str, Any]:

        return {
            "component": "Phase1System",
            "version": self.VERSION,
            "purpose": (
                "Single integration facade for "
                "ARIA Phase 1 autonomous architecture."
            ),
            "entry_points": [
                "run",
                "check_permission",
                "consolidate_experience",
                "cancel",
                "status",
                "health",
            ],
            "pipeline": [
                "GoalManager",
                "PhasePlanner",
                "PermissionGuard",
                "AutonomousExecutionController",
                "SelfCorrectionEngine",
                "ExperienceEngine",
                "ExperienceAdapter",
                "ExperienceConsolidator",
                "AutonomousOrchestrator",
            ],
            "does_not_replace": [
                "brain.executor.Executor",
                "brain.planning.planner",
                "brain.task.Task",
                "brain.plan.ExecutionPlan",
                "existing LearningEngine",
            ],
        }


# ============================================================================
# FACTORY
# ============================================================================

def create_phase1_system(
    *,
    mongo_db=None,
    learning_engine=None,
    knowledge_database=None,
    canonical_executor=None,
    canonical_planner=None,
    auto_initialize: bool = True,
    max_cycles: int = 5,
    max_replans: int = 3,
) -> Phase1System:
    """
    Convenience factory for ARIA startup/bootstrap code.
    """

    return Phase1System(
        mongo_db=mongo_db,
        learning_engine=learning_engine,
        knowledge_database=knowledge_database,
        canonical_executor=canonical_executor,
        canonical_planner=canonical_planner,
        auto_initialize=auto_initialize,
        max_cycles=max_cycles,
        max_replans=max_replans,
    )