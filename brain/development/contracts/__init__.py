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

from .engineering_session import (
    EngineeringSession,
    SessionTransition,
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
)

from .engineering_recovery import (
    RecoveryAction,
    RecoveryStatus,
    RecoveryRequest,
    RepairRequest,
    RetestRequest,
    RecoveryDecision,
    RecoveryResult,
)

from .engineering_acceptance import (
    AcceptanceStatus,
    AcceptanceDecision,
    AcceptanceCriterionStatus,
    AcceptanceCriterion,
    AcceptanceFinding,
    AcceptanceRequest,
    AcceptanceDecisionResult,
)

from .engineering_experience import (
    ExperienceKind,
    ExperienceOutcome,
    EngineeringExperience,
    ExperienceQuery,
    ExperienceMatch,
    EngineeringExperienceContext,
    ExperienceLearningResult,
)

from .self_modification import (
    SelfModificationKind,
    SelfModificationRisk,
    SelfModificationScope,
    SelfModificationStatus,
    SelfModificationAction,
    SelfModificationTarget,
    SelfModificationConstraint,
    SelfModificationVerification,
    SelfModificationRollback,
    SelfModificationPlan,
    SelfModificationRequest,
    SelfModificationDecision,
)

from .self_upgrade_gate import (
    UpgradeGateStatus,
    UpgradeGateAction,
    UpgradeAuthority,
    UpgradeAuthorization,
    UpgradeGateFinding,
    SelfUpgradeGateRequest,
    SelfUpgradeGateDecision,
)

from .engineering_git import (
    GitOperation,
    GitLifecycleStatus,
    GitRisk,
    GitAuthorization,
    GitLifecyclePlan,
    GitLifecycleRequest,
    GitLifecycleResult,
)

from .engineering_deployment import (
    DeploymentOperation,
    DeploymentStatus,
    DeploymentRisk,
    DeploymentAuthorization,
    HealthCheckDefinition,
    DeploymentRollbackPlan,
    DeploymentPlan,
    DeploymentRequest,
    HealthCheckResult,
    DeploymentResult,
)

from .telegram_engineering import (
    TelegramAuthorizationStatus,
    TelegramEngineeringAction,
    TelegramEngineeringCommand,
    TelegramEngineeringRequest,
    TelegramEngineeringResponse,
)


