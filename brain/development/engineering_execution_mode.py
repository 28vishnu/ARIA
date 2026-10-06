"""
ARIA Engineering Execution Mode
================================

Canonical deterministic execution-policy boundary for engineering requests.

This module does NOT execute engineering work.

It determines whether the current request is:

    answer_or_research
    inspect_only
    plan_only
    execute

and exposes explicit safety flags consumed by the canonical JARVIS
integration pipeline.

Important safety rule:

    plan_only / inspect_only
        -> no implementation
        -> no mutation
        -> no commit
        -> no GitHub push
        -> no deployment
        -> no rollback

    execute
        -> implementation may be performed by the authoritative
           autonomous engineering lifecycle

    GitHub push / merge / deployment / rollback
        -> remain independently authorization-gated by
           MasterDeliveryAuthorization.

This file intentionally contains policy only.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple


logger = logging.getLogger("aria.engineering_execution_mode")


@dataclass(frozen=True)
class EngineeringExecutionDecision:
    """
    Immutable execution-policy decision.

    The decision is descriptive only. It never performs an action.
    """

    mode: str

    plan_only: bool = False
    inspect_only: bool = False

    execution_allowed: bool = False
    repository_inspection_allowed: bool = False

    mutation_allowed: bool = False
    file_write_allowed: bool = False

    commit_allowed: bool = False
    github_push_allowed: bool = False
    merge_allowed: bool = False

    deployment_allowed: bool = False
    rollback_allowed: bool = False

    authorization_required: bool = False

    reason: str = ""

    signals: Tuple[str, ...] = field(default_factory=tuple)

    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a deterministic serializable representation."""

        return {
            "mode": self.mode,
            "plan_only": self.plan_only,
            "inspect_only": self.inspect_only,
            "execution_allowed": self.execution_allowed,
            "repository_inspection_allowed": (
                self.repository_inspection_allowed
            ),
            "mutation_allowed": self.mutation_allowed,
            "file_write_allowed": self.file_write_allowed,
            "commit_allowed": self.commit_allowed,
            "github_push_allowed": self.github_push_allowed,
            "merge_allowed": self.merge_allowed,
            "deployment_allowed": self.deployment_allowed,
            "rollback_allowed": self.rollback_allowed,
            "authorization_required": self.authorization_required,
            "reason": self.reason,
            "signals": list(self.signals),
            "confidence": self.confidence,
        }


