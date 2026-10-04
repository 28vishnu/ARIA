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
]