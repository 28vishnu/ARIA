from __future__ import annotations

"""
ARIA Phase 1 — Step 42
Deep Repository Reasoning

Converts the existing static architecture/dependency analysis into a
compact engineering map that can be consumed by the development brain.

This module is read-only. It never edits, executes, deploys, or pushes
repository code.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class RepositoryReasoning:
    repository: dict[str, Any] = field(default_factory=dict)
    components: tuple[dict[str, Any], ...] = ()
    module_roles: dict[str, str] = field(default_factory=dict)
    module_components: dict[str, str] = field(default_factory=dict)
    impact_map: dict[str, tuple[str, ...]] = field(default_factory=dict)
    protected_areas: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    recommended_locations: dict[str, tuple[str, ...]] = field(default_factory=dict)
    analysis_errors: tuple[str, ...] = ()
    relevant_files: tuple[str, ...] = ()
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": dict(self.repository),
            "components": [dict(item) for item in self.components],
            "module_roles": dict(self.module_roles),
            "module_components": dict(self.module_components),
            "impact_map": {
                key: list(value)
                for key, value in self.impact_map.items()
            },
            "protected_areas": list(self.protected_areas),
            "warnings": list(self.warnings),
            "recommended_locations": {
                key: list(value)
                for key, value in self.recommended_locations.items()
            },
            "analysis_errors": list(self.analysis_errors),
            "relevant_files": list(self.relevant_files),
            "confidence": self.confidence,
        }


class DeepRepositoryReasoner:
    """
    Evidence-driven repository understanding layer.

    It consumes ArchitectureIntelligence output and derives:
    - project shape
    - logical components
    - module responsibilities
    - dependency/dependent relationships
    - protected areas
    - likely implementation locations
    - relevant files for a requirement
    """

    VERSION = "PHASE1-DEEP-REPOSITORY-20261004"

    def __init__(self, architecture_intelligence: Any) -> None:
        self.architecture_intelligence = architecture_intelligence

    def analyze(
        self,
        repository_path: str | Path,
        *,
        requirement_text: str = "",
        keywords: Iterable[str] = (),
    ) -> RepositoryReasoning:
        root = Path(repository_path).expanduser().resolve()

        snapshot = self.architecture_intelligence.inspect(root)
        data = snapshot.to_dict()

        terms = self._terms(
            requirement_text,
            keywords,
        )

        relevant = self._relevant_files(
            data,
            terms,
        )

        confidence = self._confidence(
            data,
            relevant,
        )

        components = tuple(
            self._compact_component(item)
            for item in data.get("components", [])
        )

        impact_map = {
            str(key): tuple(
                str(item)
                for item in value
                if str(item).strip()
            )
            for key, value in (
                data.get("change_impact", {}) or {}
            ).items()
        }

        return RepositoryReasoning(
            repository=dict(data.get("repository", {}) or {}),
            components=components,
            module_roles={
                str(key): str(value)
                for key, value in (
                    data.get("module_roles", {}) or {}
                ).items()
            },
            module_components={
                str(key): str(value)
                for key, value in (
                    data.get("module_components", {}) or {}
                ).items()
            },
            impact_map=impact_map,
            protected_areas=tuple(
                str(item)
                for item in (
                    data.get("protected_areas", []) or []
                )
            ),
            warnings=tuple(
                str(item)
                for item in (
                    data.get("architecture_warnings", []) or []
                )
            ),
            recommended_locations={
                str(key): tuple(
                    str(item)
                    for item in value
                )
                for key, value in (
                    data.get("recommended_locations", {}) or {}
                ).items()
            },
            analysis_errors=tuple(
                str(item)
                for item in (
                    data.get("analysis_errors", []) or []
                )
            ),
            relevant_files=tuple(relevant),
            confidence=confidence,
        )

    def build_prompt_section(
        self,
        reasoning: RepositoryReasoning,
    ) -> str:
        data = reasoning.to_dict()

        lines = [
            "",
            "DEEP REPOSITORY REASONING:",
            f"Repository reasoning version: {self.VERSION}",
            f"Repository confidence: {reasoning.confidence}",
            "",
            "Repository shape:",
            self._json_line(data["repository"]),
            "",
            "Logical components:",
        ]

        if reasoning.components:
            for item in reasoning.components[:80]:
                lines.append(self._json_line(item))
        else:
            lines.append("- No component model was available.")

        lines.extend(
            [
                "",
                "Module responsibilities:",
            ]
        )

        roles = list(reasoning.module_roles.items())
        if roles:
            for module, role in roles[:160]:
                lines.append(f"- {module}: {role}")
        else:
            lines.append("- No module roles were available.")

        lines.extend(["", "Module ownership/components:"])
        ownership = list(reasoning.module_components.items())
        if ownership:
            for module, component in ownership[:160]:
                lines.append(f"- {module}: {component}")
        else:
            lines.append("- No module-component mapping was available.")

        lines.extend(["", "Dependency impact map:"])
        if reasoning.impact_map:
            for module, dependents in list(
                reasoning.impact_map.items()
            )[:160]:
                lines.append(
                    f"- {module} -> {', '.join(dependents[:40])}"
                )
        else:
            lines.append("- No dependency impact map was available.")

        lines.extend(["", "Recommended implementation locations:"])
        if reasoning.recommended_locations:
            for role, locations in list(
                reasoning.recommended_locations.items()
            )[:80]:
                lines.append(
                    f"- {role}: {', '.join(locations[:30])}"
                )
        else:
            lines.append("- No location recommendations were available.")

        lines.extend(["", "Requirement-relevant files:"])
        if reasoning.relevant_files:
            for path in reasoning.relevant_files[:160]:
                lines.append(f"- {path}")
        else:
            lines.append("- No additional relevance matches were identified.")

        lines.extend(["", "Protected areas:"])
        for path in reasoning.protected_areas[:120]:
            lines.append(f"- {path}")

        lines.extend(["", "Architecture warnings:"])
        if reasoning.warnings:
            for warning in reasoning.warnings[:80]:
                lines.append(f"- {warning}")
        else:
            lines.append("- None reported.")

        lines.extend(["", "Architecture analysis errors:"])
        if reasoning.analysis_errors:
            for error in reasoning.analysis_errors[:80]:
                lines.append(f"- {error}")
        else:
            lines.append("- None reported.")

        lines.extend(
            [
                "",
                "Repository reasoning rules:",
                "- Prefer existing components and interfaces when they already fit the requirement.",
                "- Follow the repository's existing responsibility boundaries.",
                "- Inspect dependency impact before modifying a shared module.",
                "- Do not create duplicate subsystems when an existing subsystem is suitable.",
                "- Do not modify protected areas unless the requirement explicitly requires a permitted change.",
                "- Use relevant-file evidence before choosing implementation locations.",
            ]
        )

        return "\n".join(lines)

    @staticmethod
    def _compact_component(item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {"value": str(item)}

        return {
            "name": str(item.get("name", "")),
            "root": str(item.get("root", "")),
            "files": list(item.get("files", []) or [])[:120],
            "python_modules": list(
                item.get("python_modules", []) or []
            )[:120],
            "classes": list(item.get("classes", []) or [])[:120],
            "functions": list(item.get("functions", []) or [])[:160],
            "dependencies": list(
                item.get("dependencies", []) or []
            )[:120],
            "dependents": list(
                item.get("dependents", []) or []
            )[:120],
            "responsibilities": list(
                item.get("responsibilities", []) or []
            )[:80],
        }

    @staticmethod
    def _terms(
        requirement_text: str,
        keywords: Iterable[str],
    ) -> list[str]:
        raw = f"{requirement_text} {' '.join(map(str, keywords))}"
        tokens: list[str] = []

        for token in raw.lower().replace("_", " ").split():
            cleaned = "".join(
                char
                for char in token
                if char.isalnum()
            )
            if len(cleaned) >= 3 and cleaned not in {
                "the", "and", "for", "with", "from",
                "into", "that", "this", "should", "must",
                "create", "build", "implement", "update",
                "complete", "according", "phase",
            }:
                if cleaned not in tokens:
                    tokens.append(cleaned)

        return tokens[:80]

    @classmethod
    def _relevant_files(
        cls,
        data: dict[str, Any],
        terms: list[str],
    ) -> list[str]:
        if not terms:
            return []

        scores: dict[str, int] = {}

        def add(path: str, score: int) -> None:
            if path:
                scores[path] = scores.get(path, 0) + score

        for component in data.get("components", []) or []:
            if not isinstance(component, dict):
                continue

            text = " ".join(
                [
                    str(component.get("name", "")),
                    str(component.get("root", "")),
                    " ".join(map(str, component.get("responsibilities", []) or [])),
                ]
            ).lower()

            hits = sum(1 for term in terms if term in text)

            if hits:
                for path in component.get("files", []) or []:
                    add(str(path), 2 + hits)

        for module, role in (
            data.get("module_roles", {}) or {}
        ).items():
            text = f"{module} {role}".lower()
            hits = sum(1 for term in terms if term in text)
            if hits:
                add(str(module), 2 + hits)

        for location_list in (
            data.get("recommended_locations", {}) or {}
        ).values():
            for path in location_list or []:
                text = str(path).lower()
                hits = sum(1 for term in terms if term in text)
                if hits:
                    add(str(path), 1 + hits)

        return [
            path
            for path, _ in sorted(
                scores.items(),
                key=lambda item: (-item[1], item[0]),
            )[:160]
        ]

    @staticmethod
    def _confidence(
        data: dict[str, Any],
        relevant: list[str],
    ) -> str:
        errors = len(data.get("analysis_errors", []) or [])
        components = len(data.get("components", []) or [])
        roles = len(data.get("module_roles", {}) or {})

        if components and roles and relevant and errors == 0:
            return "high"
        if components or roles:
            return "medium"
        return "low"

    @staticmethod
    def _json_line(value: Any) -> str:
        import json
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
            )
        except Exception:
            return str(value)
