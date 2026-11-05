from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .failure_analyzer import (
    FailureAnalysis,
)
from .test_runner import TestResult


@dataclass(frozen=True)
class RepairAttempt:
    attempt: int
    analysis: FailureAnalysis
    action: str
    applied: bool

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "analysis": (
                self.analysis.to_dict()
            ),
            "action": self.action,
            "applied": self.applied,
        }


@dataclass(frozen=True)
class RepairResult:
    success: bool
    attempts: int
    max_attempts: int
    stopped_reason: str
    history: tuple[
        RepairAttempt,
        ...
    ] = field(
        default_factory=tuple
    )

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "stopped_reason": (
                self.stopped_reason
            ),
            "history": [
                item.to_dict()
                for item in self.history
            ],
        }


RepairCallback = Callable[
    [FailureAnalysis, int],
    Awaitable[bool],
]


class RepairEngine:
    """
    Controls bounded automatic repair attempts.

    It deliberately does not generate code itself.

    A future DevelopmentAgent supplies the repair
    callback.

    Every repair attempt is followed by another
    test run.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
    ) -> None:

        if max_attempts < 1:
            raise ValueError(
                "max_attempts must be at least 1."
            )

        self.max_attempts = int(
            max_attempts
        )

    async def repair(
        self,
        initial_result: TestResult,
        *,
        analyze: Callable[
            [TestResult],
            FailureAnalysis,
        ],
        apply_repair: RepairCallback,
        rerun: Callable[
            [],
            Awaitable[TestResult],
        ],
    ) -> RepairResult:

        if initial_result.passed:

            return RepairResult(
                success=True,
                attempts=0,
                max_attempts=self.max_attempts,
                stopped_reason=(
                    "initial_tests_passed"
                ),
            )

        history: list[
            RepairAttempt
        ] = []

        current_result = (
            initial_result
        )

        for attempt in range(
            1,
            self.max_attempts + 1,
        ):

            analysis = analyze(
                current_result
            )

            if not analysis.repairable:

                return RepairResult(
                    success=False,
                    attempts=attempt - 1,
                    max_attempts=self.max_attempts,
                    stopped_reason=(
                        "failure_not_"
                        "automatically_repairable"
                    ),
                    history=tuple(
                        history
                    ),
                )

            applied = await apply_repair(
                analysis,
                attempt,
            )

            history.append(
                RepairAttempt(
                    attempt=attempt,
                    analysis=analysis,
                    action=(
                        "repair_requested"
                        if applied
                        else "repair_not_applied"
                    ),
                    applied=applied,
                )
            )

            if not applied:

                return RepairResult(
                    success=False,
                    attempts=attempt,
                    max_attempts=self.max_attempts,
                    stopped_reason=(
                        "repair_not_applied"
                    ),
                    history=tuple(
                        history
                    ),
                )

            current_result = await rerun()

            if current_result.passed:

                return RepairResult(
                    success=True,
                    attempts=attempt,
                    max_attempts=self.max_attempts,
                    stopped_reason=(
                        "tests_passed_after_repair"
                    ),
                    history=tuple(
                        history
                    ),
                )

        return RepairResult(
            success=False,
            attempts=self.max_attempts,
            max_attempts=self.max_attempts,
            stopped_reason=(
                "maximum_repair_attempts_reached"
            ),
            history=tuple(
                history
            ),
        )