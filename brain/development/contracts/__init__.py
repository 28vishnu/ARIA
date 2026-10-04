"""Authoritative engineering contracts for ARIA Phase 1.

This package contains the stable contracts shared by the autonomous
engineering lifecycle.
"""

from .engineering_state import (
    EngineeringPhase,
    EngineeringState,
)

from .engineering_evidence import (
    EvidenceKind,
    EngineeringEvidence,
)

from .engineering_requirement import (
    RequirementIntent,
    PermissionScope,
    EngineeringPermission,
    EngineeringRequirement,
)

from .repository_model import (
    RepositoryPathKind,
    RepositoryComponentKind,
    RepositoryPath,
    RepositoryComponent,
    RepositoryModel,
)

from .repository_scan_policy import (
    RepositoryScanPolicy,
)

from .engineering_knowledge import (
    KnowledgeKind,
    KnowledgeAuthority,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeContext,
    EngineeringKnowledgePolicy,
)

from .engineering_plan import (
    PlanStatus,
    PlanChangeReason,
    EngineeringPlanStep,
    PlanRevision,
    AdaptiveEngineeringPlan,
)

from .engineering_task_graph import (
    EngineeringTaskKind,
    EngineeringTaskStatus,
    EngineeringTask,
    EngineeringTaskGraph,
)

from .engineering_implementation import (
    ImplementationStatus,
    ImplementationRequest,
    ImplementationChange,
    ImplementationEvidence,
    ImplementationResult,
)

from .engineering_verification import (
    VerificationDimension,
    VerificationStatus,
    VerificationAction,
    VerificationRequirement,
    VerificationFinding,
    VerificationDecision,
    VerificationRequest,
    VerificationResult,
)

from .engineering_diagnosis import (
    DiagnosisCategory,
    DiagnosisConfidence,
    DiagnosisAction,
    DiagnosisEvidence,
    RootCauseHypothesis,
    DiagnosisRequest,
    DiagnosisDecision,
    DiagnosisResult,
    confidence_level,
)

from .engineering_session import (
    SessionTransition,
    EngineeringSession,
    AuthoritativeEngineeringSession,
)

from .engineering_lifecycle import (
    EngineeringLifecycle,
    LifecycleExecutionRecord,
)

from .engineering_store import (
    EngineeringStore,
)

from .engineering_result import (
    EngineeringOutcome,
    EngineeringResult,
)


__all__ = [
    # ==============================================================
    # State
    # ==============================================================

    "EngineeringPhase",
    "EngineeringState",

    # ==============================================================
    # Evidence
    # ==============================================================

    "EvidenceKind",
    "EngineeringEvidence",

    # ==============================================================
    # Requirement
    # ==============================================================

    "RequirementIntent",
    "PermissionScope",
    "EngineeringPermission",
    "EngineeringRequirement",

    # ==============================================================
    # Repository
    # ==============================================================

    "RepositoryPathKind",
    "RepositoryComponentKind",
    "RepositoryPath",
    "RepositoryComponent",
    "RepositoryModel",
    "RepositoryScanPolicy",

    # ==============================================================
    # Knowledge
    # ==============================================================

    "KnowledgeKind",
    "KnowledgeAuthority",
    "EngineeringKnowledgeItem",
    "EngineeringKnowledgeContext",
    "EngineeringKnowledgePolicy",

    # ==============================================================
    # Planning
    # ==============================================================

    "PlanStatus",
    "PlanChangeReason",
    "EngineeringPlanStep",
    "PlanRevision",
    "AdaptiveEngineeringPlan",

    # ==============================================================
    # Task Graph
    # ==============================================================

    "EngineeringTaskKind",
    "EngineeringTaskStatus",
    "EngineeringTask",
    "EngineeringTaskGraph",

    # ==============================================================
    # Implementation
    # ==============================================================

    "ImplementationStatus",
    "ImplementationRequest",
    "ImplementationChange",
    "ImplementationEvidence",
    "ImplementationResult",

    # ==============================================================
    # Verification
    # ==============================================================

    "VerificationDimension",
    "VerificationStatus",
    "VerificationAction",
    "VerificationRequirement",
    "VerificationFinding",
    "VerificationDecision",
    "VerificationRequest",
    "VerificationResult",

    # ==============================================================
    # Diagnosis
    # ==============================================================

    "DiagnosisCategory",
    "DiagnosisConfidence",
    "DiagnosisAction",
    "DiagnosisEvidence",
    "RootCauseHypothesis",
    "DiagnosisRequest",
    "DiagnosisDecision",
    "DiagnosisResult",
    "confidence_level",

    # ==============================================================
    # Session
    # ==============================================================

    "SessionTransition",
    "EngineeringSession",
    "AuthoritativeEngineeringSession",

    # ==============================================================
    # Lifecycle
    # ==============================================================

    "EngineeringLifecycle",
    "LifecycleExecutionRecord",

    # ==============================================================
    # Persistence
    # ==============================================================

    "EngineeringStore",

    # ==============================================================
    # Result
    # ==============================================================

    "EngineeringOutcome",
    "EngineeringResult",
]