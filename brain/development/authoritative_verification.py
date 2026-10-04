"""Authoritative verification engine for ARIA.

This adapter connects the new EngineeringSession contracts to ARIA's
existing intelligent verification implementation.

The existing verifier remains responsible for detailed verification
logic. This layer translates its result into the authoritative
verification contract and prevents verification from becoming another
independent source of lifecycle state.
"""

from __future__ import annotations

from typing import Any, Mapping

from .contracts.engineering_verification import (
    VerificationAction,
    VerificationDecision,
    VerificationDimension,
    VerificationFinding,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)


class AuthoritativeVerificationEngine:
    """Adapter around the existing intelligent verification layer."""

    VERSION = "PHASE1-AUTHORITATIVE-VERIFICATION-20261004"

    def __init__(
        self,
        verifier: Any | None = None,
    ) -> None:
        self.verifier = verifier

    async def verify(
        self,
        request: VerificationRequest,
        *,
        implementation_result: Any | None = None,
    ) -> VerificationResult:
        """Verify one engineering task."""

        if not isinstance(
            request,
            VerificationRequest,
        ):
            raise TypeError(
                "request must be a VerificationRequest."
            )

        try:
            if self.verifier is None:
                return self._build_no_verifier_result(
                    request
                )

            raw_result = await self._invoke_verifier(
                request,
                implementation_result,
            )

            return self._normalize_result(
                request,
                raw_result,
            )

        except Exception as exc:
            return self._build_error_result(
                request,
                exc,
            )

    async def _invoke_verifier(
        self,
        request: VerificationRequest,
        implementation_result: Any | None,
    ) -> Any:
        """Invoke whichever verification interface is available."""

        verifier = self.verifier

        method = getattr(
            verifier,
            "verify",
            None,
        )

        if method is None:
            method = getattr(
                verifier,
                "evaluate",
                None,
            )

        if method is None:
            method = getattr(
                verifier,
                "validate",
                None,
            )

        if method is None:
            raise AttributeError(
                "Verification service does not expose "
                "verify(), evaluate(), or validate()."
            )

        try:
            result = method(
                request,
                implementation_result=implementation_result,
            )
        except TypeError:
            try:
                result = method(
                    request,
                )
            except TypeError:
                result = method(
                    requirement=request.requirement,
                    acceptance_criteria=(
                        request.acceptance_criteria
                    ),
                )

        if hasattr(
            result,
            "__await__",
        ):
            return await result

        return result

    def _normalize_result(
        self,
        request: VerificationRequest,
        raw_result: Any,
    ) -> VerificationResult:
        """Normalize a legacy verification result."""

        if isinstance(
            raw_result,
            VerificationResult,
        ):
            return raw_result

        success = self._read_bool(
            raw_result,
            "success",
        )

        status_raw = self._read_value(
            raw_result,
            "status",
        )

        status = self._status_from_values(
            success,
            status_raw,
        )

        action = self._action_for_status(
            status
        )

        message = str(
            self._read_value(
                raw_result,
                "message",
            )
            or self._read_value(
                raw_result,
                "summary",
            )
            or (
                "Verification completed."
                if status
                is VerificationStatus.PASSED
                else "Verification did not prove the requirement."
            )
        )

        findings = self._extract_findings(
            request,
            raw_result,
            status,
            message,
        )

        failed_requirements = tuple(
            item.requirement_id
            for item in findings
            if item.status
            is VerificationStatus.FAILED
        )

        passed_requirements = tuple(
            item.requirement_id
            for item in findings
            if item.status
            is VerificationStatus.PASSED
        )

        missing_evidence = self._extract_strings(
            raw_result,
            "missing_evidence",
        )

        confidence = self._confidence(
            raw_result,
            status,
        )

        decision = VerificationDecision(
            status=status,
            action=action,
            confidence=confidence,
            findings=findings,
            missing_evidence=missing_evidence,
            failed_requirements=(
                failed_requirements
            ),
            passed_requirements=(
                passed_requirements
            ),
            next_steps=self._next_steps(
                status
            ),
            metadata={
                "adapter_version": self.VERSION,
                "raw_result_type": type(
                    raw_result
                ).__name__,
            },
        )

        return VerificationResult(
            session_id=request.session_id,
            task_id=request.task_id,
            decision=decision,
            evidence=findings,
            metadata={
                "adapter_version": self.VERSION,
            },
        )

    def _build_no_verifier_result(
        self,
        request: VerificationRequest,
    ) -> VerificationResult:
        """Never claim success when no verifier is available."""

        finding = VerificationFinding(
            requirement_id=(
                request.task_id
            ),
            dimension=(
                VerificationDimension.ACCEPTANCE
            ),
            status=(
                VerificationStatus.BLOCKED
            ),
            message=(
                "No verification service is attached. "
                "The requirement cannot be accepted without evidence."
            ),
            metadata={
                "adapter_version": self.VERSION,
            },
        )

        decision = VerificationDecision(
            status=VerificationStatus.BLOCKED,
            action=VerificationAction.BLOCK,
            confidence=0.0,
            findings=(
                finding,
            ),
            missing_evidence=(
                "verification_service",
            ),
            failed_requirements=(),
            passed_requirements=(),
            next_steps=(
                "attach_verification_service",
            ),
            metadata={
                "adapter_version": self.VERSION,
            },
        )

        return VerificationResult(
            session_id=request.session_id,
            task_id=request.task_id,
            decision=decision,
            evidence=(
                finding,
            ),
            metadata={
                "adapter_version": self.VERSION,
            },
        )

    def _build_error_result(
        self,
        request: VerificationRequest,
        exc: Exception,
    ) -> VerificationResult:
        """Convert verifier errors into diagnostic evidence."""

        message = (
            f"{type(exc).__name__}: {exc}"
        )

        finding = VerificationFinding(
            requirement_id=request.task_id,
            dimension=VerificationDimension.ACCEPTANCE,
            status=VerificationStatus.INCONCLUSIVE,
            message=message,
            metadata={
                "exception_type": type(
                    exc
                ).__name__,
                "adapter_version": self.VERSION,
            },
        )

        decision = VerificationDecision(
            status=VerificationStatus.INCONCLUSIVE,
            action=VerificationAction.DIAGNOSE,
            confidence=0.0,
            findings=(
                finding,
            ),
            missing_evidence=(
                "verification_execution_evidence",
            ),
            failed_requirements=(),
            passed_requirements=(),
            next_steps=(
                "diagnose_verification_failure",
            ),
            metadata={
                "adapter_version": self.VERSION,
            },
        )

        return VerificationResult(
            session_id=request.session_id,
            task_id=request.task_id,
            decision=decision,
            evidence=(
                finding,
            ),
            metadata={
                "adapter_version": self.VERSION,
            },
        )

    @staticmethod
    def _status_from_values(
        success: bool | None,
        raw_status: Any,
    ) -> VerificationStatus:
        if success is True:
            return VerificationStatus.PASSED

        if success is False:
            return VerificationStatus.FAILED

        if isinstance(
            raw_status,
            str,
        ):
            value = raw_status.lower().strip()

            if value in {
                "passed",
                "pass",
                "success",
                "accepted",
            }:
                return VerificationStatus.PASSED

            if value in {
                "failed",
                "failure",
                "error",
            }:
                return VerificationStatus.FAILED

            if value in {
                "blocked",
            }:
                return VerificationStatus.BLOCKED

            if value in {
                "inconclusive",
                "unknown",
            }:
                return VerificationStatus.INCONCLUSIVE

            if value in {
                "running",
                "in_progress",
            }:
                return VerificationStatus.IN_PROGRESS

        return VerificationStatus.INCONCLUSIVE

    @staticmethod
    def _action_for_status(
        status: VerificationStatus,
    ) -> VerificationAction:
        if status is VerificationStatus.PASSED:
            return VerificationAction.ACCEPT

        if status is VerificationStatus.FAILED:
            return VerificationAction.DIAGNOSE

        if status is VerificationStatus.BLOCKED:
            return VerificationAction.BLOCK

        if status is VerificationStatus.IN_PROGRESS:
            return VerificationAction.TEST

        return VerificationAction.REASSESS

    @staticmethod
    def _next_steps(
        status: VerificationStatus,
    ) -> tuple[str, ...]:
        if status is VerificationStatus.PASSED:
            return (
                "record_verification_evidence",
                "continue_to_acceptance",
            )

        if status is VerificationStatus.FAILED:
            return (
                "preserve_failure_evidence",
                "diagnose_root_cause",
                "repair_if_recoverable",
                "retest",
            )

        if status is VerificationStatus.BLOCKED:
            return (
                "resolve_verification_blocker",
                "reassess",
            )

        return (
            "gather_more_evidence",
            "reassess_verification",
        )

    @staticmethod
    def _read_value(
        value: Any,
        name: str,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            Mapping,
        ):
            return value.get(
                name
            )

        return getattr(
            value,
            name,
            None,
        )

    @classmethod
    def _read_bool(
        cls,
        value: Any,
        name: str,
    ) -> bool | None:
        result = cls._read_value(
            value,
            name,
        )

        if isinstance(
            result,
            bool,
        ):
            return result

        return None

    @classmethod
    def _confidence(
        cls,
        value: Any,
        status: VerificationStatus,
    ) -> float:
        raw = cls._read_value(
            value,
            "confidence",
        )

        try:
            confidence = float(
                raw
            )
        except (
            TypeError,
            ValueError,
        ):
            confidence = (
                1.0
                if status
                is VerificationStatus.PASSED
                else 0.0
            )

        return max(
            0.0,
            min(
                1.0,
                confidence,
            ),
        )

    @classmethod
    def _extract_strings(
        cls,
        value: Any,
        name: str,
    ) -> tuple[str, ...]:
        raw = cls._read_value(
            value,
            name,
        )

        if raw is None:
            return ()

        if isinstance(
            raw,
            str,
        ):
            return (
                raw,
            )

        if isinstance(
            raw,
            (list, tuple, set),
        ):
            return tuple(
                str(item)
                for item in raw
                if str(item).strip()
            )

        return (
            str(raw),
        )

    @classmethod
    def _extract_findings(
        cls,
        request: VerificationRequest,
        raw_result: Any,
        status: VerificationStatus,
        fallback_message: str,
    ) -> tuple[
        VerificationFinding,
        ...
    ]:
        raw_findings = cls._read_value(
            raw_result,
            "findings",
        )

        if raw_findings is None:
            raw_findings = cls._read_value(
                raw_result,
                "results",
            )

        findings: list[
            VerificationFinding
        ] = []

        if isinstance(
            raw_findings,
            Mapping,
        ):
            raw_findings = [
                raw_findings,
            ]

        if isinstance(
            raw_findings,
            (list, tuple),
        ):
            for index, item in enumerate(
                raw_findings
            ):
                if isinstance(
                    item,
                    VerificationFinding,
                ):
                    findings.append(
                        item
                    )
                    continue

                if not isinstance(
                    item,
                    Mapping,
                ):
                    continue

                dimension = cls._dimension(
                    item.get(
                        "dimension"
                    )
                )

                item_status = cls._status_from_values(
                    item.get(
                        "success"
                    ),
                    item.get(
                        "status"
                    ),
                )

                findings.append(
                    VerificationFinding(
                        requirement_id=str(
                            item.get(
                                "requirement_id",
                                f"{request.task_id}:{index}",
                            )
                        ),
                        dimension=dimension,
                        status=item_status,
                        message=str(
                            item.get(
                                "message",
                                fallback_message,
                            )
                        ),
                        evidence_ids=cls._tuple(
                            item.get(
                                "evidence_ids"
                            )
                        ),
                        command=(
                            str(
                                item.get(
                                    "command"
                                )
                            )
                            if item.get(
                                "command"
                            )
                            is not None
                            else None
                        ),
                        exit_code=cls._int(
                            item.get(
                                "exit_code"
                            )
                        ),
                        stdout=str(
                            item.get(
                                "stdout",
                                "",
                            )
                        ),
                        stderr=str(
                            item.get(
                                "stderr",
                                "",
                            )
                        ),
                        duration_seconds=cls._float(
                            item.get(
                                "duration_seconds"
                            )
                        ),
                        affected_paths=cls._tuple(
                            item.get(
                                "affected_paths"
                            )
                        ),
                        metadata=dict(
                            item.get(
                                "metadata",
                                {},
                            )
                        ),
                    )
                )

        if findings:
            return tuple(
                findings
            )

        return (
            VerificationFinding(
                requirement_id=request.task_id,
                dimension=VerificationDimension.ACCEPTANCE,
                status=status,
                message=fallback_message,
                affected_paths=(
                    request.changed_paths
                ),
            ),
        )

    @staticmethod
    def _dimension(
        value: Any,
    ) -> VerificationDimension:
        if isinstance(
            value,
            VerificationDimension,
        ):
            return value

        try:
            return VerificationDimension(
                str(
                    value
                )
            )
        except ValueError:
            return VerificationDimension.ACCEPTANCE

    @staticmethod
    def _tuple(
        value: Any,
    ) -> tuple[str, ...]:
        if value is None:
            return ()

        if isinstance(
            value,
            str,
        ):
            return (
                value,
            )

        if isinstance(
            value,
            (list, tuple, set),
        ):
            return tuple(
                str(item)
                for item in value
                if str(item).strip()
            )

        return ()

    @staticmethod
    def _int(
        value: Any,
    ) -> int | None:
        try:
            return int(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _float(
        value: Any,
    ) -> float | None:
        try:
            return float(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return None


__all__ = [
    "AuthoritativeVerificationEngine",
]