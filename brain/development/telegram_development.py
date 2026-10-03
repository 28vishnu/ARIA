"""
ARIA Telegram Development Interface.

Provides a Master-only entry point for Phase 1 self-development.

The interface accepts both typed text and already-transcribed voice text.

This module is intentionally a presentation/orchestration layer.
It does not directly:
- write files
- execute development commands
- deploy production
- push to GitHub
- perform rollback

DevelopmentController and DevelopmentAgent remain responsible for
the actual development lifecycle.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any


logger = logging.getLogger("aria")


class TelegramDevelopmentInterface:
    """
    Master-only Telegram interface for ARIA self-development.
    """

    def __init__(
        self,
        development_controller: Any,
    ) -> None:
        self.development_controller = (
            development_controller
        )

    # ============================================================
    # Authorization
    # ============================================================

    @staticmethod
    def _authorized(
        user_id: Any,
    ) -> bool:
        """
        Verify that the Telegram user is the configured Master.

        Authorization is fail-closed:
        if ALLOWED_TELEGRAM_USER_ID is missing or empty,
        development commands are rejected.
        """

        allowed = os.getenv(
            "ALLOWED_TELEGRAM_USER_ID",
            "",
        ).strip()

        if not allowed:
            return False

        return (
            str(user_id).strip()
            == allowed
        )

    # ============================================================
    # Command parsing
    # ============================================================

    @staticmethod
    def extract_requirement(
        text: str,
    ) -> str | None:
        """
        Extract a development requirement from supported
        Master command forms.

        Supported examples:

            /master develop build X

            /master  develop build X

            master develop build X

            master develop: build X

            master, develop build X
        """

        if not isinstance(
            text,
            str,
        ):
            return None

        value = text.strip()

        if not value:
            return None

        lower = value.lower()

        prefixes = (
            "/master develop",
            "/master  develop",
            "master develop:",
            "master develop",
            "master, develop",
        )

        for prefix in prefixes:

            if not lower.startswith(prefix):
                continue

            requirement = (
                value[
                    len(prefix):
                ].lstrip(
                    " :,-\t\r\n"
                )
            )

            requirement = requirement.strip()

            return (
                requirement
                if requirement
                else None
            )

        return None

    # ============================================================
    # Main handler
    # ============================================================

    async def handle(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> dict[str, Any] | None:
        """
        Handle a Master development request.

        Returns:

            None
                The message is not a development command.

            dict
                The development command was handled.
        """

        requirement = (
            self.extract_requirement(text)
        )

        if requirement is None:
            return None

        # --------------------------------------------------------
        # Master authorization
        # --------------------------------------------------------

        if not self._authorized(user_id):

            logger.warning(
                "[Phase1][TelegramDevelopment] "
                "Unauthorized development request | user_id=%s",
                user_id,
            )

            return {
                "handled": True,
                "success": False,
                "text": (
                    "I can only accept self-development "
                    "commands from the authorized Master account."
                ),
            }

        logger.info(
            "[Phase1][TelegramDevelopment] "
            "Starting Master development job | requirement=%r",
            requirement,
        )

        # --------------------------------------------------------
        # Execute development controller
        # --------------------------------------------------------

        try:

            job = (
                await self.development_controller.execute(
                    requirement
                )
            )

        except RuntimeError as exc:

            logger.warning(
                "[Phase1][TelegramDevelopment] "
                "Development job rejected: %s",
                exc,
            )

            return {
                "handled": True,
                "success": False,
                "text": (
                    "Development job could not start.\n\n"
                    f"Reason: {self._bounded_text(exc)}\n\n"
                    "No production deployment or GitHub push "
                    "was performed."
                ),
            }

        except Exception as exc:

            logger.exception(
                "[Phase1][TelegramDevelopment] "
                "Development job failed unexpectedly."
            )

            return {
                "handled": True,
                "success": False,
                "text": (
                    "The development job failed safely "
                    "before deployment.\n\n"
                    f"Reason: {self._bounded_text(exc)}\n\n"
                    "No production deployment or GitHub push "
                    "was performed."
                ),
            }

        # --------------------------------------------------------
        # Extract job information
        # --------------------------------------------------------

        job_id = str(
            getattr(
                job,
                "job_id",
                "unknown",
            )
        )

        status = str(
            getattr(
                job,
                "status",
                "unknown",
            )
        )

        report_object = getattr(
            job,
            "report",
            None,
        )

        metadata = getattr(
            job,
            "metadata",
            {},
        )

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {}

        # --------------------------------------------------------
        # Serialize report safely
        # --------------------------------------------------------

        report: dict[str, Any] | None = None

        if report_object is not None:

            try:

                serialized = (
                    report_object.to_dict()
                    if hasattr(
                        report_object,
                        "to_dict",
                    )
                    else report_object
                )

                if isinstance(
                    serialized,
                    dict,
                ):
                    report = serialized

            except Exception:

                logger.exception(
                    "[Phase1][TelegramDevelopment] "
                    "Could not serialize development report | "
                    "job_id=%s",
                    job_id,
                )

        # --------------------------------------------------------
        # Log bounded diagnostic information
        # --------------------------------------------------------

        self._log_job_summary(
            job_id=job_id,
            status=status,
            report=report,
            metadata=metadata,
        )

        # --------------------------------------------------------
        # Determine actual success
        #
        # Do not rely only on job.status.
        # DevelopmentReport.success is authoritative when
        # a report exists.
        # --------------------------------------------------------

        report_success = None

        if isinstance(
            report,
            dict,
        ):
            report_success = report.get(
                "success"
            )

        successful = (
            bool(report_success)
            if report_success is not None
            else status == "completed"
        )

        # --------------------------------------------------------
        # Format response
        # --------------------------------------------------------

        if successful:

            text_out = (
                self._format_success(
                    job_id=job_id,
                    status=status,
                    report=report,
                )
            )

        else:

            text_out = (
                self._format_failure(
                    job_id=job_id,
                    status=status,
                    report=report,
                    metadata=metadata,
                )
            )

        # --------------------------------------------------------
        # Serialize job safely
        # --------------------------------------------------------

        try:

            if hasattr(
                job,
                "to_dict",
            ):
                job_dict = job.to_dict()

            else:
                job_dict = {
                    "job_id": job_id,
                    "status": status,
                    "metadata": metadata,
                }

        except Exception:

            logger.exception(
                "[Phase1][TelegramDevelopment] "
                "Could not serialize development job | "
                "job_id=%s",
                job_id,
            )

            job_dict = {
                "job_id": job_id,
                "status": status,
                "metadata": metadata,
            }

        return {
            "handled": True,
            "success": successful,
            "job": job_dict,
            "text": text_out,
        }

    # ============================================================
    # Diagnostics
    # ============================================================

    @staticmethod
    def _log_job_summary(
        *,
        job_id: str,
        status: str,
        report: dict[str, Any] | None,
        metadata: dict[str, Any],
    ) -> None:
        """
        Log a bounded development summary.

        Never logs:
        - generated source code
        - repository contents
        - model prompts
        - secrets
        - credentials
        - full model responses
        """

        logger.info(
            "[Phase1][TelegramDevelopment] "
            "Job finished | job_id=%s | status=%s",
            job_id,
            status,
        )

        if not report:

            logger.warning(
                "[Phase1][TelegramDevelopment] "
                "No DevelopmentReport was returned | "
                "job_id=%s | metadata_keys=%s",
                job_id,
                sorted(
                    str(key)
                    for key in metadata.keys()
                ),
            )

            metadata_error = (
                metadata.get("error")
            )

            if metadata_error:

                logger.error(
                    "[Phase1][TelegramDevelopment] "
                    "Controller metadata error | "
                    "job_id=%s | error=%s",
                    job_id,
                    TelegramDevelopmentInterface._bounded_text(
                        metadata_error
                    ),
                )

            return

        # --------------------------------------------------------
        # Report status
        # --------------------------------------------------------

        logger.info(
            "[Phase1][TelegramDevelopment] "
            "Report | job_id=%s | success=%s | status=%s",
            job_id,
            report.get("success"),
            report.get("status"),
        )

        # --------------------------------------------------------
        # Generation
        # --------------------------------------------------------

        generation = report.get(
            "generation"
        )

        if isinstance(
            generation,
            dict,
        ):

            changes = (
                generation.get(
                    "changes"
                )
                or []
            )

            change_paths: list[str] = []

            if isinstance(
                changes,
                list,
            ):

                for change in changes[:30]:

                    if not isinstance(
                        change,
                        dict,
                    ):
                        continue

                    path = change.get(
                        "path"
                    )

                    if path:
                        change_paths.append(
                            str(path)
                        )

            logger.info(
                "[Phase1][TelegramDevelopment] "
                "Generation | job_id=%s | success=%s | "
                "changes=%s | paths=%s",
                job_id,
                generation.get(
                    "success"
                ),
                (
                    len(changes)
                    if isinstance(
                        changes,
                        list,
                    )
                    else 0
                ),
                change_paths,
            )

            generation_error = (
                generation.get("error")
                or generation.get("reason")
                or generation.get("message")
            )

            if generation_error:

                logger.error(
                    "[Phase1][TelegramDevelopment] "
                    "Generation error | job_id=%s | error=%s",
                    job_id,
                    TelegramDevelopmentInterface._bounded_text(
                        generation_error
                    ),
                )

        # --------------------------------------------------------
        # Validation
        #
        # DevelopmentValidator uses `valid`.
        # --------------------------------------------------------

        validation = report.get(
            "validation"
        )

        if isinstance(
            validation,
            dict,
        ):

            logger.info(
                "[Phase1][TelegramDevelopment] "
                "Validation | job_id=%s | valid=%s",
                job_id,
                validation.get(
                    "valid"
                ),
            )

            validation_error = (
                validation.get("error")
                or validation.get("reason")
                or validation.get("message")
            )

            if validation_error:

                logger.error(
                    "[Phase1][TelegramDevelopment] "
                    "Validation error | job_id=%s | error=%s",
                    job_id,
                    TelegramDevelopmentInterface._bounded_text(
                        validation_error
                    ),
                )

        # --------------------------------------------------------
        # Tests
        #
        # TestResult uses `passed`.
        # --------------------------------------------------------

        tests = report.get(
            "tests"
        )

        if isinstance(
            tests,
            dict,
        ):

            logger.info(
                "[Phase1][TelegramDevelopment] "
                "Tests | job_id=%s | passed=%s",
                job_id,
                tests.get(
                    "passed"
                ),
            )

            test_error = (
                tests.get("error")
                or tests.get("reason")
                or tests.get("message")
            )

            if test_error:

                logger.error(
                    "[Phase1][TelegramDevelopment] "
                    "Test error | job_id=%s | error=%s",
                    job_id,
                    TelegramDevelopmentInterface._bounded_text(
                        test_error
                    ),
                )

        # --------------------------------------------------------
        # Failure analysis
        #
        # DevelopmentReport uses a singular `failure`.
        # --------------------------------------------------------

        failure = report.get(
            "failure"
        )

        if isinstance(
            failure,
            dict,
        ):

            logger.error(
                "[Phase1][TelegramDevelopment] "
                "Failure analysis | job_id=%s | summary=%s",
                job_id,
                TelegramDevelopmentInterface._safe_summary(
                    failure
                ),
            )

        # --------------------------------------------------------
        # Report errors
        #
        # DevelopmentReport uses `errors`.
        # --------------------------------------------------------

        errors = report.get(
            "errors"
        ) or []

        if isinstance(
            errors,
            (list, tuple),
        ) and errors:

            bounded_errors = [
                TelegramDevelopmentInterface._bounded_text(
                    item,
                    limit=2000,
                )
                for item in errors[-5:]
            ]

            logger.error(
                "[Phase1][TelegramDevelopment] "
                "Development errors | job_id=%s | errors=%s",
                job_id,
                bounded_errors,
            )

        # --------------------------------------------------------
        # Repair
        # --------------------------------------------------------

        repair = report.get(
            "repair"
        )

        if isinstance(
            repair,
            dict,
        ):

            logger.info(
                "[Phase1][TelegramDevelopment] "
                "Repair | job_id=%s | summary=%s",
                job_id,
                TelegramDevelopmentInterface._safe_summary(
                    repair
                ),
            )

        # --------------------------------------------------------
        # Metadata error
        # --------------------------------------------------------

        metadata_error = (
            metadata.get("error")
        )

        if metadata_error:

            logger.error(
                "[Phase1][TelegramDevelopment] "
                "Job metadata error | job_id=%s | error=%s",
                job_id,
                TelegramDevelopmentInterface._bounded_text(
                    metadata_error
                ),
            )

    # ============================================================
    # Success response
    # ============================================================

    @staticmethod
    def _format_success(
        *,
        job_id: str,
        status: str,
        report: dict[str, Any] | None,
    ) -> str:
        """
        Format a successful development result.

        A successful development job means the DevelopmentAgent
        completed its currently implemented development stages.
        It does NOT imply production deployment.
        """

        if not isinstance(
            report,
            dict,
        ):
            return (
                "🛠️ Development job completed.\n\n"
                f"Job: {job_id}\n"
                f"Status: {status}\n\n"
                "No production deployment or GitHub push "
                "was performed."
            )

        generation = (
            report.get(
                "generation"
            )
            or {}
        )

        validation = (
            report.get(
                "validation"
            )
            or {}
        )

        tests = (
            report.get(
                "tests"
            )
            or {}
        )

        changes = (
            generation.get(
                "changes"
            )
            or []
        )

        change_count = (
            len(changes)
            if isinstance(
                changes,
                list,
            )
            else 0
        )

        validation_ok = validation.get(
            "valid"
        )

        tests_ok = tests.get(
            "passed"
        )

        validation_text = (
            "PASS"
            if validation_ok is True
            else (
                "NOT RUN"
                if validation_ok is None
                else "FAIL"
            )
        )

        tests_text = (
            "PASS"
            if tests_ok is True
            else (
                "NOT RUN"
                if tests_ok is None
                else "FAIL"
            )
        )

        report_status = str(
            report.get(
                "status",
                status,
            )
        )

        return (
            "🛠️ Development job completed.\n\n"
            f"Job: {job_id}\n"
            f"Status: {report_status}\n"
            f"Generated changes: {change_count}\n"
            f"Validation: {validation_text}\n"
            f"Tests: {tests_text}\n\n"
            "No production deployment or GitHub push "
            "was performed."
        )

    # ============================================================
    # Failure response
    # ============================================================

    @staticmethod
    def _format_failure(
        *,
        job_id: str,
        status: str,
        report: dict[str, Any] | None,
        metadata: dict[str, Any],
    ) -> str:
        """
        Produce a useful bounded Telegram failure message.

        This method reads the actual DevelopmentReport schema:

            errors
            failure
            generation.error
            validation.error
            tests.error
        """

        reasons: list[str] = []

        # --------------------------------------------------------
        # Controller metadata
        # --------------------------------------------------------

        metadata_error = (
            metadata.get("error")
        )

        if metadata_error:

            reasons.append(
                "Controller: "
                + TelegramDevelopmentInterface._bounded_text(
                    metadata_error
                )
            )

        # --------------------------------------------------------
        # Development report
        # --------------------------------------------------------

        if isinstance(
            report,
            dict,
        ):

            # ----------------------------------------------------
            # Primary report errors
            # ----------------------------------------------------

            report_errors = (
                report.get(
                    "errors"
                )
                or []
            )

            if isinstance(
                report_errors,
                (list, tuple),
            ):

                for error in report_errors[-5:]:

                    if error:

                        reasons.append(
                            "Development: "
                            + TelegramDevelopmentInterface._bounded_text(
                                error
                            )
                        )

            # ----------------------------------------------------
            # Failure analysis
            # ----------------------------------------------------

            failure = report.get(
                "failure"
            )

            if isinstance(
                failure,
                dict,
            ):

                failure_reason = (
                    failure.get(
                        "summary"
                    )
                    or failure.get(
                        "reason"
                    )
                    or failure.get(
                        "message"
                    )
                    or failure.get(
                        "error"
                    )
                )

                if failure_reason:

                    reasons.append(
                        "Failure analysis: "
                        + TelegramDevelopmentInterface._bounded_text(
                            failure_reason
                        )
                    )

            # ----------------------------------------------------
            # Generation
            # ----------------------------------------------------

            generation = report.get(
                "generation"
            )

            if isinstance(
                generation,
                dict,
            ):

                generation_error = (
                    generation.get(
                        "error"
                    )
                    or generation.get(
                        "reason"
                    )
                    or generation.get(
                        "message"
                    )
                )

                if generation_error:

                    reasons.append(
                        "Generation: "
                        + TelegramDevelopmentInterface._bounded_text(
                            generation_error
                        )
                    )

            # ----------------------------------------------------
            # Validation
            # ----------------------------------------------------

            validation = report.get(
                "validation"
            )

            if isinstance(
                validation,
                dict,
            ):

                validation_error = (
                    validation.get(
                        "error"
                    )
                    or validation.get(
                        "reason"
                    )
                    or validation.get(
                        "message"
                    )
                )

                if validation_error:

                    reasons.append(
                        "Validation: "
                        + TelegramDevelopmentInterface._bounded_text(
                            validation_error
                        )
                    )

                elif validation.get(
                    "valid"
                ) is False:

                    reasons.append(
                        "Validation: static validation failed."
                    )

            # ----------------------------------------------------
            # Tests
            # ----------------------------------------------------

            tests = report.get(
                "tests"
            )

            if isinstance(
                tests,
                dict,
            ):

                test_error = (
                    tests.get(
                        "error"
                    )
                    or tests.get(
                        "reason"
                    )
                    or tests.get(
                        "message"
                    )
                )

                if test_error:

                    reasons.append(
                        "Tests: "
                        + TelegramDevelopmentInterface._bounded_text(
                            test_error
                        )
                    )

                elif tests.get(
                    "passed"
                ) is False:

                    reasons.append(
                        "Tests: test execution failed."
                    )

            # ----------------------------------------------------
            # Report status
            # ----------------------------------------------------

            report_status = report.get(
                "status"
            )

            if (
                report_status
                and report_status != status
            ):

                reasons.append(
                    "Development status: "
                    + TelegramDevelopmentInterface._bounded_text(
                        report_status
                    )
                )

        # --------------------------------------------------------
        # Deduplicate while preserving order
        # --------------------------------------------------------

        unique_reasons: list[str] = []

        for reason in reasons:

            clean = str(
                reason
            ).strip()

            if not clean:
                continue

            if clean in unique_reasons:
                continue

            unique_reasons.append(
                clean
            )

        # --------------------------------------------------------
        # Final reason
        # --------------------------------------------------------

        if unique_reasons:

            reason_text = "\n".join(
                unique_reasons[:6]
            )

            reason_text = reason_text[
                :3500
            ]

        else:

            reason_text = (
                "The development report did not contain "
                "a specific failure reason."
            )

        return (
            "🛠️ Development job finished with failure.\n\n"
            f"Job: {job_id}\n"
            f"Status: {status}\n\n"
            f"{reason_text}\n\n"
            "No production deployment or GitHub push "
            "was performed."
        )

    # ============================================================
    # Safe diagnostic helpers
    # ============================================================

    @staticmethod
    def _safe_summary(
        value: Any,
    ) -> str:
        """
        Convert structured diagnostic data into a bounded
        summary without dumping arbitrary content.
        """

        try:

            if isinstance(
                value,
                dict,
            ):

                allowed_keys = (
                    "success",
                    "passed",
                    "valid",
                    "attempts",
                    "max_attempts",
                    "repaired",
                    "failure_count",
                    "status",
                    "error",
                    "reason",
                    "summary",
                    "repairable",
                )

                compact = {
                    key: value.get(
                        key
                    )
                    for key in allowed_keys
                    if key in value
                }

                return json.dumps(
                    compact,
                    ensure_ascii=False,
                    default=str,
                )[:2000]

            if isinstance(
                value,
                (list, tuple),
            ):

                return json.dumps(
                    list(value)[-5:],
                    ensure_ascii=False,
                    default=str,
                )[:2000]

            return str(
                value
            )[:2000]

        except Exception:

            return (
                "<diagnostic summary unavailable>"
            )

    @staticmethod
    def _bounded_text(
        value: Any,
        *,
        limit: int = 2000,
    ) -> str:
        """
        Convert arbitrary diagnostic data to bounded text.
        """

        try:

            text = str(
                value
            ).strip()

        except Exception:

            return "<unavailable>"

        if not text:
            return "<empty>"

        return text[
            :max(
                1,
                int(limit),
            )
        ]


__all__ = [
    "TelegramDevelopmentInterface",
]