"""Stable contracts for ARIA's autonomous engineering lifecycle.

Step 2 introduces data contracts only. These contracts do not execute work,
modify repositories, run commands, deploy, or change production state.
"""

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
    EngineeringSessionContract,
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
    "EngineeringSessionContract",
    "EngineeringOutcome",
    "EngineeringResult",
]