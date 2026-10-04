from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TelegramEngineeringCommand(str, Enum):
    NONE = "none"
    DEVELOP = "develop"
    STATUS = "status"
    RESUME = "resume"
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    SELF_UPGRADE = "self_upgrade"
    HELP = "help"


class TelegramEngineeringAction(str, Enum):
    START_ENGINEERING = "start_engineering"
    SHOW_STATUS = "show_status"
    RESUME_ENGINEERING = "resume_engineering"
    APPROVE_OPERATION = "approve_operation"
    REJECT_OPERATION = "reject_operation"
    CANCEL_ENGINEERING = "cancel_engineering"
    PLAN_SELF_UPGRADE = "plan_self_upgrade"
    SHOW_HELP = "show_help"
    IGNORE = "ignore"


class TelegramAuthorizationStatus(str, Enum):
    AUTHORIZED = "authorized"
    UNAUTHORIZED = "unauthorized"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class TelegramEngineeringRequest:
    """
    Canonical request produced by the Telegram command boundary.

    This object contains intent only. It does not execute engineering,
    GitHub, deployment, or self-modification operations.
    """

    command: TelegramEngineeringCommand
    action: TelegramEngineeringAction
    raw_text: str
    requirement_text: str | None = None
    session_id: str | None = None
    approval_id: str | None = None
    user_id: str | None = None
    authorization: TelegramAuthorizationStatus = (
        TelegramAuthorizationStatus.NOT_CONFIGURED
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_engineering(self) -> bool:
        return self.command in {
            TelegramEngineeringCommand.DEVELOP,
            TelegramEngineeringCommand.RESUME,
            TelegramEngineeringCommand.SELF_UPGRADE,
            TelegramEngineeringCommand.APPROVE,
            TelegramEngineeringCommand.REJECT,
            TelegramEngineeringCommand.CANCEL,
        }

    @property
    def requires_authorization(self) -> bool:
        return self.is_engineering

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command.value,
            "action": self.action.value,
            "raw_text": self.raw_text,
            "requirement_text": self.requirement_text,
            "session_id": self.session_id,
            "approval_id": self.approval_id,
            "user_id": self.user_id,
            "authorization": self.authorization.value,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class TelegramEngineeringResponse:
    """
    Canonical response returned by the engineering command adapter.

    The adapter never interprets a successful command parse as successful
    engineering. Engineering success must come from the authoritative
    engineering lifecycle.
    """

    handled: bool
    success: bool
    text: str
    command: TelegramEngineeringCommand = TelegramEngineeringCommand.NONE
    action: TelegramEngineeringAction = TelegramEngineeringAction.IGNORE
    session_id: str | None = None
    status: str | None = None
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handled": self.handled,
            "success": self.success,
            "text": self.text,
            "command": self.command.value,
            "action": self.action.value,
            "session_id": self.session_id,
            "status": self.status,
            "result": (
                self.result.to_dict()
                if hasattr(self.result, "to_dict")
                else self.result
            ),
            "error": self.error,
            "metadata": dict(self.metadata),
        }


__all__ = [
    "TelegramEngineeringCommand",
    "TelegramEngineeringAction",
    "TelegramAuthorizationStatus",
    "TelegramEngineeringRequest",
    "TelegramEngineeringResponse",
]