__all__ = [
    # ------------------------------------------------------------
    # Engineering state
    # ------------------------------------------------------------
    "EngineeringPhase",
    "EngineeringState",

    # ------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------
    "EvidenceKind",
    "EngineeringEvidence",

    # ------------------------------------------------------------
    # Requirement
    # ------------------------------------------------------------
    "RequirementIntent",
    "PermissionScope",
    "EngineeringPermission",
    "EngineeringRequirement",

    # ------------------------------------------------------------
    # Repository model
    # ------------------------------------------------------------
    "RepositoryPathKind",
    "RepositoryComponentKind",
    "RepositoryPath",
    "RepositoryComponent",
    "RepositoryModel",
    "RepositoryScanPolicy",

    # ------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------
    "KnowledgeKind",
    "KnowledgeAuthority",
    "EngineeringKnowledgeItem",
    "EngineeringKnowledgeContext",
    "EngineeringKnowledgePolicy",

    # ------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------
    "PlanStatus",
    "PlanChangeReason",
    "EngineeringPlanStep",
    "PlanRevision",
    "AdaptiveEngineeringPlan",

    # ------------------------------------------------------------
    # Task graph
    # ------------------------------------------------------------
    "EngineeringTaskKind",
    "EngineeringTaskStatus",
    "EngineeringTask",
    "EngineeringTaskGraph",

    # ------------------------------------------------------------
    # Engineering session
    # ------------------------------------------------------------
    "EngineeringSession",
    "SessionTransition",
    "AuthoritativeEngineeringSession",

    # ------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------
    "EngineeringLifecycle",
    "LifecycleExecutionRecord",

    # ------------------------------------------------------------
    # Persistent store
    # ------------------------------------------------------------
    "EngineeringStore",

    # ------------------------------------------------------------
    # Engineering result
    # ------------------------------------------------------------
    "EngineeringOutcome",
    "EngineeringResult",

    # ------------------------------------------------------------
    # Autonomous implementation
    # ------------------------------------------------------------
    "ImplementationStatus",
    "ImplementationRequest",
    "ImplementationChange",
    "ImplementationEvidence",
    "ImplementationResult",

    # ------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------
    "VerificationDimension",
    "VerificationStatus",
    "VerificationAction",
    "VerificationRequirement",
    "VerificationFinding",
    "VerificationDecision",
    "VerificationRequest",
    "VerificationResult",

    # ------------------------------------------------------------
    # Root-cause diagnosis
    # ------------------------------------------------------------
    "DiagnosisCategory",
    "DiagnosisConfidence",
    "DiagnosisAction",
    "DiagnosisEvidence",
    "RootCauseHypothesis",
    "DiagnosisRequest",
    "DiagnosisDecision",
    "DiagnosisResult",

    # ------------------------------------------------------------
    # Recovery / repair / retest
    # ------------------------------------------------------------
    "RecoveryAction",
    "RecoveryStatus",
    "RecoveryRequest",
    "RepairRequest",
    "RetestRequest",
    "RecoveryDecision",
    "RecoveryResult",

    # ------------------------------------------------------------
    # Acceptance / engineering judgment
    # ------------------------------------------------------------
    "AcceptanceStatus",
    "AcceptanceDecision",
    "AcceptanceCriterionStatus",
    "AcceptanceCriterion",
    "AcceptanceFinding",
    "AcceptanceRequest",
    "AcceptanceDecisionResult",

    # ------------------------------------------------------------
    # Engineering experience / learning
    # ------------------------------------------------------------
    "ExperienceKind",
    "ExperienceOutcome",
    "EngineeringExperience",
    "ExperienceQuery",
    "ExperienceMatch",
    "EngineeringExperienceContext",
    "ExperienceLearningResult",

    # ------------------------------------------------------------
    # Self-modification
    # ------------------------------------------------------------
    "SelfModificationKind",
    "SelfModificationRisk",
    "SelfModificationScope",
    "SelfModificationStatus",
    "SelfModificationAction",
    "SelfModificationTarget",
    "SelfModificationConstraint",
    "SelfModificationVerification",
    "SelfModificationRollback",
    "SelfModificationPlan",
    "SelfModificationRequest",
    "SelfModificationDecision",

    # ------------------------------------------------------------
    # Self-upgrade safety gate
    # ------------------------------------------------------------
    "UpgradeGateStatus",
    "UpgradeGateAction",
    "UpgradeAuthority",
    "UpgradeAuthorization",
    "UpgradeGateFinding",
    "SelfUpgradeGateRequest",
    "SelfUpgradeGateDecision",

    # ------------------------------------------------------------
    # Git / GitHub lifecycle
    # ------------------------------------------------------------
    "GitOperation",
    "GitLifecycleStatus",
    "GitRisk",
    "GitAuthorization",
    "GitLifecyclePlan",
    "GitLifecycleRequest",
    "GitLifecycleResult",

    # ------------------------------------------------------------
    # Deployment / health / rollback
    # ------------------------------------------------------------
    "DeploymentOperation",
    "DeploymentStatus",
    "DeploymentRisk",
    "DeploymentAuthorization",
    "HealthCheckDefinition",
    "DeploymentRollbackPlan",
    "DeploymentPlan",
    "DeploymentRequest",
    "HealthCheckResult",
    "DeploymentResult",

    # ------------------------------------------------------------
    # Telegram engineering interface
    # ------------------------------------------------------------
    "TelegramAuthorizationStatus",
    "TelegramEngineeringAction",
    "TelegramEngineeringCommand",
    "TelegramEngineeringRequest",
    "TelegramEngineeringResponse",
]