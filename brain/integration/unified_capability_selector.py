"""Canonical, side-effect-free capability selection for ARIA.

This module is the canonical capability-routing decision layer.

IMPORTANT:
    - It NEVER executes a capability.
    - It NEVER mutates files, repositories, GitHub, deployment state, or memory.
    - It gives high-priority request classes deterministic routes before
      generic Tool/Skill/Action matching.
    - Existing managers remain the owners of actual execution.
    - Delivery authorization remains owned by MasterDeliveryAuthorization.
    - Autonomous engineering execution remains owned by
      AutonomousEngineeringLifecycle.
    - Multimodal execution remains owned by MultimodalCapabilityGateway.

The selector therefore acts as a routing contract between the JARVIS request
model and ARIA's existing capability owners.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


# ---------------------------------------------------------------------------
# Capability candidate
# ---------------------------------------------------------------------------


@dataclass
class CapabilityCandidate:
    """A ranked capability candidate.

    This object describes a possible capability owner. It does not execute it.
    """

    kind: str
    name: str
    score: float
    description: str = ""
    permission_level: str = ""
    available: bool = True
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "score": round(float(self.score), 4),
            "description": self.description,
            "permission_level": self.permission_level,
            "available": bool(self.available),
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Canonical selection result
# ---------------------------------------------------------------------------


@dataclass
class CapabilitySelection:
    """Canonical routing decision returned by the selector.

    `route` identifies the high-level owner that should handle the request.

    Examples:
        answer
        research
        memory
        tool
        action
        multimodal
        engineering
        delivery
        automation
        document
        vision
        voice
        computer
        inspect_only
        plan_only
    """

    request: str

    primary: Optional[CapabilityCandidate] = None
    candidates: List[CapabilityCandidate] = field(default_factory=list)

    route: str = "answer"
    owner: str = "llm"

    execution_allowed: bool = True
    read_only: bool = False
    mutation_allowed: bool = False
    authorization_required: bool = False

    reason: str = ""
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request,
            "primary": (
                self.primary.to_dict()
                if self.primary is not None
                else None
            ),
            "candidates": [
                item.to_dict()
                for item in self.candidates
            ],
            "route": self.route,
            "owner": self.owner,
            "execution_allowed": bool(self.execution_allowed),
            "read_only": bool(self.read_only),
            "mutation_allowed": bool(self.mutation_allowed),
            "authorization_required": bool(
                self.authorization_required
            ),
            "reason": self.reason,
            "confidence": round(float(self.confidence), 4),
        }


# ---------------------------------------------------------------------------
# Canonical selector
# ---------------------------------------------------------------------------


class UnifiedCapabilitySelector:
    """Canonical, deterministic capability-selection layer.

    This class decides WHICH existing ARIA component should own a request.

    It does not execute the selected capability.
    """

    VERSION = "ARIA-UNIFIED-CAPABILITY-SELECTOR-20261006"

    DEFAULT_THRESHOLD = 0.30
    MAX_CANDIDATES = 12

    # ------------------------------------------------------------------
    # High-priority request markers
    # ------------------------------------------------------------------

    _DELIVERY_PATTERNS = (
        r"\bpush\b.*\b(?:github|git)\b",
        r"\b(?:github|git)\b.*\bpush\b",
        r"\bdeploy\b",
        r"\bdeployment\b",
        r"\brollback\b",
        r"\broll\s+back\b",
        r"\bmerge\b.*\b(?:pr|pull request)\b",
        r"\bcreate\b.*\b(?:pull request|pr)\b",
        r"\bcommit\b.*\b(?:changes|code|files)\b",
        r"\bcreate\b.*\bcommit\b",
        r"\bproduction\b.*\b(?:write|deploy|change|update)\b",
    )

    _ENGINEERING_PATTERNS = (
        r"\bimplement\b",
        r"\bbuild\b",
        r"\bdevelop\b",
        r"\brefactor\b",
        r"\bfix\b",
        r"\bdebug\b",
        r"\bmodify\b.*\b(?:file|code|project)\b",
        r"\bchange\b.*\b(?:file|code|project)\b",
        r"\bcreate\b.*\b(?:file|module|service|feature|system)\b",
        r"\bwrite\b.*\b(?:code|file|module)\b",
        r"\badd\b.*\b(?:feature|functionality|module|service)\b",
        r"\bremove\b.*\b(?:feature|code|module)\b",
        r"\bupdate\b.*\b(?:code|file|project|repository)\b",
        r"\bengineering\b",
        r"\bautonomous\b.*\b(?:engineer|engineering)\b",
        r"\bdevelop\b.*\b(?:aria|project|repository)\b",
    )

    _REPOSITORY_PATTERNS = (
        r"\brepository\b",
        r"\brepo\b",
        r"\bgithub\b.*\b(?:inspect|architecture|tree|files)\b",
        r"\bproject\b.*\b(?:architecture|structure|files)\b",
        r"\binspect\b.*\b(?:code|repository|repo|project)\b",
        r"\banaly[sz]e\b.*\b(?:repository|repo|project)\b",
        r"\barchitecture\b.*\b(?:repository|repo|project)\b",
    )

    _RESEARCH_PATTERNS = (
        r"\bresearch\b",
        r"\blook\s+up\b",
        r"\bsearch\b.*\b(?:web|internet|online)\b",
        r"\blatest\b",
        r"\bcurrent\b.*\b(?:information|news|version|status)\b",
        r"\bfind\b.*\bonline\b",
        r"\bwhat\s+is\s+the\s+latest\b",
    )

    _MEMORY_PATTERNS = (
        r"\bremember\b",
        r"\bforget\b",
        r"\bwhat\s+do\s+you\s+remember\b",
        r"\brecall\b",
        r"\bmy\s+(?:preferences|memory|details)\b",
    )

    _DOCUMENT_PATTERNS = (
        r"\bdocument\b",
        r"\bpdf\b",
        r"\bdocx\b",
        r"\bspreadsheet\b",
        r"\bexcel\b",
        r"\bfile\b.*\b(?:read|summarize|analy[sz]e)\b",
        r"\bsummarize\b.*\bdocument\b",
    )

    _VISION_PATTERNS = (
        r"\bimage\b",
        r"\bphoto\b",
        r"\bpicture\b",
        r"\bscreenshot\b",
        r"\blook\s+at\s+this\b",
        r"\banaly[sz]e\b.*\bimage\b",
    )

    _VOICE_PATTERNS = (
        r"\bvoice\b",
        r"\baudio\b",
        r"\bspeech\b",
        r"\btranscrib",
        r"\bspeak\b",
        r"\bsynthesize\b.*\bspeech\b",
    )

    _COMPUTER_PATTERNS = (
        r"\bcontrol\b.*\bcomputer\b",
        r"\buse\b.*\bcomputer\b",
        r"\bclick\b.*\b(?:button|screen)\b",
        r"\btype\b.*\b(?:screen|browser)\b",
        r"\bopen\b.*\b(?:browser|application)\b",
    )

    _AUTOMATION_PATTERNS = (
        r"\bremind\b",
        r"\bschedule\b",
        r"\brecurring\b",
        r"\bevery\s+(?:day|week|hour|month)\b",
        r"\bnotify\s+me\b",
        r"\bautomate\b",
        r"\bmonitor\b.*\b(?:condition|change|status)\b",
    )

    _TOOL_PATTERNS = (
        r"\bcalculate\b",
        r"\bconvert\b",
        r"\bsearch\b",
        r"\bfetch\b",
        r"\blookup\b",
    )

    # ------------------------------------------------------------------
    # Read-only markers
    # ------------------------------------------------------------------

    _READ_ONLY = (
        "do not modify",
        "don't modify",
        "dont modify",
        "do not change",
        "don't change",
        "dont change",
        "do not edit",
        "don't edit",
        "do not write",
        "don't write",
        "do not create",
        "don't create",
        "do not delete",
        "don't delete",
        "do not implement",
        "don't implement",
        "do not execute",
        "don't execute",
        "without modifying",
        "without changing",
        "without editing",
        "without writing",
        "without creating",
        "without executing",
        "read only",
        "read-only",
        "inspect only",
        "inspect-only",
        "plan only",
        "plan-only",
        "planning only",
        "explain only",
        "no changes",
        "no modification",
        "no implementation",
    )

    _PLAN_ONLY = (
        "plan how",
        "plan for",
        "give me a plan",
        "implementation plan",
        "architecture plan",
        "design plan",
        "planning only",
        "plan only",
        "phases only",
        "steps only",
        "explain the architecture",
        "explain the implementation",
        "what should we do",
        "how would you implement",
        "how should we implement",
    )

    def __init__(
        self,
        *,
        skill_manager: Any = None,
        tool_manager: Any = None,
        action_manager: Any = None,
        agent_manager: Any = None,
        plugin_manager: Any = None,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self.skill_manager = skill_manager
        self.tool_manager = tool_manager
        self.action_manager = action_manager
        self.agent_manager = agent_manager
        self.plugin_manager = plugin_manager

        try:
            self.threshold = max(
                0.0,
                min(1.0, float(threshold)),
            )
        except (TypeError, ValueError):
            self.threshold = self.DEFAULT_THRESHOLD

    # ------------------------------------------------------------------
    # Basic helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _text(value: Any) -> str:
        return re.sub(
            r"\s+",
            " ",
            str(value or "").strip(),
        ).lower()

    @staticmethod
    def _matches(
        text: str,
        patterns: tuple[str, ...],
    ) -> bool:
        for pattern in patterns:
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False

    @staticmethod
    def _token_score(
        query: str,
        name: str,
        description: str,
    ) -> float:
        query_tokens = set(
            re.findall(
                r"[a-z0-9_+-]{3,}",
                query.lower(),
            )
        )

        if not query_tokens:
            return 0.0

        name_tokens = set(
            re.findall(
                r"[a-z0-9_+-]{3,}",
                name.lower(),
            )
        )

        description_tokens = set(
            re.findall(
                r"[a-z0-9_+-]{3,}",
                description.lower(),
            )
        )

        score = 0.0

        if name_tokens & query_tokens:
            score += 0.65

        overlap = len(
            query_tokens & description_tokens
        )

        if overlap:
            score += min(
                0.30,
                overlap * 0.08,
            )

        if name and name.lower() in query.lower():
            score += 0.20

        return min(1.0, score)

    def _read_only(
        self,
        query: str,
        context: Mapping[str, Any],
    ) -> bool:
        text = self._text(query)

        if self._matches(
            text,
            self._READ_ONLY,
        ):
            return True

        if bool(context.get("read_only")):
            return True

        if bool(context.get("plan_only")):
            return True

        execution_mode = context.get(
            "execution_mode"
        )

        if isinstance(execution_mode, Mapping):
            if bool(
                execution_mode.get("plan_only")
            ):
                return True

            if execution_mode.get("mode") in {
                "plan_only",
                "inspect_only",
            }:
                return True

        return False

    def _plan_only(
        self,
        query: str,
        context: Mapping[str, Any],
    ) -> bool:
        text = self._text(query)

        if self._matches(
            text,
            self._PLAN_ONLY,
        ):
            return True

        if bool(context.get("plan_only")):
            return True

        execution_mode = context.get(
            "execution_mode"
        )

        if isinstance(execution_mode, Mapping):
            return execution_mode.get(
                "mode"
            ) == "plan_only"

        return False

    # ------------------------------------------------------------------
    # Canonical route classification
    # ------------------------------------------------------------------

    def _canonical_route(
        self,
        query: str,
        context: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Determine the authoritative high-level route.

        Priority is intentional:

            delivery
            engineering
            repository
            multimodal
            memory
            automation
            research
            tool
            answer

        This prevents generic capability matching from hijacking high-risk
        or specialized requests.
        """

        text = self._text(query)

        read_only = self._read_only(
            query,
            context,
        )

        plan_only = self._plan_only(
            query,
            context,
        )

        # --------------------------------------------------------------
        # Delivery has the highest priority.
        # --------------------------------------------------------------

        if self._matches(
            text,
            self._DELIVERY_PATTERNS,
        ):
            return {
                "route": "delivery",
                "owner": "master_delivery_authorization",
                "reason": (
                    "Delivery operation detected. "
                    "Master authorization is required "
                    "before any GitHub, merge, deployment, "
                    "commit, or rollback operation."
                ),
                "confidence": 1.0,
                "execution_allowed": False,
                "read_only": False,
                "mutation_allowed": False,
                "authorization_required": True,
            }

        # --------------------------------------------------------------
        # Engineering.
        # --------------------------------------------------------------

        if self._matches(
            text,
            self._ENGINEERING_PATTERNS,
        ):
            if plan_only or read_only:
                return {
                    "route": "plan_only",
                    "owner": "autonomous_engineering_lifecycle",
                    "reason": (
                        "Engineering request explicitly constrained "
                        "to planning/inspection without mutation."
                    ),
                    "confidence": 1.0,
                    "execution_allowed": False,
                    "read_only": True,
                    "mutation_allowed": False,
                    "authorization_required": False,
                }

            return {
                "route": "engineering",
                "owner": "autonomous_engineering_lifecycle",
                "reason": (
                    "Engineering request detected. "
                    "Canonical autonomous engineering lifecycle "
                    "must own execution."
                ),
                "confidence": 1.0,
                "execution_allowed": True,
                "read_only": False,
                "mutation_allowed": True,
                "authorization_required": False,
            }

        # --------------------------------------------------------------
        # Repository inspection / architecture.
        # --------------------------------------------------------------

        if self._matches(
            text,
            self._REPOSITORY_PATTERNS,
        ):
            return {
                "route": (
                    "inspect_only"
                    if read_only or plan_only
                    else "repository"
                ),
                "owner": "repository_intelligence",
                "reason": (
                    "Repository/project intelligence request detected. "
                    "Repository evidence should be collected before "
                    "architecture or implementation conclusions."
                ),
                "confidence": 1.0,
                "execution_allowed": False,
                "read_only": True,
                "mutation_allowed": False,
                "authorization_required": False,
            }

        # --------------------------------------------------------------
        # Multimodal.
        # --------------------------------------------------------------

        if self._matches(
            text,
            self._COMPUTER_PATTERNS,
        ):
            return {
                "route": "computer",
                "owner": "multimodal_capability_gateway",
                "reason": (
                    "Computer-control request detected. "
                    "Explicit computer-control enablement remains required."
                ),
                "confidence": 1.0,
                "execution_allowed": not read_only,
                "read_only": read_only,
                "mutation_allowed": not read_only,
                "authorization_required": False,
            }

        if self._matches(
            text,
            self._VISION_PATTERNS,
        ):
            return {
                "route": "vision",
                "owner": "multimodal_capability_gateway",
                "reason": (
                    "Vision/image request detected."
                ),
                "confidence": 1.0,
                "execution_allowed": False,
                "read_only": True,
                "mutation_allowed": False,
                "authorization_required": False,
            }

        if self._matches(
            text,
            self._DOCUMENT_PATTERNS,
        ):
            return {
                "route": "document",
                "owner": "multimodal_capability_gateway",
                "reason": (
                    "Document-processing request detected."
                ),
                "confidence": 1.0,
                "execution_allowed": False,
                "read_only": True,
                "mutation_allowed": False,
                "authorization_required": False,
            }

        if self._matches(
            text,
            self._VOICE_PATTERNS,
        ):
            return {
                "route": "voice",
                "owner": "multimodal_capability_gateway",
                "reason": (
                    "Voice/audio request detected."
                ),
                "confidence": 1.0,
                "execution_allowed": False,
                "read_only": True,
                "mutation_allowed": False,
                "authorization_required": False,
            }

        # --------------------------------------------------------------
        # Memory.
        # --------------------------------------------------------------

        if self._matches(
            text,
            self._MEMORY_PATTERNS,
        ):
            return {
                "route": "memory",
                "owner": "jarvis_memory_system",
                "reason": (
                    "Explicit memory operation detected."
                ),
                "confidence": 1.0,
                "execution_allowed": False,
                "read_only": True,
                "mutation_allowed": False,
                "authorization_required": False,
            }

        # --------------------------------------------------------------
        # Automation.
        # --------------------------------------------------------------

        if self._matches(
            text,
            self._AUTOMATION_PATTERNS,
        ):
            return {
                "route": "automation",
                "owner": "scheduler",
                "reason": (
                    "Scheduling/automation request detected."
                ),
                "confidence": 1.0,
                "execution_allowed": not read_only,
                "read_only": read_only,
                "mutation_allowed": not read_only,
                "authorization_required": False,
            }

        # --------------------------------------------------------------
        # Research.
        # --------------------------------------------------------------

        if self._matches(
            text,
            self._RESEARCH_PATTERNS,
        ):
            return {
                "route": "research",
                "owner": "search",
                "reason": (
                    "Research/current-information request detected."
                ),
                "confidence": 1.0,
                "execution_allowed": False,
                "read_only": True,
                "mutation_allowed": False,
                "authorization_required": False,
            }

        # --------------------------------------------------------------
        # Generic tool request.
        # --------------------------------------------------------------

        if self._matches(
            text,
            self._TOOL_PATTERNS,
        ):
            return {
                "route": "tool",
                "owner": "tool_manager",
                "reason": (
                    "Generic tool-capability request detected."
                ),
                "confidence": 0.80,
                "execution_allowed": not read_only,
                "read_only": read_only,
                "mutation_allowed": False,
                "authorization_required": False,
            }

        # --------------------------------------------------------------
        # Normal conversational answer.
        # --------------------------------------------------------------

        return {
            "route": "answer",
            "owner": "llm",
            "reason": (
                "No specialized canonical route detected; "
                "normal answer/reasoning path may handle the request."
            ),
            "confidence": 0.50,
            "execution_allowed": False,
            "read_only": True,
            "mutation_allowed": False,
            "authorization_required": False,
        }

    # ------------------------------------------------------------------
    # Capability-manager discovery
    # ------------------------------------------------------------------

    async def _collect_manager_candidates(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> List[CapabilityCandidate]:
        candidates: List[CapabilityCandidate] = []

        # --------------------------------------------------------------
        # ToolManager
        # --------------------------------------------------------------

        if (
            self.tool_manager is not None
            and hasattr(
                self.tool_manager,
                "select_tool",
            )
        ):
            try:
                tool = await self.tool_manager.select_tool(
                    query,
                    context,
                )

                if tool is not None:
                    name = str(
                        getattr(
                            tool,
                            "name",
                            "",
                        )
                    ).strip()

                    if name:
                        description = str(
                            getattr(
                                tool,
                                "description",
                                "",
                            )
                            or ""
                        )

                        candidates.append(
                            CapabilityCandidate(
                                kind="tool",
                                name=name,
                                score=0.95,
                                description=description,
                                permission_level=str(
                                    getattr(
                                        tool,
                                        "permission_level",
                                        "",
                                    )
                                ),
                                reason=(
                                    "ToolManager capability "
                                    "selection."
                                ),
                            )
                        )

            except Exception:
                # Capability discovery is non-fatal.
                pass

        # --------------------------------------------------------------
        # SkillManager
        # --------------------------------------------------------------

        if (
            self.skill_manager is not None
            and hasattr(
                self.skill_manager,
                "find_candidates",
            )
        ):
            try:
                skills = await self.skill_manager.find_candidates(
                    query,
                    context,
                    minimum_confidence=self.threshold,
                )

                if skills:
                    for item in skills[
                        : self.MAX_CANDIDATES
                    ]:
                        if not isinstance(
                            item,
                            Mapping,
                        ):
                            continue

                        skill = item.get("skill")

                        name = str(
                            item.get("name")
                            or getattr(
                                skill,
                                "name",
                                "",
                            )
                        ).strip()

                        if not name:
                            continue

                        try:
                            confidence = float(
                                item.get(
                                    "confidence",
                                    0.0,
                                )
                            )
                        except (
                            TypeError,
                            ValueError,
                        ):
                            confidence = 0.0

                        candidates.append(
                            CapabilityCandidate(
                                kind="skill",
                                name=name,
                                score=confidence,
                                description=str(
                                    getattr(
                                        skill,
                                        "description",
                                        "",
                                    )
                                    or ""
                                ),
                                permission_level=str(
                                    getattr(
                                        skill,
                                        "permission_level",
                                        "",
                                    )
                                ),
                                reason=(
                                    "SkillManager capability "
                                    "confidence."
                                ),
                            )
                        )

            except Exception:
                # Capability discovery is non-fatal.
                pass

        # --------------------------------------------------------------
        # AgentManager
        # --------------------------------------------------------------

        if (
            self.agent_manager is not None
            and hasattr(
                self.agent_manager,
                "select_agent",
            )
        ):
            try:
                selected = (
                    await self.agent_manager.select_agent(
                        query,
                        context,
                    )
                )

                agent = None
                score = 0.0

                if (
                    isinstance(
                        selected,
                        tuple,
                    )
                    and len(selected) >= 2
                ):
                    agent = selected[0]
                    score = float(
                        selected[1] or 0.0
                    )

                elif selected is not None:
                    agent = selected
                    score = 0.50

                if (
                    agent is not None
                    and score >= self.threshold
                ):
                    name = str(
                        getattr(
                            agent,
                            "name",
                            "",
                        )
                    ).strip()

                    if name:
                        candidates.append(
                            CapabilityCandidate(
                                kind="agent",
                                name=name,
                                score=score,
                                description=str(
                                    getattr(
                                        agent,
                                        "description",
                                        "",
                                    )
                                    or ""
                                ),
                                permission_level=str(
                                    getattr(
                                        agent,
                                        "permission_level",
                                        "",
                                    )
                                ),
                                reason=(
                                    "AgentManager capability "
                                    "confidence."
                                ),
                            )
                        )

            except Exception:
                # Capability discovery is non-fatal.
                pass

        # --------------------------------------------------------------
        # ActionManager
        # --------------------------------------------------------------

        if self.action_manager is not None:
            actions = getattr(
                self.action_manager,
                "actions",
                {},
            )

            if isinstance(
                actions,
                Mapping,
            ):
                for name, action in actions.items():
                    description = str(
                        getattr(
                            action,
                            "description",
                            "",
                        )
                        or ""
                    )

                    score = self._token_score(
                        query,
                        str(name),
                        description,
                    )

                    if score < self.threshold:
                        continue

                    candidates.append(
                        CapabilityCandidate(
                            kind="action",
                            name=str(name),
                            score=score,
                            description=description,
                            permission_level=str(
                                getattr(
                                    action,
                                    "permission_level",
                                    "confirm",
                                )
                            ),
                            reason=(
                                "Action capability metadata "
                                "match."
                            ),
                        )
                    )

        # --------------------------------------------------------------
        # PluginManager
        # --------------------------------------------------------------

        if self.plugin_manager is not None:
            plugins = getattr(
                self.plugin_manager,
                "plugins",
                {},
            )

            if isinstance(
                plugins,
                Mapping,
            ):
                for plugin_id, plugin in plugins.items():
                    manifest = getattr(
                        plugin,
                        "manifest",
                        None,
                    )

                    capabilities = list(
                        getattr(
                            manifest,
                            "capabilities",
                            [],
                        )
                        or []
                    )

                    description = " ".join(
                        str(item)
                        for item in capabilities
                    )

                    score = self._token_score(
                        query,
                        str(plugin_id),
                        description,
                    )

                    state = str(
                        getattr(
                            plugin,
                            "state",
                            "unknown",
                        )
                    ).lower()

                    if (
                        score < self.threshold
                        or state
                        in {
                            "disabled",
                            "failed",
                        }
                    ):
                        continue

                    candidates.append(
                        CapabilityCandidate(
                            kind="plugin",
                            name=str(plugin_id),
                            score=score,
                            description=description,
                            available=True,
                            reason=(
                                "Plugin capability metadata "
                                "match."
                            ),
                        )
                    )

        return candidates

    # ------------------------------------------------------------------
    # Public canonical selection
    # ------------------------------------------------------------------

    async def select(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CapabilitySelection:
        """Return the canonical routing decision.

        No execution occurs here.
        """

        context = dict(context or {})
        request = str(query or "")

        route = self._canonical_route(
            request,
            context,
        )

        selection = CapabilitySelection(
            request=request,
            route=str(
                route.get(
                    "route",
                    "answer",
                )
            ),
            owner=str(
                route.get(
                    "owner",
                    "llm",
                )
            ),
            execution_allowed=bool(
                route.get(
                    "execution_allowed",
                    False,
                )
            ),
            read_only=bool(
                route.get(
                    "read_only",
                    True,
                )
            ),
            mutation_allowed=bool(
                route.get(
                    "mutation_allowed",
                    False,
                )
            ),
            authorization_required=bool(
                route.get(
                    "authorization_required",
                    False,
                )
            ),
            reason=str(
                route.get(
                    "reason",
                    "",
                )
            ),
            confidence=float(
                route.get(
                    "confidence",
                    0.0,
                )
            ),
        )

        # --------------------------------------------------------------
        # High-priority canonical routes must not be overridden by
        # generic capability matching.
        # --------------------------------------------------------------

        protected_routes = {
            "delivery",
            "engineering",
            "plan_only",
            "inspect_only",
            "repository",
            "computer",
            "vision",
            "document",
            "voice",
            "memory",
            "automation",
            "research",
        }

        if selection.route in protected_routes:
            manager_candidates = (
                await self._collect_manager_candidates(
                    request,
                    context,
                )
            )

            manager_candidates.sort(
                key=lambda item: (
                    -item.score,
                    item.kind,
                    item.name,
                )
            )

            selection.candidates = (
                manager_candidates[
                    : self.MAX_CANDIDATES
                ]
            )

            # The canonical route remains primary.
            # Generic manager candidates are supporting evidence only.
            selection.primary = CapabilityCandidate(
                kind="route",
                name=selection.owner,
                score=selection.confidence,
                description=selection.reason,
                available=True,
                reason=(
                    "Canonical route has priority over "
                    "generic capability matching."
                ),
            )

            return selection

        # --------------------------------------------------------------
        # Normal answer/tool routes can use manager discovery.
        # --------------------------------------------------------------

        candidates = (
            await self._collect_manager_candidates(
                request,
                context,
            )
        )

        candidates.sort(
            key=lambda item: (
                -item.score,
                item.kind,
                item.name,
            )
        )

        selection.candidates = candidates[
            : self.MAX_CANDIDATES
        ]

        if selection.candidates:
            selection.primary = (
                selection.candidates[0]
            )

            # If a strong generic tool/skill/action exists, expose it
            # as the owner for a normal tool route.
            best = selection.candidates[0]

            if (
                selection.route == "tool"
                and best.score >= self.threshold
            ):
                selection.owner = (
                    f"{best.kind}:{best.name}"
                )
                selection.confidence = max(
                    selection.confidence,
                    best.score,
                )
                selection.reason = (
                    "Generic tool capability selected "
                    "by the registered capability managers."
                )

        return selection

    # ------------------------------------------------------------------
    # Compatibility helper
    # ------------------------------------------------------------------

    async def select_capability(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CapabilitySelection:
        """Compatibility alias used by integration layers."""

        return await self.select(
            query,
            context,
        )

    # ------------------------------------------------------------------
    # Health / capability metadata
    # ------------------------------------------------------------------

    def capabilities(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "threshold": self.threshold,
            "side_effect_free": True,
            "execution_owner": False,
            "canonical_routing": True,
            "managers": {
                "skills": self.skill_manager is not None,
                "tools": self.tool_manager is not None,
                "actions": self.action_manager is not None,
                "agents": self.agent_manager is not None,
                "plugins": self.plugin_manager is not None,
            },
            "canonical_routes": [
                "answer",
                "research",
                "memory",
                "tool",
                "action",
                "multimodal",
                "vision",
                "document",
                "voice",
                "computer",
                "automation",
                "repository",
                "inspect_only",
                "plan_only",
                "engineering",
                "delivery",
            ],
        }

    def health(self) -> Dict[str, Any]:
        managers = self.capabilities()[
            "managers"
        ]

        # Skills/tools/actions are the minimum existing manager family.
        # Agents/plugins remain optional.
        healthy = bool(
            managers["skills"]
            and managers["tools"]
            and managers["actions"]
        )

        return {
            "healthy": healthy,
            "version": self.VERSION,
            "side_effect_free": True,
            "canonical_routing": True,
            "managers": managers,
        }


__all__ = [
    "CapabilityCandidate",
    "CapabilitySelection",
    "UnifiedCapabilitySelector",
]