from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from .contracts.engineering_requirement import (
    EngineeringPermission,
    EngineeringRequirement,
    PermissionScope,
    RequirementIntent,
)


logger = logging.getLogger("aria")


@dataclass(frozen=True)
class RequirementResolution:
    """
    Normalized result of authoritative requirement resolution.
    """

    success: bool
    requirement: EngineeringRequirement | None
    ready_for_planning: bool
    ambiguity_flags: tuple[str, ...] = ()
    clarification_questions: tuple[str, ...] = ()
    source: str = ""
    confidence: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "requirement": (
                self.requirement.to_dict()
                if self.requirement
                else None
            ),
            "ready_for_planning": (
                self.ready_for_planning
            ),
            "ambiguity_flags": list(
                self.ambiguity_flags
            ),
            "clarification_questions": list(
                self.clarification_questions
            ),
            "source": self.source,
            "confidence": self.confidence,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


class AuthoritativeEngineeringRequirement:
    """
    Authoritative requirement/intent boundary for ARIA engineering.

    Responsibilities:

        raw Telegram/user request
                    ↓
             requirement analysis
                    ↓
             normalized intent
                    ↓
          constraints / permissions
                    ↓
          acceptance criteria
                    ↓
        EngineeringRequirement
                    ↓
             planning boundary

    The legacy requirement intelligence service may still perform
    interpretation, but its result is normalized here before it
    becomes part of the authoritative engineering session.

    This class does NOT:
      - execute code
      - modify files
      - push GitHub
      - deploy
      - bypass authorization
    """

    def __init__(
        self,
        *,
        requirement_intelligence: Any | None = None,
        session: Any | None = None,
        evidence_recorder: Any | None = None,
    ) -> None:
        self.requirement_intelligence = (
            requirement_intelligence
        )
        self.session = session
        self.evidence_recorder = (
            evidence_recorder
        )

    # ============================================================
    # Public API
    # ============================================================

    async def resolve(
        self,
        raw_request: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> RequirementResolution:
        """
        Resolve a user requirement into the authoritative contract.
        """

        request = str(
            raw_request or ""
        ).strip()

        if not request:
            return RequirementResolution(
                success=False,
                requirement=None,
                ready_for_planning=False,
                source="authoritative_requirement",
                confidence=0.0,
                error=(
                    "Engineering requirement cannot be empty."
                ),
            )

        if self.requirement_intelligence is None:
            requirement = self._fallback_requirement(
                request,
                metadata=metadata,
            )

            result = RequirementResolution(
                success=True,
                requirement=requirement,
                ready_for_planning=True,
                source="fallback_normalizer",
                confidence=0.55,
                metadata={
                    **(
                        metadata
                        or {}
                    ),
                    "fallback": True,
                },
            )

            self._record_evidence(
                result
            )

            return result

        try:
            analyzed = await self._analyze(
                request
            )

        except Exception as exc:
            logger.exception(
                "[EngineeringRequirement] "
                "Requirement intelligence failed."
            )

            return RequirementResolution(
                success=False,
                requirement=None,
                ready_for_planning=False,
                source="requirement_intelligence",
                confidence=0.0,
                error=str(exc),
                metadata={
                    **(
                        metadata
                        or {}
                    ),
                },
            )

        result = self._normalize_analysis(
            request,
            analyzed,
            metadata=metadata,
        )

        self._record_evidence(
            result
        )

        return result

    async def analyze(
        self,
        raw_request: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> RequirementResolution:
        """
        Compatibility alias.
        """

        return await self.resolve(
            raw_request,
            metadata=metadata,
        )

    # ============================================================
    # Requirement intelligence dispatch
    # ============================================================

    async def _analyze(
        self,
        request: str,
    ) -> Any:
        service = (
            self.requirement_intelligence
        )

        methods = (
            "analyze",
            "resolve",
            "parse",
            "understand",
        )

        for method_name in methods:
            method = getattr(
                service,
                method_name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                lambda: method(request),
                lambda: method(
                    request_text=request
                ),
                lambda: method(
                    requirement_text=request
                ),
                lambda: method(
                    raw_request=request
                ),
            )

            for attempt in attempts:
                try:
                    value = attempt()

                    if inspect.isawaitable(
                        value
                    ):
                        value = await value

                    return value

                except TypeError:
                    continue

        raise RuntimeError(
            "Requirement intelligence service does not "
            "expose a supported analysis method."
        )

    # ============================================================
    # Normalization
    # ============================================================

    def _normalize_analysis(
        self,
        raw_request: str,
        analyzed: Any,
        *,
        metadata: dict[str, Any] | None,
    ) -> RequirementResolution:
        raw_requirement = self._get(
            analyzed,
            "requirement",
            analyzed,
        )

        intent_value = self._get(
            analyzed,
            "intent",
            self._get(
                raw_requirement,
                "intent",
                RequirementIntent.DEVELOP,
            ),
        )

        intent = self._normalize_intent(
            intent_value
        )

        goal = self._string(
            self._get(
                raw_requirement,
                "goal",
                self._get(
                    raw_requirement,
                    "objective",
                    raw_request,
                ),
            )
        )

        objective = self._string(
            self._get(
                raw_requirement,
                "objective",
                goal,
            )
        )

        constraints = self._string_tuple(
            self._get(
                raw_requirement,
                "constraints",
                (),
            )
        )

        acceptance_criteria = (
            self._string_tuple(
                self._get(
                    raw_requirement,
                    "acceptance_criteria",
                    self._get(
                        raw_requirement,
                        "acceptance",
                        (),
                    ),
                )
            )
        )

        requested_paths = (
            self._string_tuple(
                self._get(
                    raw_requirement,
                    "requested_paths",
                    self._get(
                        raw_requirement,
                        "target_paths",
                        (),
                    ),
                )
            )
        )

        protected_paths = (
            self._string_tuple(
                self._get(
                    raw_requirement,
                    "protected_paths",
                    (),
                )
            )
        )

        explicit_actions = (
            self._string_tuple(
                self._get(
                    raw_requirement,
                    "explicit_actions",
                    (),
                )
            )
        )

        forbidden_actions = (
            self._string_tuple(
                self._get(
                    raw_requirement,
                    "forbidden_actions",
                    (),
                )
            )
        )

        ambiguity_flags = (
            self._string_tuple(
                self._get(
                    analyzed,
                    "ambiguity_flags",
                    (),
                )
            )
        )

        clarification_questions = (
            self._string_tuple(
                self._get(
                    analyzed,
                    "clarification_questions",
                    (),
                )
            )
        )

        permission_scope = (
            self._normalize_permission_scope(
                raw_request,
                explicit_actions=explicit_actions,
                forbidden_actions=forbidden_actions,
            )
        )

        permissions = self._build_permissions(
            raw_request,
            permission_scope=permission_scope,
            explicit_actions=explicit_actions,
        )

        confidence = self._float(
            self._get(
                analyzed,
                "confidence",
                self._get(
                    raw_requirement,
                    "confidence",
                    0.75,
                ),
            ),
            default=0.75,
        )

        confidence = max(
            0.0,
            min(
                1.0,
                confidence,
            ),
        )

        ready_value = self._get(
            analyzed,
            "ready_for_planning",
            None,
        )

        if ready_value is None:
            ready_for_planning = (
                not ambiguity_flags
                and bool(goal)
            )
        else:
            ready_for_planning = bool(
                ready_value
            )

        requirement = (
            EngineeringRequirement(
                raw_request=raw_request,
                intent=intent,
                goal=goal,
                objective=objective,
                constraints=constraints,
                acceptance_criteria=(
                    acceptance_criteria
                ),
                requested_paths=requested_paths,
                protected_paths=protected_paths,
                permissions=permissions,
                explicit_actions=(
                    explicit_actions
                ),
                forbidden_actions=(
                    forbidden_actions
                ),
                ambiguity_notes=(
                    ambiguity_flags
                ),
                confidence=confidence,
                metadata={
                    **(
                        metadata
                        or {}
                    ),
                    "authority": (
                        "authoritative_requirement"
                    ),
                    "source": (
                        "requirement_intelligence"
                    ),
                },
            )
        )

        return RequirementResolution(
            success=True,
            requirement=requirement,
            ready_for_planning=(
                ready_for_planning
            ),
            ambiguity_flags=(
                ambiguity_flags
            ),
            clarification_questions=(
                clarification_questions
            ),
            source=(
                "requirement_intelligence"
            ),
            confidence=confidence,
            metadata={
                **(
                    metadata
                    or {}
                ),
            },
        )

    # ============================================================
    # Fallback
    # ============================================================

    def _fallback_requirement(
        self,
        raw_request: str,
        *,
        metadata: dict[str, Any] | None,
    ) -> EngineeringRequirement:
        """
        Conservative fallback when the legacy analyzer is absent.

        The fallback never invents permissions.
        """

        lower = raw_request.lower()

        forbidden: list[str] = []

        if (
            "do not push" in lower
            or "don't push" in lower
        ):
            forbidden.append(
                "push_to_github"
            )

        if (
            "do not deploy" in lower
            or "don't deploy" in lower
        ):
            forbidden.append(
                "deploy"
            )

        if (
            "do not modify production"
            in lower
            or "don't modify production"
            in lower
        ):
            forbidden.append(
                "modify_production"
            )

        explicit: list[str] = []

        if "push to github" in lower:
            explicit.append(
                "push_to_github"
            )

        if "deploy" in lower:
            explicit.append(
                "deploy"
            )

        permissions = self._build_permissions(
            raw_request,
            permission_scope=(
                PermissionScope.WORKSPACE
            ),
            explicit_actions=(
                tuple(explicit)
            ),
        )

        return EngineeringRequirement(
            raw_request=raw_request,
            intent=RequirementIntent.DEVELOP,
            goal=raw_request,
            objective=raw_request,
            constraints=(
                "Work only inside an isolated engineering workspace.",
            ),
            acceptance_criteria=(
                "Requirement is implemented.",
                "Relevant verification passes.",
            ),
            requested_paths=(),
            protected_paths=(),
            permissions=permissions,
            explicit_actions=tuple(
                explicit
            ),
            forbidden_actions=tuple(
                forbidden
            ),
            ambiguity_notes=(),
            confidence=0.55,
            metadata={
                **(
                    metadata
                    or {}
                ),
                "fallback": True,
            },
        )

    # ============================================================
    # Intent normalization
    # ============================================================

    @staticmethod
    def _normalize_intent(
        value: Any,
    ) -> RequirementIntent:
        if isinstance(
            value,
            RequirementIntent,
        ):
            return value

        text = str(
            value or ""
        ).strip().lower()

        aliases = {
            "develop": RequirementIntent.DEVELOP,
            "development": RequirementIntent.DEVELOP,
            "build": RequirementIntent.DEVELOP,
            "implement": RequirementIntent.DEVELOP,
            "code": RequirementIntent.DEVELOP,
            "fix": RequirementIntent.FIX,
            "bugfix": RequirementIntent.FIX,
            "repair": RequirementIntent.FIX,
            "refactor": RequirementIntent.REFACTOR,
            "test": RequirementIntent.TEST,
            "testing": RequirementIntent.TEST,
            "research": RequirementIntent.RESEARCH,
            "investigate": RequirementIntent.RESEARCH,
            "analyze": RequirementIntent.RESEARCH,
            "self_upgrade": RequirementIntent.SELF_UPGRADE,
            "self-upgrade": RequirementIntent.SELF_UPGRADE,
            "upgrade": RequirementIntent.SELF_UPGRADE,
        }

        return aliases.get(
            text,
            RequirementIntent.DEVELOP,
        )

    # ============================================================
    # Permissions
    # ============================================================

    @staticmethod
    def _normalize_permission_scope(
        raw_request: str,
        *,
        explicit_actions: tuple[str, ...],
        forbidden_actions: tuple[str, ...],
    ) -> PermissionScope:
        lower = raw_request.lower()

        if (
            "production" in lower
            and (
                "modify production"
                in lower
                or "change production"
                in lower
            )
        ):
            return PermissionScope.PRODUCTION

        if (
            "github" in lower
            and (
                "push" in lower
                or "commit" in lower
                or "pull request" in lower
            )
        ):
            return PermissionScope.REPOSITORY

        if (
            "deploy" in lower
            or "deployment" in lower
        ):
            return PermissionScope.DEPLOYMENT

        if (
            "self-upgrade" in lower
            or "self upgrade" in lower
        ):
            return PermissionScope.SELF_UPGRADE

        return PermissionScope.WORKSPACE

    @staticmethod
    def _build_permissions(
        raw_request: str,
        *,
        permission_scope: PermissionScope,
        explicit_actions: tuple[str, ...],
    ) -> tuple[EngineeringPermission, ...]:
        permissions: list[
            EngineeringPermission
        ] = []

        permissions.append(
            EngineeringPermission(
                action="workspace_development",
                scope=PermissionScope.WORKSPACE,
                authorized=True,
                explicit=False,
                source="engineering_requirement",
            )
        )

        lower = raw_request.lower()

        github_explicit = (
            "push to github" in lower
            or "push github" in lower
            or "commit and push" in lower
        )

        if github_explicit:
            permissions.append(
                EngineeringPermission(
                    action="push_to_github",
                    scope=(
                        PermissionScope.REPOSITORY
                    ),
                    authorized=True,
                    explicit=True,
                    source="user_request",
                )
            )

        deploy_explicit = (
            "deploy" in lower
            and (
                "deploy it" in lower
                or "deploy this" in lower
                or "deploy to" in lower
            )
        )

        if deploy_explicit:
            permissions.append(
                EngineeringPermission(
                    action="deploy",
                    scope=(
                        PermissionScope.DEPLOYMENT
                    ),
                    authorized=True,
                    explicit=True,
                    source="user_request",
                )
            )

        self_upgrade_explicit = (
            "self-upgrade" in lower
            or "self upgrade" in lower
            or "upgrade yourself" in lower
        )

        if self_upgrade_explicit:
            permissions.append(
                EngineeringPermission(
                    action="self_upgrade",
                    scope=(
                        PermissionScope.SELF_UPGRADE
                    ),
                    authorized=True,
                    explicit=True,
                    source="user_request",
                )
            )

        return tuple(
            permissions
        )

    # ============================================================
    # Generic compatibility helpers
    # ============================================================

    @staticmethod
    def _get(
        obj: Any,
        name: str,
        default: Any = None,
    ) -> Any:
        if obj is None:
            return default

        if isinstance(
            obj,
            dict,
        ):
            return obj.get(
                name,
                default,
            )

        return getattr(
            obj,
            name,
            default,
        )

    @staticmethod
    def _string(
        value: Any,
    ) -> str:
        if value is None:
            return ""

        return str(
            value
        ).strip()

    @staticmethod
    def _string_tuple(
        value: Any,
    ) -> tuple[str, ...]:
        if value is None:
            return ()

        if isinstance(
            value,
            str,
        ):
            value = [
                value
            ]

        elif not isinstance(
            value,
            Iterable,
        ):
            value = [
                value
            ]

        result: list[str] = []

        for item in value:
            text = str(
                item
            ).strip()

            if text:
                result.append(
                    text
                )

        return tuple(
            result
        )

    @staticmethod
    def _float(
        value: Any,
        *,
        default: float,
    ) -> float:
        try:
            return float(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return default

    # ============================================================
    # Evidence
    # ============================================================

    def _record_evidence(
        self,
        result: RequirementResolution,
    ) -> None:
        recorder = (
            self.evidence_recorder
        )

        if recorder is None:
            return

        try:
            recorder.record(
                kind="requirement",
                summary=(
                    "Engineering requirement resolved."
                ),
                details=result.to_dict(),
                source=(
                    "authoritative_engineering_requirement"
                ),
            )

        except Exception:
            logger.exception(
                "[EngineeringRequirement] "
                "Could not record requirement evidence."
            )

    # ============================================================
    # Session integration
    # ============================================================

    def attach_session(
        self,
        session: Any,
    ) -> None:
        self.session = session

    def attach_evidence_recorder(
        self,
        recorder: Any,
    ) -> None:
        self.evidence_recorder = (
            recorder
        )

    def health(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "requirement_intelligence": (
                self.requirement_intelligence
                is not None
            ),
            "session_attached": (
                self.session
                is not None
            ),
            "evidence_recorder_attached": (
                self.evidence_recorder
                is not None
            ),
        }