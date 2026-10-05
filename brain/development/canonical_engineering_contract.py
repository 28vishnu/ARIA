from __future__ import annotations

"""
Canonical Phase 1 engineering-runtime contract.

This module does not execute engineering work.

It defines and validates the single authoritative runtime boundary used by
ARIA so that legacy/compatibility development systems cannot accidentally
become the primary engineering execution path.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CanonicalEngineeringRuntimeContract:
    """
    Read-only description of ARIA's authoritative engineering spine.

    There must be exactly one authoritative execution chain:

        Phase1PersistentRuntimeAdapter
                    ↓
        FinalAutonomousEngineer
                    ↓
        AuthoritativeEngineeringOrchestrator
                    ↓
        Engineering lifecycle
    """

    name: str = "aria.authoritative.engineering"
    version: str = "1.0"

    authoritative: bool = True

    execution_owner: str = "FinalAutonomousEngineer"

    orchestration_owner: str = (
        "AuthoritativeEngineeringOrchestrator"
    )

    runtime_owner: str = (
        "Phase1PersistentRuntimeAdapter"
    )

    persistence_owner: str = (
        "PersistentEngineeringRuntime"
    )

    github_push_requires_authorization: bool = True

    deployment_requires_authorization: bool = True

    production_direct_write: bool = False

    @property
    def lifecycle(self) -> tuple[str, ...]:
        """
        The only authoritative Phase 1 engineering lifecycle.

        Ordering is intentional and must not be changed casually.
        """

        return (
            "requirement",
            "knowledge",
            "planning",
            "task_graph",
            "implementation",
            "verification",
            "diagnosis",
            "recovery",
            "acceptance",
            "experience",
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Return a JSON-safe description of the canonical contract.
        """

        return {
            "name": self.name,
            "version": self.version,
            "authoritative": self.authoritative,
            "execution_owner": self.execution_owner,
            "orchestration_owner": (
                self.orchestration_owner
            ),
            "runtime_owner": self.runtime_owner,
            "persistence_owner": (
                self.persistence_owner
            ),
            "lifecycle": list(
                self.lifecycle
            ),
            "github_push_requires_authorization": (
                self.github_push_requires_authorization
            ),
            "deployment_requires_authorization": (
                self.deployment_requires_authorization
            ),
            "production_direct_write": (
                self.production_direct_write
            ),
        }

    def validate_runtime(
        self,
        runtime: Any,
    ) -> dict[str, Any]:
        """
        Validate the supplied runtime without executing engineering work.

        This method is intentionally read-only.

        It checks the actual object graph:

            runtime
                ↓
            final_engineer
                ↓
            orchestrator

        and also verifies that the persistent runtime is the expected
        canonical implementation.
        """

        final_engineer = getattr(
            runtime,
            "final_engineer",
            None,
        )

        persistent_runtime = getattr(
            runtime,
            "_persistent_runtime",
            None,
        )

        checks = {
            "runtime_is_present": (
                runtime is not None
            ),

            "final_engineer_present": (
                final_engineer is not None
            ),

            "final_engineer_is_canonical_type": (
                final_engineer is not None
                and type(
                    final_engineer
                ).__name__
                == self.execution_owner
            ),

            "orchestrator_present": (
                final_engineer is not None
                and getattr(
                    final_engineer,
                    "orchestrator",
                    None,
                ) is not None
            ),

            "orchestrator_is_canonical_type": (
                final_engineer is not None
                and getattr(
                    final_engineer,
                    "orchestrator",
                    None,
                ) is not None
                and type(
                    getattr(
                        final_engineer,
                        "orchestrator",
                    )
                ).__name__
                == self.orchestration_owner
            ),

            "persistent_runtime_present": (
                persistent_runtime is not None
            ),

            "persistent_runtime_is_canonical_type": (
                persistent_runtime is not None
                and type(
                    persistent_runtime
                ).__name__
                == self.persistence_owner
            ),

            "runtime_exposes_develop": callable(
                getattr(
                    runtime,
                    "develop",
                    None,
                )
            ),

            "runtime_exposes_resume": callable(
                getattr(
                    runtime,
                    "resume",
                    None,
                )
            ),

            "runtime_exposes_status": callable(
                getattr(
                    runtime,
                    "status",
                    None,
                )
            ),

            "runtime_exposes_health": callable(
                getattr(
                    runtime,
                    "health",
                    None,
                )
            ),
        }

        failures = [
            name
            for name, passed in checks.items()
            if not passed
        ]

        return {
            "contract": self.to_dict(),
            "healthy": not failures,
            "checks": checks,
            "failures": failures,
        }


CANONICAL_ENGINEERING_RUNTIME = (
    CanonicalEngineeringRuntimeContract()
)


__all__ = [
    "CanonicalEngineeringRuntimeContract",
    "CANONICAL_ENGINEERING_RUNTIME",
]
