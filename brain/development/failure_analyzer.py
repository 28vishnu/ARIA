from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .test_runner import TestResult


@dataclass(frozen=True)
class FailureFinding:
    category: str
    message: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "message": self.message,
            "evidence": list(
                self.evidence
            ),
        }


@dataclass(frozen=True)
class FailureAnalysis:
    failed: bool
    summary: str
    findings: tuple[
        FailureFinding,
        ...
    ] = field(
        default_factory=tuple
    )
    repairable: bool = False

    def to_dict(self) -> dict:
        return {
            "failed": self.failed,
            "summary": self.summary,
            "findings": [
                finding.to_dict()
                for finding in self.findings
            ],
            "repairable": self.repairable,
        }


class FailureAnalyzer:
    """
    Classifies test failures without executing
    or modifying source code.
    """

    PATTERNS = (
        (
            "syntax_error",
            re.compile(
                r"(SyntaxError|IndentationError|TabError)",
                re.I,
            ),
            "Python syntax or indentation failure.",
        ),
        (
            "import_error",
            re.compile(
                r"(ModuleNotFoundError|ImportError)",
                re.I,
            ),
            "Python import/dependency failure.",
        ),
        (
            "assertion_failure",
            re.compile(
                r"(AssertionError|assert .*failed|FAILED)",
                re.I,
            ),
            "A test assertion failed.",
        ),
        (
            "type_error",
            re.compile(
                r"\bTypeError\b",
                re.I,
            ),
            "A value or call has an incompatible type.",
        ),
        (
            "name_error",
            re.compile(
                r"\bNameError\b",
                re.I,
            ),
            "A referenced name is not defined.",
        ),
        (
            "attribute_error",
            re.compile(
                r"\bAttributeError\b",
                re.I,
            ),
            "An expected attribute or method is missing.",
        ),
        (
            "timeout",
            re.compile(
                r"(timed out|timeout)",
                re.I,
            ),
            "Execution exceeded the configured time limit.",
        ),
        (
            "permission",
            re.compile(
                r"(PermissionError|permission denied)",
                re.I,
            ),
            "A filesystem or process permission was denied.",
        ),
    )

    def analyze(
        self,
        result: TestResult,
    ) -> FailureAnalysis:

        if result.passed:
            return FailureAnalysis(
                failed=False,
                summary="Test execution passed.",
                repairable=False,
            )

        combined = (
            f"{result.stdout}\n"
            f"{result.stderr}"
        )

        findings: list[
            FailureFinding
        ] = []

        for (
            category,
            pattern,
            message,
        ) in self.PATTERNS:

            matches = pattern.findall(
                combined
            )

            if matches:

                evidence = self._evidence(
                    combined,
                    pattern,
                )

                findings.append(
                    FailureFinding(
                        category=category,
                        message=message,
                        evidence=evidence,
                    )
                )

        if not findings:

            findings.append(
                FailureFinding(
                    category="unknown",
                    message=(
                        "The failure did not "
                        "match a known "
                        "diagnostic pattern."
                    ),
                    evidence=tuple(
                        self._tail_lines(
                            combined
                        )
                    ),
                )
            )

        repairable_categories = {
            "syntax_error",
            "assertion_failure",
            "type_error",
            "name_error",
            "attribute_error",
        }

        repairable = any(
            finding.category
            in repairable_categories
            for finding in findings
        )

        if any(
            finding.category == "timeout"
            for finding in findings
        ):
            repairable = False

        return FailureAnalysis(
            failed=True,
            summary=self._summary(
                findings
            ),
            findings=tuple(
                findings
            ),
            repairable=repairable,
        )

    @staticmethod
    def _summary(
        findings: Iterable[
            FailureFinding
        ],
    ) -> str:

        categories = ", ".join(
            finding.category
            for finding in findings
        )

        return (
            "Detected failure categories: "
            f"{categories}."
        )

    @staticmethod
    def _tail_lines(
        text: str,
        limit: int = 12,
    ) -> list[str]:

        return [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ][-limit:]

    @staticmethod
    def _evidence(
        text: str,
        pattern: re.Pattern[str],
        limit: int = 5,
    ) -> tuple[str, ...]:

        lines = text.splitlines()
        matched: list[str] = []

        for index, line in enumerate(
            lines
        ):

            if pattern.search(line):

                start = max(
                    0,
                    index - 1,
                )

                end = min(
                    len(lines),
                    index + 2,
                )

                for candidate in lines[
                    start:end
                ]:

                    candidate = (
                        candidate.strip()
                    )

                    if (
                        candidate
                        and candidate
                        not in matched
                    ):
                        matched.append(
                            candidate
                        )

                if len(
                    matched
                ) >= limit:
                    break

        return tuple(
            matched[:limit]
        )