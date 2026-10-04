"""Contract describing the authoritative engineering session.

Step 2 defines the interface shape only. Step 3 will implement the mutable
session and lifecycle ownership behind this contract.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from .engineering_evidence import EngineeringEvidence
from .engineering_state import EngineeringPhase, EngineeringState


class EngineeringSessionContract(Protocol):
    """Stable interface expected by future engineering subsystems."""

    @property
    def session_id(self) -> str:
        """Return the stable identifier for the engineering session."""

    @property
    def state(self) -> EngineeringState:
        """Return the current authoritative state."""

    @property
    def phase(self) -> EngineeringPhase:
        """Return the current lifecycle phase."""

    def add_evidence(
        self,
        evidence: EngineeringEvidence,
    ) -> None:
        """Record immutable evidence and associate its ID with the session."""

    def evidence(
        self,
        evidence_id: str,
    ) -> EngineeringEvidence | None:
        """Retrieve one recorded evidence item."""

    def evidence_ids(self) -> Sequence[str]:
        """Return evidence IDs in insertion order."""

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable session snapshot."""