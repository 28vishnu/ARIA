"""
ARIA Telegram Development Interface.

Provides a Master-only entry point for Phase 1 self-development.

The interface accepts both typed text and already-transcribed voice text.
It never performs deployment or GitHub push.

DevelopmentController and DevelopmentAgent remain responsible for:
- isolated workspaces
- code generation
- guarded file changes
- validation
- testing
- bounded repair

This interface is intentionally a presentation/orchestration layer.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("aria")


class TelegramDevelopmentInterface:
    """Master-only Telegram interface for ARIA self-development."""

    def __init__(self, development_controller: Any) -> None:
        self.development_controller = development_controller

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    @staticmethod
    def _authorized(user_id: Any) -> bool:
        allowed = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()

        return (
            bool(allowed)
            and str(user_id).strip() == allowed
        )

    # ------------------------------------------------------------------
    # Command parsing
    # ------------------------------------------------------------------

    @staticmethod
    def extract_requirement(text: str) -> str | None:
        """
        Extract the requirement from supported Master commands.

        Examples:
            /master develop build X
            master develop build X
            master, develop build X
        """

        if not isinstance(text, str):
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
            if lower.startswith(prefix):
                requirement = value[len(prefix):].lstrip(
                    " :,-\t\r\n"
                )

                return requirement.strip() or None

        return None

    # ------------------------------------------------------------------
    # Main handler
    # ------------------------------------------------------------------

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
                Development command was handled.
        """

        requirement = self.extract_requirement(text)

        if requirement is None:
            return None

        if not self._authorized(user_id):
            logger.warning(
                "[Phase1][TelegramDevelopment] Unauthorized "
                "development request | user_id=%s",
                user_id,
            )

            return {
                "handled": True,
                "success": False,
                "text": (
                    "I can only accept self-development commands "
                    "from the authorized Master account."
                ),
            }

        logger.info(
            "[Phase1][TelegramDevelopment] Starting Master "
            "development job | requirement=%r",
            requirement,
        )

        try:
            job = await self.development_controller.execute(
                requirement
            )

            # ----------------------------------------------------------
            # Safely extract the job report.
            # ----------------------------------------------------------

            report = None

            if getattr(job, "report", None) is not None:
                try:
                    report = job.report.to_dict()
                except Exception:
                    logger.exception(
                        "[Phase1][TelegramDevelopment] "
                        "Could not serialize development report."
                    )

            metadata = getattr(job, "metadata", {})

            if not isinstance(metadata, dict):
                metadata = {}

            status = str(
                getattr(job, "status", "unknown")
            )

            job_id = str(
                getattr(job, "job_id", "unknown")
            )

            # ----------------------------------------------------------
            # Log the actual development outcome.
            #
            # Do NOT log generated source code.
            # Do NOT log secrets.
            # Do NOT log the entire repository context.
            # ----------------------------------------------------------

            self._log_job_summary(
                job_id=job_id,
                status=status,
                report=report,
                metadata=metadata,
            )

            # ----------------------------------------------------------
            # Format Telegram response.
            # ----------------------------------------------------------

            if status == "completed" and report:
                text_out = self._format_success(
                    job_id,
                    report,
                )
            else:
                text_out = self._format_failure(
                    job_id,
                    report,
                    metadata,
                    status=status,
                )

            # ----------------------------------------------------------
            # Return normalized result.
            # ----------------------------------------------------------

            try:
                job_dict = job.to_dict()
            except Exception:
                job_dict = {
                    "job_id": job_id,
                    "status": status,
                    "metadata": metadata,
                }

            return {
                "handled": True,
                "success": status == "completed",
                "job": job_dict,
                "text": text_out,
            }

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
                    "Development job could not start:\n"
                    f"{exc}"
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
                    "The development job failed safely before "
                    "deployment.\n"
                    f"Reason: {exc}"
                ),
            }

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @staticmethod
    def _log_job_summary(
        *,
        job_id: str,
        status: str,
        report: dict[str, Any] | None,
        metadata: dict[str, Any],
    ) -> None:
        """
        Log a bounded, human-readable development summary.

        This intentionally avoids dumping source code, repository
        contents, credentials, or large model responses.
        """

        logger.info(
            "[Phase1][TelegramDevelopment] Job finished | "
            "job_id=%s | status=%s",
            job_id,
            status,
        )

        if not report:
            logger.warning(
                "[Phase1][TelegramDevelopment] "
                "No DevelopmentReport was returned | job_id=%s "
                "| metadata_keys=%s",
                job_id,
                sorted(str(key) for key in metadata.keys()),
            )

            error = metadata.get("error")

            if error:
                logger.error(
                    "[Phase1][TelegramDevelopment] "
                    "Controller metadata error | job_id=%s | error=%s",
                    job_id,
                    error,
                )

            return

        # Generation ---------------------------------------------------

        generation = report.get("generation")

        if isinstance(generation, dict):
            changes = generation.get("changes") or []

            change_paths: list[str] = []

            if isinstance(changes, list):
                for change in changes[:30]:
                    if isinstance(change, dict):
                        path = change.get("path")

                        if path:
                            change_paths.append(str(path))

            logger.info(
                "[Phase1][TelegramDevelopment] Generation | "
                "job_id=%s | success=%s | changes=%s | paths=%s",
                job_id,
                generation.get("success"),
                len(changes) if isinstance(changes, list) else 0,
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
                    generation_error,
                )

        # Validation --------------------------------------------------

        validation = report.get("validation")

        if isinstance(validation, dict):
            logger.info(
                "[Phase1][TelegramDevelopment] Validation | "
                "job_id=%s | success=%s",
                job_id,
                validation.get("success"),
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
                    validation_error,
                )

        # Tests --------------------------------------------------------

        tests = report.get("tests")

        if isinstance(tests, dict):
            logger.info(
                "[Phase1][TelegramDevelopment] Tests | "
                "job_id=%s | success=%s",
                job_id,
                tests.get("success"),
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
                    test_error,
                )

        # Failures -----------------------------------------------------

        failures = report.get("failures") or []

        if failures:
            bounded_failures = [
                str(item)[:2000]
                for item in failures[-5:]
            ]

            logger.error(
                "[Phase1][TelegramDevelopment] "
                "Development failures | job_id=%s | failures=%s",
                job_id,
                bounded_failures,
            )

        # Repair -------------------------------------------------------

        repair = (
            report.get("repair")
            or report.get("repairs")
        )

        if isinstance(repair, dict):
            logger.info(
                "[Phase1][TelegramDevelopment] Repair | "
                "job_id=%s | summary=%s",
                job_id,
                TelegramDevelopmentInterface._safe_summary(
                    repair
                ),
            )

        # Metadata error ----------------------------------------------

        metadata_error = metadata.get("error")

        if metadata_error:
            logger.error(
                "[Phase1][TelegramDevelopment] "
                "Job metadata error | job_id=%s | error=%s",
                job_id,
                metadata_error,
            )

    # ------------------------------------------------------------------
    # Success response
    # ------------------------------------------------------------------

    @staticmethod
    def _format_success(
        job_id: str,
        report: dict[str, Any],
    ) -> str:
        generation = report.get("generation") or {}
        validation = report.get("validation") or {}
        tests = report.get("tests") or {}

        changes = generation.get("changes") or []

        change_count = (
            len(changes)
            if isinstance(changes, list)
            else 0
        )

        validation_ok = validation.get("success")
        tests_ok = tests.get("success")

        return (
            "🛠️ Development job completed.\n\n"
            f"Job: {job_id}\n"
            f"Generated changes: {change_count}\n"
            f"Validation: "
            f"{'PASS' if validation_ok else 'FAIL'}\n"
            f"Tests: "
            f"{'PASS' if tests_ok else 'FAIL'}\n\n"
            "No production deployment or GitHub push was performed."
        )

    # ------------------------------------------------------------------
    # Failure response
    # ------------------------------------------------------------------

    @staticmethod
    def _format_failure(
        job_id: str,
        report: dict[str, Any] | None,
        metadata: dict[str, Any],
        *,
        status: str,
    ) -> str:
        """
        Produce a useful but bounded Telegram failure message.
        """

        reasons: list[str] = []

        # Controller metadata ----------------------------------------

        metadata_error = metadata.get("error")

        if metadata_error:
            reasons.append(
                f"Controller: {metadata_error}"
            )

        # Report failures ---------------------------------------------

        if isinstance(report, dict):
            failures = report.get("failures") or []

            if isinstance(failures, list):
                for failure in failures[-3:]:
                    if failure:
                        reasons.append(
                            f"Failure: {failure}"
                        )

            generation = report.get("generation")

            if isinstance(generation, dict):
                generation_error = (
                    generation.get("error")
                    or generation.get("reason")
                    or generation.get("message")
                )

                if generation_error:
                    reasons.append(
                        f"Generation: {generation_error}"
                    )

            validation = report.get("validation")

            if isinstance(validation, dict):
                validation_error = (
                    validation.get("error")
                    or validation.get("reason")
                    or validation.get("message")
                )

                if validation_error:
                    reasons.append(
                        f"Validation: {validation_error}"
                    )

            tests = report.get("tests")

            if isinstance(tests, dict):
                test_error = (
                    tests.get("error")
                    or tests.get("reason")
                    or tests.get("message")
                )

                if test_error:
                    reasons.append(
                        f"Tests: {test_error}"
                    )

        # Deduplicate while preserving order -------------------------

        unique_reasons: list[str] = []

        for reason in reasons:
            clean = str(reason).strip()

            if not clean:
                continue

            if clean not in unique_reasons:
                unique_reasons.append(clean)

        if unique_reasons:
            reason_text = "\n".join(
                unique_reasons[:4]
            )

            # Telegram message safety/brevity.
            reason_text = reason_text[:3500]

        else:
            reason_text = (
                "The development report did not contain "
                "a specific failure reason. Check the Render "
                "logs for the Phase1 TelegramDevelopment "
                "diagnostic entries."
            )

        return (
            "🛠️ Development job finished with failure.\n\n"
            f"Job: {job_id}\n"
            f"Status: {status}\n\n"
            f"{reason_text}\n\n"
            "No production deployment or GitHub push was performed."
        )

    # ------------------------------------------------------------------
    # Safe summary helper
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_summary(value: Any) -> str:
        """
        Convert structured diagnostic data to a bounded summary.

        This is intentionally not a raw dump.
        """

        try:
            if isinstance(value, dict):
                allowed_keys = (
                    "success",
                    "attempts",
                    "max_attempts",
                    "repaired",
                    "failure_count",
                    "status",
                    "error",
                    "reason",
                )

                compact = {
                    key: value.get(key)
                    for key in allowed_keys
                    if key in value
                }

                return json.dumps(
                    compact,
                    ensure_ascii=False,
                    default=str,
                )[:2000]

            if isinstance(value, list):
                return json.dumps(
                    value[-5:],
                    ensure_ascii=False,
                    default=str,
                )[:2000]

            return str(value)[:2000]

        except Exception:
            return "<diagnostic summary unavailable>"


__all__ = ["TelegramDevelopmentInterface"]