"""
ARIA Telegram Development Interface.

Provides a Master-only entry point for Phase 1 self-development.
The interface accepts both typed text and already-transcribed voice text.

It never performs deployment or GitHub push. DevelopmentController and
DevelopmentAgent enforce workspace isolation and validation.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("aria")


class TelegramDevelopmentInterface:
    def __init__(self, development_controller: Any) -> None:
        self.development_controller = development_controller

    @staticmethod
    def _authorized(user_id: Any) -> bool:
        allowed = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()
        return bool(allowed) and str(user_id) == allowed

    @staticmethod
    def extract_requirement(text: str) -> str | None:
        if not isinstance(text, str):
            return None

        value = text.strip()
        if not value:
            return None

        lower = value.lower()

        prefixes = (
            "/master develop",
            "/master  develop",
            "master develop",
            "master, develop",
            "master develop:",
        )

        for prefix in prefixes:
            if lower.startswith(prefix):
                requirement = value[len(prefix):].lstrip(" :,-")
                return requirement.strip() or None

        return None

    async def handle(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> dict[str, Any] | None:
        requirement = self.extract_requirement(text)

        if requirement is None:
            return None

        if not self._authorized(user_id):
            logger.warning(
                "[Phase1][TelegramDevelopment] Unauthorized development request | user_id=%s",
                user_id,
            )
            return {
                "handled": True,
                "success": False,
                "text": "I can only accept self-development commands from the authorized Master account.",
            }

        logger.info(
            "[Phase1][TelegramDevelopment] Starting Master development job | requirement=%r",
            requirement,
        )

        try:
            job = await self.development_controller.execute(
                requirement
            )

            report = job.report.to_dict() if job.report else None

            if job.status == "completed" and report:
                text_out = self._format_success(job.job_id, report)
            else:
                text_out = self._format_failure(
                    job.job_id,
                    report,
                    job.metadata,
                )

            return {
                "handled": True,
                "success": job.status == "completed",
                "job": job.to_dict(),
                "text": text_out,
            }

        except RuntimeError as exc:
            logger.warning(
                "[Phase1][TelegramDevelopment] Development job rejected: %s",
                exc,
            )
            return {
                "handled": True,
                "success": False,
                "text": f"Development job could not start: {exc}",
            }

        except Exception as exc:
            logger.exception(
                "[Phase1][TelegramDevelopment] Development job failed."
            )
            return {
                "handled": True,
                "success": False,
                "text": (
                    "The development job failed safely before deployment.\n"
                    f"Reason: {exc}"
                ),
            }

    @staticmethod
    def _format_success(job_id: str, report: dict[str, Any]) -> str:
        generation = report.get("generation") or {}
        validation = report.get("validation") or {}
        tests = report.get("tests") or {}

        changes = generation.get("changes") or []
        change_count = len(changes)

        validation_ok = validation.get("success")
        tests_ok = tests.get("success")

        return (
            "🛠️ Development job completed.\n\n"
            f"Job: {job_id}\n"
            f"Generated changes: {change_count}\n"
            f"Validation: {'PASS' if validation_ok else 'FAIL'}\n"
            f"Tests: {'PASS' if tests_ok else 'FAIL'}\n\n"
            "No production deployment or GitHub push was performed."
        )

    @staticmethod
    def _format_failure(
        job_id: str,
        report: dict[str, Any] | None,
        metadata: dict[str, Any],
    ) -> str:
        reason = metadata.get("error") if isinstance(metadata, dict) else None

        if report:
            failures = report.get("failures") or []
            if failures:
                reason = str(failures[-1])

        return (
            "🛠️ Development job finished with failure.\n\n"
            f"Job: {job_id}\n"
            f"Reason: {reason or 'Validation or testing failed.'}\n\n"
            "No production deployment or GitHub push was performed."
        )


__all__ = ["TelegramDevelopmentInterface"]