class EngineeringExecutionMode:
    """
    Canonical engineering execution-policy selector.

    This component is intentionally side-effect free.

    It must be safe to call multiple times for the same request.
    """

    VERSION = "ARIA-ENGINEERING-EXECUTION-MODE-20261006"

    MODE_ANSWER = "answer_or_research"
    MODE_INSPECT = "inspect_only"
    MODE_PLAN = "plan_only"
    MODE_EXECUTE = "execute"

    VALID_MODES = frozenset(
        {
            MODE_ANSWER,
            MODE_INSPECT,
            MODE_PLAN,
            MODE_EXECUTE,
        }
    )

    # ------------------------------------------------------------------
    # Explicit user prohibitions
    # ------------------------------------------------------------------

    _NO_ACTION_PATTERNS = (
        r"\bdo\s+not\s+(?:modify|change|edit|write|create|delete)\b",
        r"\bdon['’]?t\s+(?:modify|change|edit|write|create|delete)\b",
        r"\bdo\s+not\s+execute\b",
        r"\bdon['’]?t\s+execute\b",
        r"\bdo\s+not\s+run\b",
        r"\bdon['’]?t\s+run\b",
        r"\bdo\s+not\s+implement\b",
        r"\bdon['’]?t\s+implement\b",
        r"\bdo\s+not\s+commit\b",
        r"\bdon['’]?t\s+commit\b",
        r"\bdo\s+not\s+push\b",
        r"\bdon['’]?t\s+push\b",
        r"\bdo\s+not\s+deploy\b",
        r"\bdon['’]?t\s+deploy\b",
        r"\bno\s+(?:file\s+)?changes\b",
        r"\bwithout\s+(?:changing|modifying|editing|writing)\b",
        r"\bwithout\s+execut(?:ing|ion)\b",
        r"\bwithout\s+mutation\b",
    )

    _PLAN_PATTERNS = (
        r"\bplan\s+(?:how|what|the)\b",
        r"\bimplementation\s+plan\b",
        r"\barchitecture\s+(?:plan|design)\b",
        r"\bdesign\s+the\s+implementation\b",
        r"\bgive\s+me\s+(?:a\s+)?plan\b",
        r"\bcreate\s+(?:a\s+)?plan\b",
        r"\broadmap\b",
        r"\bsteps?\s+(?:to|for)\b",
        r"\bhow\s+would\s+you\s+(?:add|implement|build|integrate)\b",
    )

    _INSPECT_PATTERNS = (
        r"\binspect\b",
        r"\banaly[sz]e\b",
        r"\banaly[sz]e\s+the\s+repository\b",
        r"\breview\s+the\s+repository\b",
        r"\breview\s+the\s+code\b",
        r"\bexplain\s+the\s+(?:current\s+)?architecture\b",
        r"\bwhat\s+is\s+the\s+current\s+architecture\b",
        r"\bshow\s+me\s+the\s+architecture\b",
        r"\btrace\s+the\s+(?:pipeline|flow|lifecycle)\b",
        r"\bunderstand\s+the\s+repository\b",
        r"\bunderstand\s+the\s+codebase\b",
        r"\breadiness\s+report\b",
        r"\bstatus\s+of\s+the\s+(?:engineering|repository)\b",
    )

    _EXECUTE_PATTERNS = (
        r"\bimplement\b",
        r"\bbuild\b",
        r"\bdevelop\b",
        r"\bcreate\b",
        r"\badd\b",
        r"\bmodify\b",
        r"\bchange\b",
        r"\bupdate\b",
        r"\bfix\b",
        r"\brefactor\b",
        r"\bwrite\s+(?:the\s+)?code\b",
        r"\bcode\s+this\b",
        r"\bmake\s+the\s+changes\b",
        r"\bapply\s+the\s+changes\b",
        r"\bfinish\s+(?:this|the)\b",
        r"\bcomplete\s+(?:this|the)\b",
    )

    _DELIVERY_PATTERNS = (
        r"\bpush\b",
        r"\bgithub\b",
        r"\bmerge\b",
        r"\bdeploy\b",
        r"\bdeployment\b",
        r"\brollback\b",
        r"\brelease\b",
        r"\bpublish\b",
    )

    _RESEARCH_PATTERNS = (
        r"\bresearch\b",
        r"\blook\s+up\b",
        r"\bfind\s+out\b",
        r"\bcompare\b",
        r"\binvestigate\b",
        r"\bwhat\s+does\b",
        r"\bwhy\s+does\b",
        r"\bhow\s+does\b",
    )

    def __init__(
        self,
        *,
        default_mode: str = MODE_ANSWER,
        allow_execution: bool = True,
    ) -> None:
        normalized_default = self._normalize_mode(default_mode)

        if normalized_default not in self.VALID_MODES:
            normalized_default = self.MODE_ANSWER

        self.default_mode = normalized_default
        self.allow_execution = bool(allow_execution)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def determine(
        self,
        request: Any = "",
        *,
        query: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> EngineeringExecutionDecision:
        """
        Determine the canonical execution mode.

        ``query`` is supported as an explicit alias because different
        integration layers historically used different parameter names.
        """

        text = self._extract_text(request, query=query)
        ctx = dict(context or {})

        signals = self._collect_signals(text, ctx)

        explicit_mode = self._explicit_context_mode(ctx)

        # --------------------------------------------------------------
        # Hard safety boundary: explicit prohibition always wins.
        # --------------------------------------------------------------

        if signals["prohibition"]:
            return self._decision(
                self.MODE_INSPECT,
                reason=(
                    "The request explicitly prohibits implementation, "
                    "execution, or mutation."
                ),
                signals=signals["all"],
                repository_inspection_allowed=True,
                confidence=1.0,
            )

        # --------------------------------------------------------------
        # Explicit plan-only / read-only context
        # --------------------------------------------------------------

        if self._truthy_context(
            ctx,
            (
                "plan_only",
                "read_only",
                "inspect_only",
                "analysis_only",
                "no_mutation",
            ),
        ):
            if self._truthy_context(
                ctx,
                (
                    "plan_only",
                    "analysis_only",
                ),
            ):
                return self._decision(
                    self.MODE_PLAN,
                    reason=(
                        "The integration context explicitly requires "
                        "planning without execution."
                    ),
                    signals=signals["all"],
                    repository_inspection_allowed=True,
                )

            return self._decision(
                self.MODE_INSPECT,
                reason=(
                    "The integration context explicitly requires "
                    "read-only inspection."
                ),
                signals=signals["all"],
                repository_inspection_allowed=True,
            )

        # --------------------------------------------------------------
        # Explicit execution context
        # --------------------------------------------------------------

        if explicit_mode == self.MODE_EXECUTE:
            if not self.allow_execution:
                return self._decision(
                    self.MODE_PLAN,
                    reason=(
                        "Execution was requested, but this execution-mode "
                        "instance is configured to disallow execution."
                    ),
                    signals=signals["all"],
                    repository_inspection_allowed=True,
                    confidence=1.0,
                )

            return self._decision(
                self.MODE_EXECUTE,
                reason=(
                    "The request explicitly enters engineering execution "
                    "mode. Delivery actions remain independently gated."
                ),
                signals=signals["all"],
                repository_inspection_allowed=True,
                execution_allowed=True,
                mutation_allowed=True,
                file_write_allowed=True,
                confidence=1.0,
            )

        if explicit_mode == self.MODE_PLAN:
            return self._decision(
                self.MODE_PLAN,
                reason=(
                    "The request explicitly selects plan-only mode."
                ),
                signals=signals["all"],
                repository_inspection_allowed=True,
            )

        if explicit_mode == self.MODE_INSPECT:
            return self._decision(
                self.MODE_INSPECT,
                reason=(
                    "The request explicitly selects inspect-only mode."
                ),
                signals=signals["all"],
                repository_inspection_allowed=True,
            )

        # --------------------------------------------------------------
        # Delivery requests
        #
        # Delivery is not itself engineering implementation.
        # The delivery authorization gateway owns those actions.
        # We therefore keep execution mode non-mutating here.
        # --------------------------------------------------------------

        if signals["delivery"]:
            return self._decision(
                self.MODE_EXECUTE,
                reason=(
                    "A delivery operation was requested. Engineering "
                    "execution mode does not authorize delivery; GitHub, "
                    "merge, deployment, and rollback remain separately "
                    "authorization-gated."
                ),
                signals=signals["all"],
                repository_inspection_allowed=True,
                execution_allowed=False,
                mutation_allowed=False,
                file_write_allowed=False,
                authorization_required=True,
                confidence=1.0,
            )

        # --------------------------------------------------------------
        # Explicit planning language
        # --------------------------------------------------------------

        if signals["plan"]:
            return self._decision(
                self.MODE_PLAN,
                reason=(
                    "The request asks for planning/design rather than "
                    "implementation."
                ),
                signals=signals["all"],
                repository_inspection_allowed=True,
                confidence=1.0,
            )

        # --------------------------------------------------------------
        # Explicit inspection language
        # --------------------------------------------------------------

        if signals["inspect"] and not signals["execute"]:
            return self._decision(
                self.MODE_INSPECT,
                reason=(
                    "The request asks to inspect, analyze, review, or "
                    "explain the repository without requesting changes."
                ),
                signals=signals["all"],
                repository_inspection_allowed=True,
                confidence=1.0,
            )

        # --------------------------------------------------------------
        # Engineering implementation request
        # --------------------------------------------------------------

        if signals["execute"]:
            if not self.allow_execution:
                return self._decision(
                    self.MODE_PLAN,
                    reason=(
                        "The request appears executable, but execution "
                        "has been disabled for this policy instance."
                    ),
                    signals=signals["all"],
                    repository_inspection_allowed=True,
                )

            return self._decision(
                self.MODE_EXECUTE,
                reason=(
                    "The request explicitly asks ARIA to implement, "
                    "modify, fix, build, or otherwise perform engineering "
                    "work."
                ),
                signals=signals["all"],
                repository_inspection_allowed=True,
                execution_allowed=True,
                mutation_allowed=True,
                file_write_allowed=True,
                confidence=0.98,
            )

        # --------------------------------------------------------------
        # Research / ordinary answer
        # --------------------------------------------------------------

        if signals["research"]:
            return self._decision(
                self.MODE_ANSWER,
                reason=(
                    "The request is research/knowledge oriented and does "
                    "not require engineering execution."
                ),
                signals=signals["all"],
                repository_inspection_allowed=False,
                confidence=0.95,
            )

        return self._decision(
            self.default_mode,
            reason=(
                "No executable engineering intent was detected; the "
                "request remains in the normal answer/research pipeline."
            ),
            signals=signals["all"],
            repository_inspection_allowed=False,
            confidence=0.85,
        )

    def select(
        self,
        request: Any = "",
        *,
        query: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> EngineeringExecutionDecision:
        """Compatibility alias for ``determine``."""

        return self.determine(
            request,
            query=query,
            context=context,
        )

    def decide(
        self,
        request: Any = "",
        *,
        query: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> EngineeringExecutionDecision:
        """Compatibility alias for ``determine``."""

        return self.determine(
            request,
            query=query,
            context=context,
        )

    def resolve(
        self,
        request: Any = "",
        *,
        query: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> EngineeringExecutionDecision:
        """Compatibility alias for ``determine``."""

        return self.determine(
            request,
            query=query,
            context=context,
        )

    def mode_for(
        self,
        request: Any = "",
        *,
        query: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """Return only the canonical mode string."""

        return self.determine(
            request,
            query=query,
            context=context,
        ).mode

    def allows_execution(
        self,
        request: Any = "",
        *,
        query: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        """Return whether engineering implementation is allowed."""

        return bool(
            self.determine(
                request,
                query=query,
                context=context,
            ).execution_allowed
        )

    def is_read_only(
        self,
        request: Any = "",
        *,
        query: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        """Return whether the request is inspection/plan-only."""

        decision = self.determine(
            request,
            query=query,
            context=context,
        )

        return decision.mode in {
            self.MODE_INSPECT,
            self.MODE_PLAN,
        }

    def health(self) -> Dict[str, Any]:
        """Return deterministic health information."""

        return {
            "healthy": True,
            "version": self.VERSION,
            "default_mode": self.default_mode,
            "execution_enabled": self.allow_execution,
            "valid_modes": sorted(self.VALID_MODES),
            "side_effect_free": True,
            "delivery_authorization_separate": True,
        }

    def capabilities(self) -> Dict[str, Any]:
        """Return the policy capabilities exposed to the integration layer."""

        return {
            "answer_or_research": True,
            "inspect_only": True,
            "plan_only": True,
            "execute": bool(self.allow_execution),
            "repository_inspection": True,
            "file_mutation_policy": True,
            "commit_policy": True,
            "github_push_policy": True,
            "merge_policy": True,
            "deployment_policy": True,
            "rollback_policy": True,
            "delivery_authorization_required": True,
        }

    # ------------------------------------------------------------------
    # Signal extraction
    # ------------------------------------------------------------------

    def _collect_signals(
        self,
        text: str,
        context: Mapping[str, Any],
    ) -> Dict[str, Any]:
        normalized = self._normalize_text(text)

        prohibition = self._matches_any(
            normalized,
            self._NO_ACTION_PATTERNS,
        )

        plan = self._matches_any(
            normalized,
            self._PLAN_PATTERNS,
        )

        inspect = self._matches_any(
            normalized,
            self._INSPECT_PATTERNS,
        )

        execute = self._matches_any(
            normalized,
            self._EXECUTE_PATTERNS,
        )

        delivery = self._matches_any(
            normalized,
            self._DELIVERY_PATTERNS,
        )

        research = self._matches_any(
            normalized,
            self._RESEARCH_PATTERNS,
        )

        all_signals = []

        if prohibition:
            all_signals.append("explicit_no_action")

        if plan:
            all_signals.append("planning_language")

        if inspect:
            all_signals.append("inspection_language")

        if execute:
            all_signals.append("execution_language")

        if delivery:
            all_signals.append("delivery_language")

        if research:
            all_signals.append("research_language")

        # Context-derived signals are also preserved for diagnostics.
        if self._truthy_context(
            context,
            ("plan_only",),
        ):
            all_signals.append("context_plan_only")

        if self._truthy_context(
            context,
            ("inspect_only", "read_only"),
        ):
            all_signals.append("context_read_only")

        if self._truthy_context(
            context,
            ("no_mutation",),
        ):
            all_signals.append("context_no_mutation")

        return {
            "prohibition": prohibition,
            "plan": plan,
            "inspect": inspect,
            "execute": execute,
            "delivery": delivery,
            "research": research,
            "all": tuple(dict.fromkeys(all_signals)),
        }

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    @classmethod
    def _explicit_context_mode(
        cls,
        context: Mapping[str, Any],
    ) -> Optional[str]:
        for key in (
            "engineering_execution_mode",
            "execution_mode",
            "mode",
        ):
            value = context.get(key)

            if value is None:
                continue

            if isinstance(value, EngineeringExecutionDecision):
                return value.mode

            if isinstance(value, Mapping):
                value = value.get("mode")

            normalized = cls._normalize_mode(value)

            if normalized in cls.VALID_MODES:
                return normalized

        return None

    @staticmethod
    def _truthy_context(
        context: Mapping[str, Any],
        keys: Iterable[str],
    ) -> bool:
        for key in keys:
            value = context.get(key)

            if isinstance(value, str):
                if value.strip().lower() in {
                    "true",
                    "yes",
                    "1",
                    "on",
                }:
                    return True

            elif bool(value):
                return True

        return False

    # ------------------------------------------------------------------
    # Decision creation
    # ------------------------------------------------------------------

    def _decision(
        self,
        mode: str,
        *,
        reason: str,
        signals: Iterable[str],
        repository_inspection_allowed: bool = False,
        execution_allowed: bool = False,
        mutation_allowed: bool = False,
        file_write_allowed: bool = False,
        commit_allowed: bool = False,
        github_push_allowed: bool = False,
        merge_allowed: bool = False,
        deployment_allowed: bool = False,
        rollback_allowed: bool = False,
        authorization_required: bool = False,
        confidence: float = 1.0,
    ) -> EngineeringExecutionDecision:
        normalized_mode = self._normalize_mode(mode)

        if normalized_mode not in self.VALID_MODES:
            normalized_mode = self.MODE_ANSWER

        plan_only = normalized_mode == self.MODE_PLAN
        inspect_only = normalized_mode == self.MODE_INSPECT

        # Hard safety normalization.
        if plan_only or inspect_only:
            execution_allowed = False
            mutation_allowed = False
            file_write_allowed = False
            commit_allowed = False
            github_push_allowed = False
            merge_allowed = False
            deployment_allowed = False
            rollback_allowed = False

        # Execution itself never automatically authorizes delivery.
        if normalized_mode == self.MODE_EXECUTE:
            github_push_allowed = False
            merge_allowed = False
            deployment_allowed = False
            rollback_allowed = False

        return EngineeringExecutionDecision(
            mode=normalized_mode,
            plan_only=plan_only,
            inspect_only=inspect_only,
            execution_allowed=bool(execution_allowed),
            repository_inspection_allowed=bool(
                repository_inspection_allowed
            ),
            mutation_allowed=bool(mutation_allowed),
            file_write_allowed=bool(file_write_allowed),
            commit_allowed=bool(commit_allowed),
            github_push_allowed=bool(github_push_allowed),
            merge_allowed=bool(merge_allowed),
            deployment_allowed=bool(deployment_allowed),
            rollback_allowed=bool(rollback_allowed),
            authorization_required=bool(authorization_required),
            reason=str(reason or ""),
            signals=tuple(dict.fromkeys(str(x) for x in signals)),
            confidence=max(
                0.0,
                min(
                    1.0,
                    float(confidence),
                ),
            ),
        )

    # ------------------------------------------------------------------
    # Text normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(
        request: Any,
        *,
        query: Optional[str] = None,
    ) -> str:
        if query is not None:
            return str(query or "")

        if isinstance(request, str):
            return request

        if isinstance(request, Mapping):
            for key in (
                "query",
                "request",
                "text",
                "message",
                "content",
                "original_request",
            ):
                value = request.get(key)

                if value is not None:
                    return str(value)

            return str(request)

        for attribute in (
            "query",
            "request",
            "text",
            "message",
            "content",
            "original_request",
        ):
            value = getattr(request, attribute, None)

            if value is not None:
                return str(value)

        return str(request or "")

    @staticmethod
    def _normalize_text(value: Any) -> str:
        text = str(value or "").strip().lower()

        text = text.replace("’", "'")
        text = re.sub(r"\s+", " ", text)

        return text

    @staticmethod
    def _normalize_mode(value: Any) -> str:
        if value is None:
            return ""

        normalized = str(value).strip().lower()

        aliases = {
            "answer": EngineeringExecutionMode.MODE_ANSWER,
            "research": EngineeringExecutionMode.MODE_ANSWER,
            "knowledge": EngineeringExecutionMode.MODE_ANSWER,
            "inspect": EngineeringExecutionMode.MODE_INSPECT,
            "read": EngineeringExecutionMode.MODE_INSPECT,
            "readonly": EngineeringExecutionMode.MODE_INSPECT,
            "read_only": EngineeringExecutionMode.MODE_INSPECT,
            "analysis": EngineeringExecutionMode.MODE_INSPECT,
            "plan": EngineeringExecutionMode.MODE_PLAN,
            "planning": EngineeringExecutionMode.MODE_PLAN,
            "plan-only": EngineeringExecutionMode.MODE_PLAN,
            "plan_only": EngineeringExecutionMode.MODE_PLAN,
            "execute": EngineeringExecutionMode.MODE_EXECUTE,
            "execution": EngineeringExecutionMode.MODE_EXECUTE,
            "implement": EngineeringExecutionMode.MODE_EXECUTE,
        }

        return aliases.get(
            normalized,
            normalized,
        )

    @staticmethod
    def _matches_any(
        text: str,
        patterns: Iterable[str],
    ) -> bool:
        for pattern in patterns:
            try:
                if re.search(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                ):
                    return True
            except re.error:
                logger.warning(
                    "[EngineeringExecutionMode] Invalid pattern: %s",
                    pattern,
                )

        return False


# ----------------------------------------------------------------------
# Compatibility aliases
# ----------------------------------------------------------------------

EngineeringExecutionPolicy = EngineeringExecutionMode
ExecutionModeSelector = EngineeringExecutionMode


__all__ = [
    "EngineeringExecutionDecision",
    "EngineeringExecutionMode",
    "EngineeringExecutionPolicy",
    "ExecutionModeSelector",
]