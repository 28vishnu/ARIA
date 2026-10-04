"""Stable contracts for ARIA's autonomous engineering lifecycle."""

from .engineering_state import (
    EngineeringPhase,
    EngineeringState,
    TERMINAL_PHASES,
)
from .engineering_evidence import (
    EvidenceKind,
    EngineeringEvidence,
)
from .engineering_session import (
    EngineeringSession,
    AuthoritativeEngineeringSession,
    EngineeringSessionContract,
    SessionTransition,
)
from .engineering_result import (
    EngineeringOutcome,
    EngineeringResult,
)
from .engineering_lifecycle import (
    LifecycleHook,
    LifecycleStep,
    LifecycleExecution,
    EngineeringLifecycle,
)
from .engineering_store import (
    EngineeringStore,
    EngineeringStoreError,
    EngineeringSessionNotFound,
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
    DEFAULT_REPOSITORY_SCAN_POLICY,
)

__all__ = [
    "EngineeringPhase",
    "EngineeringState",
    "TERMINAL_PHASES",
    "EvidenceKind",
    "EngineeringEvidence",
    "EngineeringSession",
    "AuthoritativeEngineeringSession",
    "EngineeringSessionContract",
    "SessionTransition",
    "EngineeringOutcome",
    "EngineeringResult",
    "LifecycleHook",
    "LifecycleStep",
    "LifecycleExecution",
    "EngineeringStore",
    "EngineeringStoreError",
    "EngineeringSessionNotFound",
    "RequirementIntent",
    "PermissionScope",
    "EngineeringPermission",
    "EngineeringRequirement",
    "RepositoryPathKind",
    "RepositoryComponentKind",
    "RepositoryPath",
    "RepositoryComponent",
    "RepositoryModel",
    "RepositoryScanPolicy",
    "DEFAULT_REPOSITORY_SCAN_POLICY",
]