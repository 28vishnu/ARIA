"""Canonical, side-effect-free capability selection for ARIA.

This module does not execute tools, skills, actions, agents, or plugins.
It only inspects the already-registered capability managers and returns a
ranked selection plan. Execution remains owned by the existing managers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CapabilityCandidate:
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


@dataclass
class CapabilitySelection:
    request: str
    primary: Optional[CapabilityCandidate] = None
    candidates: List[CapabilityCandidate] = field(default_factory=list)
    execution_allowed: bool = True
    read_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request,
            "primary": self.primary.to_dict() if self.primary else None,
            "candidates": [item.to_dict() for item in self.candidates],
            "execution_allowed": self.execution_allowed,
            "read_only": self.read_only,
        }


class UnifiedCapabilitySelector:
    """Select the best registered ARIA capability without executing it."""

    VERSION = "aria-unified-capability-selector-20261006"
    DEFAULT_THRESHOLD = 0.30
    MAX_CANDIDATES = 12

    _READ_ONLY = (
        "do not modify", "don't modify", "read only", "read-only",
        "without changing", "without modifying", "no changes",
        "analyze only", "inspect only", "explain only", "plan only",
        "phases only", "do not execute", "don't execute",
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
            self.threshold = max(0.0, min(1.0, float(threshold)))
        except (TypeError, ValueError):
            self.threshold = self.DEFAULT_THRESHOLD

    @staticmethod
    def _text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    @staticmethod
    def _token_score(query: str, name: str, description: str) -> float:
        q = set(re.findall(r"[a-z0-9_+-]{3,}", query.lower()))
        if not q:
            return 0.0
        name_tokens = set(re.findall(r"[a-z0-9_+-]{3,}", name.lower()))
        desc_tokens = set(re.findall(r"[a-z0-9_+-]{3,}", description.lower()))
        score = 0.0
        if name_tokens & q:
            score += 0.65
        overlap = len(q & desc_tokens)
        if overlap:
            score += min(0.30, overlap * 0.08)
        if name.lower() in query.lower():
            score += 0.20
        return min(1.0, score)

    def _read_only(self, query: str, context: Dict[str, Any]) -> bool:
        text = self._text(query)
        if any(marker in text for marker in self._READ_ONLY):
            return True
        return bool(context.get("read_only") or context.get("plan_only"))

    async def select(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CapabilitySelection:
        context = dict(context or {})
        selection = CapabilitySelection(
            request=str(query or ""),
            execution_allowed=not self._read_only(query, context),
            read_only=self._read_only(query, context),
        )
        candidates: List[CapabilityCandidate] = []

        if self.tool_manager is not None and hasattr(self.tool_manager, "select_tool"):
            try:
                tool = await self.tool_manager.select_tool(query, context)
                if tool is not None:
                    name = str(getattr(tool, "name", "")).strip()
                    if name:
                        description = str(getattr(tool, "description", "") or "")
                        candidates.append(CapabilityCandidate(
                            kind="tool", name=name, score=0.95,
                            description=description,
                            reason="ToolManager confidence selection.",
                        ))
            except Exception:
                pass

        if self.skill_manager is not None and hasattr(self.skill_manager, "find_candidates"):
            try:
                skills = await self.skill_manager.find_candidates(
                    query, context, minimum_confidence=self.threshold,
                )
                for item in skills[: self.MAX_CANDIDATES]:
                    skill = item.get("skill")
                    name = str(item.get("name") or getattr(skill, "name", "")).strip()
                    if name:
                        candidates.append(CapabilityCandidate(
                            kind="skill", name=name,
                            score=float(item.get("confidence", 0.0)),
                            description=str(getattr(skill, "description", "") or ""),
                            reason="SkillManager capability confidence.",
                        ))
            except Exception:
                pass

        if self.agent_manager is not None and hasattr(self.agent_manager, "select_agent"):
            try:
                agent, score = await self.agent_manager.select_agent(query, context)
                if agent is not None and float(score) >= self.threshold:
                    candidates.append(CapabilityCandidate(
                        kind="agent", name=str(getattr(agent, "name", "")),
                        score=float(score),
                        description=str(getattr(agent, "description", "") or ""),
                        reason="AgentManager capability confidence.",
                    ))
            except Exception:
                pass

        if self.action_manager is not None:
            for name, action in getattr(self.action_manager, "actions", {}).items():
                description = str(getattr(action, "description", "") or "")
                score = self._token_score(query, str(name), description)
                if score >= self.threshold:
                    candidates.append(CapabilityCandidate(
                        kind="action", name=str(name), score=score,
                        description=description,
                        permission_level=str(getattr(action, "permission_level", "confirm")),
                        reason="Action capability metadata match.",
                    ))

        if self.plugin_manager is not None:
            for plugin_id, plugin in getattr(self.plugin_manager, "plugins", {}).items():
                manifest = getattr(plugin, "manifest", None)
                caps = list(getattr(manifest, "capabilities", []) or [])
                description = " ".join(str(item) for item in caps)
                score = self._token_score(query, str(plugin_id), description)
                state = str(getattr(plugin, "state", "unknown")).lower()
                if score >= self.threshold and state not in {"disabled", "failed"}:
                    candidates.append(CapabilityCandidate(
                        kind="plugin", name=str(plugin_id), score=score,
                        description=description,
                        available=True,
                        reason="Plugin capability metadata match.",
                    ))

        candidates.sort(key=lambda item: (-item.score, item.kind, item.name))
        selection.candidates = candidates[: self.MAX_CANDIDATES]
        if selection.candidates:
            selection.primary = selection.candidates[0]

        return selection

    def capabilities(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "threshold": self.threshold,
            "managers": {
                "skills": self.skill_manager is not None,
                "tools": self.tool_manager is not None,
                "actions": self.action_manager is not None,
                "agents": self.agent_manager is not None,
                "plugins": self.plugin_manager is not None,
            },
        }

    def health(self) -> Dict[str, Any]:
        managers = self.capabilities()["managers"]
        return {
            "healthy": bool(managers["skills"] and managers["tools"] and managers["actions"]),
            "version": self.VERSION,
            "managers": managers,
        }


__all__ = ["CapabilityCandidate", "CapabilitySelection", "UnifiedCapabilitySelector"]
