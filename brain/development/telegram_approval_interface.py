from __future__ import annotations

import logging
import os
from typing import Any

from .approval_manager import ApprovalManager

logger = logging.getLogger("aria.telegram_approval")


class TelegramApprovalInterface:
    """Master-only Telegram interface for approval gates."""

    def __init__(self, approval_manager: ApprovalManager) -> None:
        self.approval_manager = approval_manager

    @staticmethod
    def _authorized(user_id: Any) -> bool:
        allowed = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()
        return bool(allowed) and str(user_id).strip() == allowed

    @staticmethod
    def _bounded(value: Any, limit: int = 3500) -> str:
        text = str(value or "").strip()
        return text[:limit] if text else "<empty>"

    @staticmethod
    def _parse(text: str) -> tuple[str, str | None]:
        if not isinstance(text, str):
            return "none", None

        value = text.strip()
        lower = value.lower()

        if not value:
            return "none", None

        if lower in {
            "/master approvals",
            "/master approval",
            "master approvals",
            "master approval",
        }:
            return "list", None

        prefixes = (
            "/master approve",
            "master approve",
            "master, approve",
        )
        for prefix in prefixes:
            if lower.startswith(prefix):
                request_id = value[len(prefix):].strip(" :,-\t\r\n")
                return "approve", request_id or None

        prefixes = (
            "/master reject",
            "master reject",
            "master, reject",
        )
        for prefix in prefixes:
            if lower.startswith(prefix):
                request_id = value[len(prefix):].strip(" :,-\t\r\n")
                return "reject", request_id or None

        return "none", None

    async def handle(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> dict[str, Any] | None:
        command, request_id = self._parse(text)

        if command == "none":
            return None

        if not self._authorized(user_id):
            logger.warning(
                "[Phase1][TelegramApproval] Unauthorized approval command | user_id=%s",
                user_id,
            )
            return {
                "handled": True,
                "success": False,
                "text": "Only the authorized Master can approve or reject engineering operations.",
            }

        if command == "list":
            return self._list_pending()

        if not request_id:
            return {
                "handled": True,
                "success": False,
                "text": (
                    "Provide an approval request ID.\n\n"
                    "Example:\n"
                    "/master approve approval-20261004073000-0001"
                ),
            }

        try:
            if command == "approve":
                decision = self.approval_manager.approve(
                    request_id,
                    decided_by=f"Telegram Master:{user_id}",
                )
            else:
                decision = self.approval_manager.reject(
                    request_id,
                    decided_by=f"Telegram Master:{user_id}",
                )

            return {
                "handled": True,
                "success": bool(decision.approved) if command == "approve" else True,
                "text": self._decision_text(decision),
                "decision": decision.to_dict(),
            }

        except KeyError:
            return {
                "handled": True,
                "success": False,
                "text": (
                    f"Approval request <code>{self._bounded(request_id, 200)}</code> "
                    "does not exist, has expired, or was already decided."
                ),
            }
        except Exception as exc:
            logger.exception("[Phase1][TelegramApproval] Decision failed")
            return {
                "handled": True,
                "success": False,
                "text": f"Approval decision failed safely.\n\nReason: {self._bounded(exc)}",
            }

    def _list_pending(self) -> dict[str, Any]:
        requests = self.approval_manager.pending_requests()

        if not requests:
            return {
                "handled": True,
                "success": True,
                "text": "🟢 No pending approval requests.",
                "requests": [],
            }

        lines = ["🔐 <b>Pending Approval Requests</b>", ""]
        data = []

        for request in requests:
            item = request.to_dict()
            data.append(item)
            lines.extend(
                [
                    f"<b>{request.request_id}</b>",
                    f"Operation: {self._bounded(request.operation, 300)}",
                    f"Risk: {request.risk_level.upper()}",
                    f"Reason: {self._bounded(request.reason, 500)}",
                    f"Created: {request.created_at}",
                    "",
                ]
            )

        lines.append(
            "Approve with: /master approve &lt;request_id&gt;"
        )
        lines.append(
            "Reject with: /master reject &lt;request_id&gt;"
        )

        return {
            "handled": True,
            "success": True,
            "text": "\n".join(lines)[:4000],
            "requests": data,
        }

    @staticmethod
    def _decision_text(decision: Any) -> str:
        if decision.approved:
            return (
                "✅ <b>Approval granted</b>\n\n"
                f"Request: <code>{decision.request_id}</code>\n"
                f"By: {decision.decided_by}\n"
                f"Reason: {decision.reason}\n\n"
                "The waiting engineering workflow may now continue."
            )

        return (
            "🛑 <b>Approval rejected</b>\n\n"
            f"Request: <code>{decision.request_id}</code>\n"
            f"By: {decision.decided_by}\n"
            f"Reason: {decision.reason}\n\n"
            "The gated workflow must remain stopped."
        )

    def status(self) -> dict[str, Any]:
        pending = self.approval_manager.pending_requests()
        return {
            "pending_count": len(pending),
            "pending_request_ids": [
                request.request_id for request in pending
            ],
            "master_authorization_required": True,
        }

    def health(self) -> dict[str, Any]:
        return {
            "healthy": self.approval_manager is not None,
            "master_authorization_required": True,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "name": "telegram_approval_interface",
            "capabilities": [
                "list_pending_approvals",
                "approve",
                "reject",
                "continue_waiting_workflows",
            ],
            "safety": [
                "master_only",
                "fail_closed",
                "no_direct_operation_execution",
                "existing_approval_manager_timeout",
            ],
        }


__all__ = ["TelegramApprovalInterface"]
