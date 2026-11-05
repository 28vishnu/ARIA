"""Structured requirement contract for ARIA autonomous engineering.

Step 6 converts a human engineering request into a durable, explicit
requirement object.

The requirement contract separates:
- what the user wants
- what ARIA must accomplish
- what ARIA must not do
- what permissions were granted
- how success will be recognized

This module performs no code generation, repository modification, testing,
deployment, GitHub operations, or autonomous execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence


class RequirementIntent(str, Enum):
    """High-level engineering intents understood by ARIA."""

    CREATE = "create"
    MODIFY = "modify"
    FIX = "fix"
    REFACTOR = "refactor"
    TEST = "test"
    VERIFY = "verify"
    INVESTIGATE = "investigate"
    UPGRADE = "upgrade"
    IMPLEMENT_PHASE = "implement_phase"
    DEPLOY = "deploy"
    MAINTAIN = "maintain"
    UNKNOWN = "unknown"


class PermissionScope(str, Enum):
    """Explicitly controllable engineering permissions."""

    READ_REPOSITORY = "read_repository"
    WRITE_WORKSPACE = "write_workspace"
    MODIFY_PRODUCTION = "modify_production"
    RUN_TESTS = "run_tests"
    RUN_COMMANDS = "run_commands"
    GIT_BRANCH = "git_branch"
    GIT_COMMIT = "git_commit"
    GITHUB_PUSH = "github_push"
    CREATE_PR = "create_pr"
    DEPLOY = "deploy"
    ROLLBACK = "rollback"


@dataclass(frozen=True)
class EngineeringPermission:
    """One explicit permission decision."""

    scope: PermissionScope
    granted: bool
    source: str = "user"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.value,
            "granted": self.granted,
            "source": self.source,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class EngineeringRequirement:
    """Complete structured representation of a user's request."""

    requirement_id: str

    raw_request: str
    intent: RequirementIntent

    goal: str
    objective: str

    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    requested_paths: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()

    permissions: tuple[
        EngineeringPermission,
        ...,
    ] = ()

    explicit_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()

    ambiguity_notes: tuple[str, ...] = ()

    confidence: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.requirement_id.strip():
            raise ValueError(
                "requirement_id must not be empty."
            )

        if not self.raw_request.strip():
            raise ValueError(
                "raw_request must not be empty."
            )

        if not self.goal.strip():
            raise ValueError(
                "goal must not be empty."
            )

        if not self.objective.strip():
            raise ValueError(
                "objective must not be empty."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

    # ------------------------------------------------------------------
    # Permission helpers
    # ------------------------------------------------------------------

    def permission(
        self,
        scope: PermissionScope,
    ) -> bool:
        """Return whether a specific action is explicitly permitted."""

        for item in self.permissions:
            if item.scope is scope:
                return item.granted

        return False

    def has_write_authority(self) -> bool:
        return self.permission(
            PermissionScope.WRITE_WORKSPACE
        )

    def can_modify_production(self) -> bool:
        return self.permission(
            PermissionScope.MODIFY_PRODUCTION
        )

    def can_push_github(self) -> bool:
        return self.permission(
            PermissionScope.GITHUB_PUSH
        )

    def can_deploy(self) -> bool:
        return self.permission(
            PermissionScope.DEPLOY
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "raw_request": self.raw_request,
            "intent": self.intent.value,
            "goal": self.goal,
            "objective": self.objective,
            "constraints": list(self.constraints),
            "acceptance_criteria": list(
                self.acceptance_criteria
            ),
            "requested_paths": list(
                self.requested_paths
            ),
            "protected_paths": list(
                self.protected_paths
            ),
            "permissions": [
                item.to_dict()
                for item in self.permissions
            ],
            "explicit_actions": list(
                self.explicit_actions
            ),
            "forbidden_actions": list(
                self.forbidden_actions
            ),
            "ambiguity_notes": list(
                self.ambiguity_notes
            ),
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "EngineeringRequirement":
        if not isinstance(
            payload,
            dict,
        ):
            raise TypeError(
                "EngineeringRequirement payload "
                "must be a dictionary."
            )

        raw_intent = payload.get(
            "intent",
            RequirementIntent.UNKNOWN.value,
        )

        try:
            intent = RequirementIntent(
                str(raw_intent)
            )
        except ValueError:
            intent = RequirementIntent.UNKNOWN

        permissions: list[
            EngineeringPermission
        ] = []

        for item in payload.get(
            "permissions",
            [],
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue

            try:
                scope = PermissionScope(
                    str(
                        item.get(
                            "scope"
                        )
                    )
                )
            except ValueError:
                continue

            permissions.append(
                EngineeringPermission(
                    scope=scope,
                    granted=bool(
                        item.get(
                            "granted",
                            False,
                        )
                    ),
                    source=str(
                        item.get(
                            "source",
                            "unknown",
                        )
                    ),
                    reason=str(
                        item.get(
                            "reason",
                            "",
                        )
                    ),
                )
            )

        return cls(
            requirement_id=str(
                payload.get(
                    "requirement_id",
                    "",
                )
            ),
            raw_request=str(
                payload.get(
                    "raw_request",
                    "",
                )
            ),
            intent=intent,
            goal=str(
                payload.get(
                    "goal",
                    "",
                )
            ),
            objective=str(
                payload.get(
                    "objective",
                    "",
                )
            ),
            constraints=_string_tuple(
                payload.get(
                    "constraints"
                )
            ),
            acceptance_criteria=_string_tuple(
                payload.get(
                    "acceptance_criteria"
                )
            ),
            requested_paths=_string_tuple(
                payload.get(
                    "requested_paths"
                )
            ),
            protected_paths=_string_tuple(
                payload.get(
                    "protected_paths"
                )
            ),
            permissions=tuple(
                permissions
            ),
            explicit_actions=_string_tuple(
                payload.get(
                    "explicit_actions"
                )
            ),
            forbidden_actions=_string_tuple(
                payload.get(
                    "forbidden_actions"
                )
            ),
            ambiguity_notes=_string_tuple(
                payload.get(
                    "ambiguity_notes"
                )
            ),
            confidence=float(
                payload.get(
                    "confidence",
                    0.0,
                )
            ),
            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )


def _string_tuple(
    value: Any,
) -> tuple[str, ...]:
    if value is None:
        return ()

    if isinstance(
        value,
        str,
    ):
        return (value,)

    if not isinstance(
        value,
        (list, tuple, set),
    ):
        raise TypeError(
            "Expected a string or sequence of strings."
        )

    return tuple(
        str(item)
        for item in value
    )


__all__ = [
    "RequirementIntent",
    "PermissionScope",
    "EngineeringPermission",
    "EngineeringRequirement",
]