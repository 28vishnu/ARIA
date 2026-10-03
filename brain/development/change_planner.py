from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .requirement_parser import Requirement


@dataclass(frozen=True)
class FileChange:
    path: str
    action: str
    reason: str
    risk: str = "low"

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "action": self.action,
            "reason": self.reason,
            "risk": self.risk,
        }


@dataclass(frozen=True)
class ChangePlan:
    requirement: Requirement
    changes: tuple[FileChange, ...] = ()
    tests: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    requires_approval: bool = False
    blocked: bool = False
    block_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": (
                self.requirement.to_dict()
            ),
            "changes": [
                change.to_dict()
                for change in self.changes
            ],
            "tests": list(self.tests),
            "risks": list(self.risks),
            "requires_approval": (
                self.requires_approval
            ),
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


class ChangePlanner:
    """
    Builds a conservative implementation plan.

    It does not modify source code.

    It identifies whether explicitly referenced files are new
    or existing and marks high-risk/protected paths.
    """

    PROTECTED_PREFIXES = (
        ".git/",
        ".github/workflows/",
        ".aria_workspaces/",
    )

    PROTECTED_NAMES = (
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
    )

    def plan(
        self,
        requirement: Requirement,
        *,
        existing_paths: Iterable[str] = (),
    ) -> ChangePlan:

        if not isinstance(
            requirement,
            Requirement,
        ):
            raise TypeError(
                "requirement must be a Requirement."
            )

        existing = {
            str(path)
            .replace("\\", "/")
            .lstrip("./")
            for path in existing_paths
        }

        changes: list[FileChange] = []
        risks = list(
            requirement.risk_flags
        )

        blocked = False
        block_reason: str | None = None

        for path in requirement.requested_files:

            normalized = (
                path
                .replace("\\", "/")
                .lstrip("./")
            )

            if (
                normalized
                in self.PROTECTED_NAMES
                or any(
                    normalized.startswith(prefix)
                    for prefix in self.PROTECTED_PREFIXES
                )
            ):
                blocked = True
                block_reason = (
                    "Protected path requested: "
                    f"{normalized}"
                )

                risks.append(
                    "protected_path"
                )

                continue

            action = (
                "modify"
                if normalized in existing
                else "create"
            )

            risk = (
                "high"
                if normalized
                in {
                    "main.py",
                    "core/bootstrap.py",
                }
                else "low"
            )

            changes.append(
                FileChange(
                    path=normalized,
                    action=action,
                    reason=(
                        "Explicitly referenced "
                        "by the requirement."
                    ),
                    risk=risk,
                )
            )

        if not changes and not blocked:

            changes.append(
                FileChange(
                    path="",
                    action="inspect",
                    reason=(
                        "No explicit file path was "
                        "supplied; implementation must "
                        "inspect the repository before "
                        "selecting files."
                    ),
                    risk="medium",
                )
            )

        tests = list(
            requirement.acceptance_criteria
        )

        if not tests:
            tests = [
                "Run relevant existing tests and "
                "static validation after changes."
            ]

        requires_approval = (
            requirement.requires_approval
            or any(
                change.risk == "high"
                for change in changes
            )
        )

        return ChangePlan(
            requirement=requirement,
            changes=tuple(changes),
            tests=tuple(
                dict.fromkeys(tests)
            ),
            risks=tuple(
                dict.fromkeys(risks)
            ),
            requires_approval=(
                requires_approval
            ),
            blocked=blocked,
            block_reason=block_reason,
        )