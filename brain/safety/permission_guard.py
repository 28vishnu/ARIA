"""
ARIA Permission Guard
=====================

Phase 1 - Step 18

Central safety and permission boundary for autonomous execution.

Responsibilities
----------------
- classify requested actions
- distinguish safe / approval-required / blocked actions
- enforce bounded execution policy
- prevent unrestricted destructive operations
- provide a single decision object to orchestration
- support explicit user approval
- maintain an auditable decision history

Design
------
The permission guard does NOT execute anything.

It only answers:

    ALLOW
    ASK
    BLOCK

The actual executor remains responsible for execution.
"""

from __future__ import annotations

import hashlib
import logging

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger("aria")


# ============================================================================
# CONSTANTS
# ============================================================================

MAX_HISTORY = 200
MAX_REASON_LENGTH = 2000
MAX_ACTION_LENGTH = 500
MAX_RESOURCE_LENGTH = 1000


DECISION_ALLOW = "allow"
DECISION_ASK = "ask"
DECISION_BLOCK = "block"

VALID_DECISIONS = {
    DECISION_ALLOW,
    DECISION_ASK,
    DECISION_BLOCK,
}


# ============================================================================
# ACTION CATEGORIES
# ============================================================================

CATEGORY_READ = "read"

CATEGORY_CREATE = "create"

CATEGORY_MODIFY = "modify"

CATEGORY_DELETE = "delete"

CATEGORY_EXECUTE = "execute"

CATEGORY_NETWORK = "network"

CATEGORY_COMMUNICATION = "communication"

CATEGORY_FINANCIAL = "financial"

CATEGORY_CREDENTIAL = "credential"

CATEGORY_SYSTEM = "system"

CATEGORY_UNKNOWN = "unknown"


# ============================================================================
# POLICY
# ============================================================================

DEFAULT_ALLOWED_CATEGORIES = {
    CATEGORY_READ,
    CATEGORY_CREATE,
    CATEGORY_MODIFY,
    CATEGORY_EXECUTE,
    CATEGORY_NETWORK,
}

DEFAULT_APPROVAL_CATEGORIES = {
    CATEGORY_DELETE,
    CATEGORY_COMMUNICATION,
    CATEGORY_FINANCIAL,
    CATEGORY_CREDENTIAL,
    CATEGORY_SYSTEM,
}


# Explicitly dangerous patterns.

BLOCKED_ACTION_PATTERNS = (
    "disable security",
    "bypass security",
    "bypass authentication",
    "steal password",
    "steal credentials",
    "credential theft",
    "delete all system files",
    "format operating system",
    "destroy database",
    "wipe database",
    "disable antivirus",
    "disable firewall",
    "ransomware",
    "keylogger",
    "persistence malware",
)


# Actions that are not automatically safe even if their category
# looks harmless.

APPROVAL_ACTION_PATTERNS = (
    "send email",
    "send message",
    "publish",
    "post publicly",
    "delete",
    "remove account",
    "close account",
    "purchase",
    "buy",
    "pay",
    "transfer money",
    "change password",
    "change credentials",
    "grant permission",
    "revoke permission",
    "install software",
    "uninstall software",
    "modify firewall",
    "modify security settings",
)


# ============================================================================
# HELPERS
# ============================================================================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(
    value: Any,
    limit: int = MAX_REASON_LENGTH,
) -> str:
    if value is None:
        return ""

    value = str(value).strip()

    if len(value) <= limit:
        return value

    return value[:limit] + "\n[TRUNCATED]"


def _fingerprint(
    *values: Any,
) -> str:
    raw = "|".join(
        _text(
            value,
            1000,
        ).lower()
        for value in values
    )

    return hashlib.sha256(
        raw.encode(
            "utf-8",
            errors="ignore",
        )
    ).hexdigest()[:24]


# ============================================================================
# DATA MODEL
# ============================================================================

