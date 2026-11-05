from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .sandbox import (
    CommandResult,
    DevelopmentSandbox,
)


@dataclass(frozen=True)
class TestResult:
    command: tuple[str, ...]
    passed: bool
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool

    def to_dict(self) -> dict:
        return {
            "command": list(
                self.command
            ),
            "passed": self.passed,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
        }


@dataclass(frozen=True)
class TestSuiteResult:
    passed: bool
    results: tuple[
        TestResult,
        ...
    ] = field(
        default_factory=tuple
    )

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "results": [
                result.to_dict()
                for result in self.results
            ],
        }


class DevelopmentTestRunner:
    """
    Runs bounded development tests through
    DevelopmentSandbox.

    Only supported test commands are constructed here.
    Arbitrary shell commands are not accepted.
    """

    def __init__(
        self,
        sandbox: DevelopmentSandbox,
        *,
        timeout_seconds: float | None = None,
    ) -> None:

        self.sandbox = sandbox
        self.timeout_seconds = (
            timeout_seconds
        )

    @staticmethod
    def _convert(
        result: CommandResult,
    ) -> TestResult:

        return TestResult(
            command=result.command,
            passed=result.ok,
            return_code=result.return_code,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=result.timed_out,
        )

    async def compile_file(
        self,
        path: str | Path,
    ) -> TestResult:

        result = (
            await self.sandbox.compile_python(
                path
            )
        )

        return self._convert(
            result
        )

    async def run_pytest(
        self,
        *,
        test_path: str = "tests",
        extra_args: Sequence[str] = (),
    ) -> TestResult:

        normalized = (
            str(test_path)
            .replace("\\", "/")
            .lstrip("./")
        )

        if (
            normalized.startswith("../")
            or normalized == ".."
        ):
            raise ValueError(
                "test_path must remain "
                "inside the workspace."
            )

        if any(
            token in normalized
            for token in (
                ";",
                "&&",
                "||",
                "|",
                "`",
                "$(",
            )
        ):
            raise ValueError(
                "Unsafe test path."
            )

        args = (
            "-m",
            "pytest",
            normalized,
            "--disable-warnings",
            "-q",
            *tuple(
                str(arg)
                for arg in extra_args
            ),
        )

        result = await self.sandbox.python(
            args
        )

        return self._convert(
            result
        )

    async def run_targeted_tests(
        self,
        test_paths: Sequence[str],
    ) -> TestSuiteResult:

        if not test_paths:
            raise ValueError(
                "At least one test path "
                "is required."
            )

        results: list[TestResult] = []

        for path in test_paths:

            result = (
                await self.run_pytest(
                    test_path=path
                )
            )

            results.append(
                result
            )

            if not result.passed:
                break

        return TestSuiteResult(
            passed=all(
                result.passed
                for result in results
            ),
            results=tuple(
                results
            ),
        )

    async def run_regression_suite(
        self,
    ) -> TestSuiteResult:

        result = await self.run_pytest(
            test_path="tests"
        )

        return TestSuiteResult(
            passed=result.passed,
            results=(result,),
        )