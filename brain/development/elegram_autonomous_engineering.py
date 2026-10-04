from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("aria.telegram_engineering")


class TelegramAutonomousEngineeringInterface:
    """Master-only Telegram gateway to the Phase 1 runtime."""

    def __init__(self, phase1_runtime: Any) -> None:
        self.phase1_runtime = phase1_runtime

    @staticmethod
    def _authorized(user_id: Any) -> bool:
        allowed = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()
        return bool(allowed) and str(user_id).strip() == allowed

    @staticmethod
    def _bounded(value: Any, limit: int = 3500) -> str:
        return str(value or "").strip()[:limit]

    @staticmethod
    def _requirement(text: str) -> str | None:
        if not isinstance(text, str):
            return None
        value = text.strip()
        lower = value.lower()
        prefixes = (
            "/master develop",
            "/master  develop",
            "master develop",
            "master develop:",
            "master, develop",
        )
        for prefix in prefixes:
            if lower.startswith(prefix):
                requirement = value[len(prefix):].strip(" :,-\t\r\n")
                return requirement or None
        return None

    @staticmethod
    def _json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, default=str)[:3500]
        except Exception:
            return str(value)[:3500]

    async def handle(self, *, user_id: Any, text: str) -> dict[str, Any] | None:
        requirement = self._requirement(text)
        if requirement is None:
            return None

        if not self._authorized(user_id):
            return {
                "handled": True,
                "success": False,
                "text": "I can only accept autonomous engineering commands from the authorized Master account.",
            }

        try:
            result = await self.phase1_runtime.develop(requirement)
            data = result.to_dict() if hasattr(result, "to_dict") else result
            success = bool(data.get("success", False)) if isinstance(data, dict) else bool(getattr(result, "success", False))
            return {
                "handled": True,
                "success": success,
                "text": (
                    "✅ Autonomous engineering completed.\n\n"
                    if success
                    else "🛠️ Autonomous engineering finished without acceptance.\n\n"
                ) + self._json(data),
                "result": data,
            }
        except Exception as exc:
            logger.exception("[Phase1][TelegramEngineering] Autonomous development failed")
            return {
                "handled": True,
                "success": False,
                "text": (
                    "Autonomous engineering failed safely.\n\n"
                    f"Reason: {self._bounded(exc)}\n\n"
                    "No unapproved GitHub push or production deployment was performed."
                ),
            }

    def status(self) -> dict[str, Any]:
        try:
            return self.phase1_runtime.status()
        except Exception as exc:
            return {"healthy": False, "error": str(exc)}

    def health(self) -> dict[str, Any]:
        try:
            return self.phase1_runtime.health()
        except Exception as exc:
            return {"healthy": False, "error": str(exc)}


__all__ = ["TelegramAutonomousEngineeringInterface"]