@dataclass
class PermissionDecision:
    """
    Result of a permission check.
    """

    decision: str

    action: str

    category: str

    reason: str = ""

    requires_approval: bool = False

    approval_token: str = ""

    risk_level: str = "low"

    reversible: bool = True

    resource: str = ""

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    created_at: datetime = field(
        default_factory=_utc_now
    )

    def allowed(self) -> bool:
        return self.decision == DECISION_ALLOW

    def needs_approval(self) -> bool:
        return self.decision == DECISION_ASK

    def blocked(self) -> bool:
        return self.decision == DECISION_BLOCK

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "action": self.action,
            "category": self.category,
            "reason": self.reason,
            "requires_approval": (
                self.requires_approval
            ),
            "approval_token": (
                self.approval_token
            ),
            "risk_level": self.risk_level,
            "reversible": self.reversible,
            "resource": self.resource,
            "metadata": dict(
                self.metadata
            ),
            "created_at": (
                self.created_at.isoformat()
            ),
        }


# ============================================================================
# PERMISSION GUARD
# ============================================================================

class PermissionGuard:
    """
    Central safety policy engine.

    It is intentionally conservative around:
        - deletion
        - communications
        - money
        - credentials
        - security settings
        - system-level operations
    """

    def __init__(
        self,
        allowed_categories: Optional[
            set
        ] = None,
        approval_categories: Optional[
            set
        ] = None,
        max_history: int = MAX_HISTORY,
    ):
        self.allowed_categories = set(
            allowed_categories
            or DEFAULT_ALLOWED_CATEGORIES
        )

        self.approval_categories = set(
            approval_categories
            or DEFAULT_APPROVAL_CATEGORIES
        )

        self.max_history = max(
            20,
            int(max_history),
        )

        self._history: List[
            PermissionDecision
        ] = []

        self._approved_tokens: Dict[
            str,
            datetime,
        ] = {}

        self.statistics = {
            "checks": 0,
            "allowed": 0,
            "approval_required": 0,
            "blocked": 0,
            "approvals": 0,
            "expired_tokens": 0,
        }

    # ========================================================================
    # CLASSIFICATION
    # ========================================================================

    def classify_action(
        self,
        action: str,
    ) -> str:
        """
        Classify an action into a broad safety category.
        """

        text = _text(
            action,
            MAX_ACTION_LENGTH,
        ).lower()

        if not text:
            return CATEGORY_UNKNOWN

        # Destructive operations first.
        if any(
            word in text
            for word in (
                "delete",
                "remove",
                "wipe",
                "destroy",
                "erase",
                "drop database",
                "truncate",
                "format",
            )
        ):
            return CATEGORY_DELETE

        if any(
            word in text
            for word in (
                "password",
                "credential",
                "secret",
                "api key",
                "private key",
                "token",
            )
        ):
            return CATEGORY_CREDENTIAL

        if any(
            word in text
            for word in (
                "purchase",
                "buy",
                "pay",
                "payment",
                "money",
                "transfer",
                "bank",
            )
        ):
            return CATEGORY_FINANCIAL

        if any(
            word in text
            for word in (
                "email",
                "message",
                "send",
                "reply",
                "publish",
                "post",
                "contact",
            )
        ):
            return CATEGORY_COMMUNICATION

        if any(
            word in text
            for word in (
                "firewall",
                "antivirus",
                "security",
                "permission",
                "privilege",
                "sudo",
                "root",
                "system settings",
            )
        ):
            return CATEGORY_SYSTEM

        if any(
            word in text
            for word in (
                "http",
                "https",
                "request",
                "download",
                "upload",
                "web",
                "internet",
                "api",
            )
        ):
            return CATEGORY_NETWORK

        if any(
            word in text
            for word in (
                "read",
                "view",
                "inspect",
                "list",
                "search",
                "find",
                "get",
                "check",
            )
        ):
            return CATEGORY_READ

        if any(
            word in text
            for word in (
                "create",
                "generate",
                "write",
                "build",
                "make",
            )
        ):
            return CATEGORY_CREATE

        if any(
            word in text
            for word in (
                "edit",
                "modify",
                "update",
                "change",
                "rename",
            )
        ):
            return CATEGORY_MODIFY

        if any(
            word in text
            for word in (
                "run",
                "execute",
                "launch",
                "start",
                "command",
            )
        ):
            return CATEGORY_EXECUTE

        return CATEGORY_UNKNOWN

    # ========================================================================
    # RISK
    # ========================================================================

    def risk_level(
        self,
        category: str,
        action: str = "",
    ) -> str:
        """
        Determine a conservative risk level.
        """

        category = _text(
            category,
            100,
        ).lower()

        action = _text(
            action,
            MAX_ACTION_LENGTH,
        ).lower()

        if category in {
            CATEGORY_FINANCIAL,
            CATEGORY_CREDENTIAL,
        }:
            return "critical"

        if category in {
            CATEGORY_DELETE,
            CATEGORY_SYSTEM,
        }:
            return "high"

        if category == CATEGORY_COMMUNICATION:
            return "medium"

        if category == CATEGORY_NETWORK:
            return "medium"

        if any(
            pattern in action
            for pattern in APPROVAL_ACTION_PATTERNS
        ):
            return "medium"

        return "low"

    # ========================================================================
    # BLOCKING
    # ========================================================================

    def _is_blocked(
        self,
        action: str,
    ) -> Optional[str]:
        text = _text(
            action,
            MAX_ACTION_LENGTH,
        ).lower()

        for pattern in BLOCKED_ACTION_PATTERNS:

            if pattern in text:
                return (
                    f"Action matches blocked safety pattern: "
                    f"{pattern}"
                )

        return None

    # ========================================================================
    # APPROVAL TOKEN
    # ========================================================================

    def _create_approval_token(
        self,
        action: str,
        resource: str,
    ) -> str:
        return _fingerprint(
            action,
            resource,
            _utc_now().timestamp(),
        )

    def approve(
        self,
        decision: PermissionDecision,
    ) -> str:
        """
        Approve one specific ASK decision.

        Approval is intentionally tied to the exact action/resource
        combination represented by the generated token.
        """

        if (
            decision.decision
            != DECISION_ASK
        ):
            raise ValueError(
                "Only approval-required decisions can be approved."
            )

        token = decision.approval_token

        if not token:
            raise ValueError(
                "Decision has no approval token."
            )

        self._approved_tokens[
            token
        ] = _utc_now()

        self.statistics[
            "approvals"
        ] += 1

        return token

    def revoke(
        self,
        token: str,
    ) -> bool:
        token = _text(
            token,
            200,
        )

        if token in self._approved_tokens:

            self._approved_tokens.pop(
                token,
                None,
            )

            return True

        return False

    def _token_valid(
        self,
        token: str,
    ) -> bool:
        if not token:
            return False

        created = self._approved_tokens.get(
            token
        )

        if created is None:
            return False

        # Approval tokens are short-lived.
        age = (
            _utc_now()
            - created
        ).total_seconds()

        if age > 300:

            self._approved_tokens.pop(
                token,
                None,
            )

            self.statistics[
                "expired_tokens"
            ] += 1

            return False

        return True

    # ========================================================================
    # MAIN CHECK
    # ========================================================================

    def check(
        self,
        action: str,
        *,
        resource: str = "",
        category: Optional[
            str
        ] = None,
        approved: bool = False,
        approval_token: str = "",
        reversible: bool = True,
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> PermissionDecision:
        """
        Evaluate an action.

        Returns:
            allow
            ask
            block
        """

        self.statistics[
            "checks"
        ] += 1

        action = _text(
            action,
            MAX_ACTION_LENGTH,
        )

        resource = _text(
            resource,
            MAX_RESOURCE_LENGTH,
        )

        if not action:

            decision = PermissionDecision(
                decision=DECISION_BLOCK,
                action="",
                category=CATEGORY_UNKNOWN,
                reason="Empty action is not executable.",
                risk_level="high",
                reversible=reversible,
                resource=resource,
            )

            self._record(
                decision
            )

            return decision

        blocked_reason = self._is_blocked(
            action
        )

        if blocked_reason:

            decision = PermissionDecision(
                decision=DECISION_BLOCK,
                action=action,
                category=(
                    category
                    or self.classify_action(
                        action
                    )
                ),
                reason=blocked_reason,
                risk_level="critical",
                reversible=reversible,
                resource=resource,
                metadata=dict(
                    metadata or {}
                ),
            )

            self.statistics[
                "blocked"
            ] += 1

            self._record(
                decision
            )

            return decision

        category = (
            _text(
                category,
                100,
            ).lower()
            if category
            else self.classify_action(
                action
            )
        )

        risk = self.risk_level(
            category,
            action,
        )

        # Explicit approval token.
        if (
            approval_token
            and self._token_valid(
                approval_token
            )
        ):

            decision = PermissionDecision(
                decision=DECISION_ALLOW,
                action=action,
                category=category,
                reason=(
                    "Valid user approval token supplied."
                ),
                requires_approval=False,
                approval_token=approval_token,
                risk_level=risk,
                reversible=reversible,
                resource=resource,
                metadata=dict(
                    metadata or {}
                ),
            )

            self.statistics[
                "allowed"
            ] += 1

            self._record(
                decision
            )

            return decision

        # Explicit approval supplied by caller.
        if approved:

            decision = PermissionDecision(
                decision=DECISION_ALLOW,
                action=action,
                category=category,
                reason=(
                    "Explicit approval supplied by caller."
                ),
                requires_approval=False,
                risk_level=risk,
                reversible=reversible,
                resource=resource,
                metadata=dict(
                    metadata or {}
                ),
            )

            self.statistics[
                "allowed"
            ] += 1

            self._record(
                decision
            )

            return decision

        # Financial, credential and system operations.
        if category in self.approval_categories:

            decision = PermissionDecision(
                decision=DECISION_ASK,
                action=action,
                category=category,
                reason=(
                    "User approval is required for "
                    f"{category} actions."
                ),
                requires_approval=True,
                approval_token=self._create_approval_token(
                    action,
                    resource,
                ),
                risk_level=risk,
                reversible=reversible,
                resource=resource,
                metadata=dict(
                    metadata or {}
                ),
            )

            self.statistics[
                "approval_required"
            ] += 1

            self._record(
                decision
            )

            return decision

        # Pattern-based approval.
        action_lower = action.lower()

        if any(
            pattern in action_lower
            for pattern in APPROVAL_ACTION_PATTERNS
        ):

            decision = PermissionDecision(
                decision=DECISION_ASK,
                action=action,
                category=category,
                reason=(
                    "This action requires explicit "
                    "user approval."
                ),
                requires_approval=True,
                approval_token=self._create_approval_token(
                    action,
                    resource,
                ),
                risk_level=risk,
                reversible=reversible,
                resource=resource,
                metadata=dict(
                    metadata or {}
                ),
            )

            self.statistics[
                "approval_required"
            ] += 1

            self._record(
                decision
            )

            return decision

        # Unknown actions are not automatically granted.
        if category == CATEGORY_UNKNOWN:

            decision = PermissionDecision(
                decision=DECISION_ASK,
                action=action,
                category=category,
                reason=(
                    "Unknown action category; "
                    "explicit approval is required."
                ),
                requires_approval=True,
                approval_token=self._create_approval_token(
                    action,
                    resource,
                ),
                risk_level="medium",
                reversible=reversible,
                resource=resource,
                metadata=dict(
                    metadata or {}
                ),
            )

            self.statistics[
                "approval_required"
            ] += 1

            self._record(
                decision
            )

            return decision

        # Safe allowed categories.
        if category in self.allowed_categories:

            decision = PermissionDecision(
                decision=DECISION_ALLOW,
                action=action,
                category=category,
                reason=(
                    "Action is within the configured "
                    "autonomous permission boundary."
                ),
                requires_approval=False,
                risk_level=risk,
                reversible=reversible,
                resource=resource,
                metadata=dict(
                    metadata or {}
                ),
            )

            self.statistics[
                "allowed"
            ] += 1

            self._record(
                decision
            )

            return decision

        # Final conservative fallback.
        decision = PermissionDecision(
            decision=DECISION_ASK,
            action=action,
            category=category,
            reason=(
                "Action is outside the automatic "
                "permission boundary."
            ),
            requires_approval=True,
            approval_token=self._create_approval_token(
                action,
                resource,
            ),
            risk_level=risk,
            reversible=reversible,
            resource=resource,
            metadata=dict(
                metadata or {}
            ),
        )

        self.statistics[
            "approval_required"
        ] += 1

        self._record(
            decision
        )

        return decision

    # ========================================================================
    # BATCH CHECK
    # ========================================================================

    def check_plan(
        self,
        actions: List[Any],
    ) -> Dict[str, Any]:
        """
        Check a collection of planned actions before execution.

        The entire plan is blocked if any action is blocked.

        If at least one action requires approval, the plan is marked
        approval_required.
        """

        decisions = []

        for item in actions:

            if isinstance(
                item,
                dict,
            ):

                action = item.get(
                    "action",
                    item.get(
                        "name",
                        "",
                    ),
                )

                resource = item.get(
                    "resource",
                    "",
                )

                category = item.get(
                    "category"
                )

                reversible = bool(
                    item.get(
                        "reversible",
                        True,
                    )
                )

            else:

                action = str(
                    item
                )

                resource = ""

                category = None

                reversible = True

            decisions.append(
                self.check(
                    action=action,
                    resource=resource,
                    category=category,
                    reversible=reversible,
                )
            )

        blocked = any(
            decision.blocked()
            for decision in decisions
        )

        approval_required = any(
            decision.needs_approval()
            for decision in decisions
        )

        if blocked:

            overall = DECISION_BLOCK

        elif approval_required:

            overall = DECISION_ASK

        else:

            overall = DECISION_ALLOW

        return {
            "decision": overall,
            "allowed": (
                overall == DECISION_ALLOW
            ),
            "approval_required": (
                overall == DECISION_ASK
            ),
            "blocked": (
                overall == DECISION_BLOCK
            ),
            "decisions": [
                decision.to_dict()
                for decision in decisions
            ],
        }

    # ========================================================================
    # HISTORY
    # ========================================================================

    def _record(
        self,
        decision: PermissionDecision,
    ) -> None:

        self._history.append(
            decision
        )

        if (
            len(self._history)
            > self.max_history
        ):
            self._history = (
                self._history[
                    -self.max_history:
                ]
            )

    def history(
        self,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:

        limit = max(
            1,
            min(
                int(limit),
                self.max_history,
            ),
        )

        return [
            decision.to_dict()
            for decision in reversed(
                self._history[-limit:]
            )
        ]

    # ========================================================================
    # HEALTH
    # ========================================================================

    def health(self) -> Dict[str, Any]:

        return {
            "component": (
                "permission_guard"
            ),
            "status": "healthy",
            "allowed_categories": sorted(
                self.allowed_categories
            ),
            "approval_categories": sorted(
                self.approval_categories
            ),
            "history_size": len(
                self._history
            ),
            "statistics": dict(
                self.statistics
            ),
        }

    def describe(self) -> Dict[str, Any]:

        return {
            "component": "PermissionGuard",
            "purpose": (
                "Enforce ARIA's autonomous "
                "safety and permission boundary."
            ),
            "llm_required": False,
            "execution_side_effects": False,
            "decisions": [
                DECISION_ALLOW,
                DECISION_ASK,
                DECISION_BLOCK,
            ],
            "protected_categories": [
                CATEGORY_DELETE,
                CATEGORY_COMMUNICATION,
                CATEGORY_FINANCIAL,
                CATEGORY_CREDENTIAL,
                CATEGORY_SYSTEM,
            ],
            "features": [
                "action classification",
                "risk classification",
                "blocked-action detection",
                "approval tokens",
                "plan-level permission checks",
                "decision history",
                "bounded approval lifetime",
            ],
        }