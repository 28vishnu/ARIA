from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Requirement:
    raw_text: str
    summary: str
    goals: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    requested_files: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    requires_approval: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "summary": self.summary,
            "goals": list(self.goals),
            "constraints": list(self.constraints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "requested_files": list(self.requested_files),
            "risk_flags": list(self.risk_flags),
            "requires_approval": self.requires_approval,
            "metadata": dict(self.metadata),
        }


class RequirementParser:
    """
    Deterministically converts a Master's request into structured
    requirements.

    This component does not generate code and does not modify files.

    Ambiguous requirements are preserved instead of silently
    inventing implementation details.
    """

    _RISK_TERMS = (
        "secret",
        "password",
        "token",
        "credential",
        "api key",
        "production",
        "deploy",
        "deployment",
        "delete",
        "database",
        "security",
        "authentication",
        "authorization",
        "github actions",
        "workflow",
        ".env",
        "dockerfile",
    )

    _APPROVAL_TERMS = (
        "production",
        "deploy",
        "deployment",
        "delete",
        "remove",
        "secret",
        "credential",
        "authentication",
        "authorization",
        "github workflow",
        "workflow",
    )

    def parse(
        self,
        text: str,
    ) -> Requirement:
        if not isinstance(text, str):
            raise TypeError(
                "Requirement must be a string."
            )

        raw = text.strip()

        if not raw:
            raise ValueError(
                "Requirement cannot be empty."
            )

        lines = [
            line.strip(" -\t")
            for line in raw.splitlines()
            if line.strip()
        ]

        goals: list[str] = []
        constraints: list[str] = []
        criteria: list[str] = []
        requested_files: list[str] = []

        for line in lines:
            lower = line.lower()

            if any(
                keyword in lower
                for keyword in (
                    "must ",
                    "should ",
                    "needs to ",
                    "need to ",
                    "want ",
                )
            ):
                goals.append(line)

            if any(
                keyword in lower
                for keyword in (
                    "only ",
                    "without ",
                    "do not ",
                    "don't ",
                    "never ",
                    "must not ",
                )
            ):
                constraints.append(line)

            if any(
                keyword in lower
                for keyword in (
                    "test",
                    "verify",
                    "pass",
                    "working",
                    "acceptance",
                    "expected",
                )
            ):
                criteria.append(line)

            for token in line.replace(
                "`",
                " ",
            ).split():

                cleaned = token.strip(
                    ".,:;()[]{}"
                )

                if (
                    "/" in cleaned
                    or cleaned.endswith(
                        (
                            ".py",
                            ".json",
                            ".yaml",
                            ".yml",
                            ".toml",
                        )
                    )
                ):
                    requested_files.append(
                        cleaned
                    )

        lower_raw = raw.lower()

        risk_flags = sorted(
            {
                term
                for term in self._RISK_TERMS
                if term in lower_raw
            }
        )

        requires_approval = any(
            term in lower_raw
            for term in self._APPROVAL_TERMS
        )

        summary = (
            lines[0][:500]
            if lines
            else raw[:500]
        )

        return Requirement(
            raw_text=raw,
            summary=summary,
            goals=tuple(
                dict.fromkeys(goals)
            ),
            constraints=tuple(
                dict.fromkeys(constraints)
            ),
            acceptance_criteria=tuple(
                dict.fromkeys(criteria)
            ),
            requested_files=tuple(
                dict.fromkeys(requested_files)
            ),
            risk_flags=tuple(
                risk_flags
            ),
            requires_approval=requires_approval,
            metadata={
                "parser": "deterministic-v1"
            },
        )