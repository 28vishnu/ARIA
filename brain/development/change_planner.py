"""ARIA deterministic change and impact planner.

Step 4 adds architecture-aware change-impact analysis before any code is
written.  This module remains read-only: it never writes files, executes
repository code, deploys, or pushes to GitHub.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, TYPE_CHECKING

from .requirement_parser import Requirement

if TYPE_CHECKING:
    from .architecture_intelligence import ArchitectureIntelligence, ArchitectureSnapshot


@dataclass(frozen=True)
class FileChange:
    path: str
    action: str
    reason: str
    risk: str = "low"

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "action": self.action, "reason": self.reason, "risk": self.risk}


@dataclass(frozen=True)
class ImpactAnalysis:
    """Architecture evidence describing what a planned change can affect."""

    affected_modules: tuple[str, ...] = ()
    affected_files: tuple[str, ...] = ()
    affected_components: tuple[str, ...] = ()
    direct_dependents: tuple[str, ...] = ()
    transitive_dependents: tuple[str, ...] = ()
    newly_created_modules: tuple[str, ...] = ()
    protected_areas_touched: tuple[str, ...] = ()
    architecture_warnings: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    risk: str = "low"
    review_required: bool = False
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_modules": list(self.affected_modules),
            "affected_files": list(self.affected_files),
            "affected_components": list(self.affected_components),
            "direct_dependents": list(self.direct_dependents),
            "transitive_dependents": list(self.transitive_dependents),
            "newly_created_modules": list(self.newly_created_modules),
            "protected_areas_touched": list(self.protected_areas_touched),
            "architecture_warnings": list(self.architecture_warnings),
            "reasons": list(self.reasons),
            "risk": self.risk,
            "review_required": self.review_required,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ChangePlan:
    requirement: Requirement
    changes: tuple[FileChange, ...] = ()
    tests: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    requires_approval: bool = False
    blocked: bool = False
    block_reason: str | None = None
    impact: ImpactAnalysis = field(default_factory=ImpactAnalysis)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "changes": [item.to_dict() for item in self.changes],
            "tests": list(self.tests),
            "risks": list(self.risks),
            "requires_approval": self.requires_approval,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "impact": self.impact.to_dict(),
        }


class ChangePlanner:
    """Conservative planner with architecture-aware impact analysis."""

    PROTECTED_PREFIXES = (
        ".git/", ".github/workflows/", ".aria_workspaces/", ".aria_workspace/",
    )
    PROTECTED_NAMES = (
        ".env", ".env.local", ".env.production", ".env.development", ".env.test",
        ".env.staging", "credentials.json", "credentials.yaml", "credentials.yml",
        "secrets.json", "secrets.yaml", "secrets.yml", "service-account.json",
    )
    SENSITIVE_NAME_FRAGMENTS = (
        ".pem", ".key", ".p12", ".pfx", "credential", "credentials", "secret",
        "secrets", "password", "passwd", "token", "private_key", "private-key",
    )
    HIGH_RISK_PATHS = frozenset({
        "main.py", "core/bootstrap.py", "Dockerfile", "docker-compose.yml",
        "docker-compose.yaml", "pyproject.toml", "requirements.txt", "package.json",
        "package-lock.json",
    })
    VALID_ACTIONS = frozenset({"create", "modify", "inspect"})

    def __init__(self, architecture_intelligence: "ArchitectureIntelligence | None" = None) -> None:
        self.architecture_intelligence = architecture_intelligence

    def plan(
        self,
        requirement: Requirement,
        *,
        existing_paths: Iterable[str] = (),
        repository_path: str | Path | None = None,
        architecture_snapshot: "ArchitectureSnapshot | None" = None,
    ) -> ChangePlan:
        if not isinstance(requirement, Requirement):
            raise TypeError("requirement must be a Requirement.")

        existing = self._normalise_existing_paths(existing_paths)
        risks = list(requirement.risk_flags)
        changes: list[FileChange] = []
        blocked = False
        block_reasons: list[str] = []

        create_only = self._is_create_only_requirement(requirement)
        intent = self._infer_intent(requirement)
        no_modifications = self._forbids_existing_modifications(requirement)
        no_delete = self._has_constraint(requirement, "NO_DELETE")

        for raw_path in requirement.requested_files:
            normalized = self._normalise_path(raw_path)
            if normalized is None:
                blocked = True
                block_reasons.append(f"Unsafe or invalid repository path requested: {raw_path}")
                risks.append("unsafe_path")
                continue

            protection_reason = self._protected_path_reason(normalized)
            if protection_reason:
                blocked = True
                block_reasons.append(
                    f"Protected path requested: {normalized} ({protection_reason})"
                )
                risks.append("protected_path")
                continue

            exists = normalized in existing
            if exists and (create_only or no_modifications):
                blocked = True
                block_reasons.append(
                    f"Existing file modification is forbidden by the requirement: {normalized}"
                )
                risks.append("existing_file_modification")
                continue

            action = "modify" if exists else "create"
            if action not in self.VALID_ACTIONS:
                blocked = True
                block_reasons.append(f"Unsupported planned action: {action}")
                continue

            risk = self._risk_for_path(normalized)
            if risk == "high":
                risks.append(f"high_risk_path:{normalized}")
            changes.append(
                FileChange(
                    path=normalized,
                    action=action,
                    reason="Explicitly requested repository file.",
                    risk=risk,
                )
            )

        if not changes and intent in {"create", "modify", "fix", "refactor", "remove"}:
            if requirement.requested_files:
                blocked = True
                block_reasons.append("No safe file changes remained after path validation.")
            elif intent in {"create", "modify", "fix", "refactor"}:
                changes.append(
                    FileChange(
                        path="<implementation-target>",
                        action="inspect",
                        reason="No explicit file was supplied; architecture inspection must locate the target before writing.",
                        risk="medium",
                    )
                )

        if no_delete and intent == "remove":
            blocked = True
            block_reasons.append("Requirement forbids deletion but requests removal.")
            risks.append("delete_forbidden")

        tests = self._derive_tests(requirement, changes)
        impact = self._build_impact(
            requirement,
            changes,
            repository_path=repository_path,
            architecture_snapshot=architecture_snapshot,
        )

        if impact.risk in {"medium", "high", "critical"}:
            risks.append(f"impact_risk:{impact.risk}")
        if impact.review_required:
            risks.append("impact_review_required")

        requires_approval = bool(requirement.requires_approval or impact.review_required)
        if blocked and not block_reasons:
            block_reasons.append("Change request blocked by deterministic planner.")

        return ChangePlan(
            requirement=requirement,
            changes=tuple(changes),
            tests=tuple(tests),
            risks=tuple(dict.fromkeys(risks)),
            requires_approval=requires_approval,
            blocked=blocked,
            block_reason="; ".join(block_reasons) if block_reasons else None,
            impact=impact,
        )

    def _build_impact(
        self,
        requirement: Requirement,
        changes: list[FileChange],
        *,
        repository_path: str | Path | None,
        architecture_snapshot: "ArchitectureSnapshot | None",
    ) -> ImpactAnalysis:
        if architecture_snapshot is None and self.architecture_intelligence and repository_path:
            architecture_snapshot = self.architecture_intelligence.inspect(repository_path)

        if architecture_snapshot is None:
            return ImpactAnalysis(
                reasons=("Architecture snapshot unavailable; impact analysis is incomplete.",),
                risk="medium",
                review_required=True,
                confidence=0.0,
            )

        module_to_path: dict[str, str] = {}
        for path in architecture_snapshot.repository.get("python_modules", []):
            normalized = str(path).replace("\\", "/")
            if normalized.endswith(".py") or "/" in normalized:
                module = normalized[:-3] if normalized.endswith(".py") else normalized
                module = module.replace("/", ".")
                file_path = normalized
            else:
                module = normalized
                file_path = normalized.replace(".", "/") + ".py"
            if module.endswith(".__init__"):
                module = module[:-9]
            module_to_path[module] = file_path

        changed_modules: list[str] = []
        new_modules: list[str] = []
        changed_components: set[str] = set()
        touched_protected: set[str] = set()
        reasons: list[str] = []

        for change in changes:
            if change.path.startswith("<"):
                continue
            normalized = change.path.replace("\\", "/").strip("/")
            if normalized.endswith(".py"):
                module = normalized[:-3].replace("/", ".")
                if module.endswith(".__init__"):
                    module = module[:-9]
                changed_modules.append(module)
                if module not in architecture_snapshot.change_impact and change.action == "create":
                    new_modules.append(module)
                component = architecture_snapshot.module_components.get(module)
                if component:
                    changed_components.add(component)
            else:
                component = self._component_for_path(normalized)
                changed_components.add(component)

            for protected in architecture_snapshot.protected_areas:
                if normalized == protected or normalized.startswith(protected.rstrip("/") + "/"):
                    touched_protected.add(protected)

        impacted: set[str] = set(changed_modules)
        direct: set[str] = set()
        transitive: set[str] = set()
        for module in changed_modules:
            dependents = list(architecture_snapshot.change_impact.get(module, []))
            for dependent in dependents:
                impacted.add(dependent)
                transitive.add(dependent)
            # A dependent that directly imports the module can be identified
            # conservatively by the first hop in the transitive list only when
            # component data exposes it; otherwise keep the distinction empty.
            for dependent in architecture_snapshot.change_impact.get(module, []):
                direct.add(dependent)

        for module in impacted:
            component = architecture_snapshot.module_components.get(module)
            if component:
                changed_components.add(component)

        affected_files = {
            module_to_path[module]
            for module in impacted
            if module in module_to_path
        }
        affected_files.update(
            change.path for change in changes if not change.path.startswith("<")
        )

        warning_count = len(architecture_snapshot.architecture_warnings)
        fanout = len(transitive)
        if touched_protected:
            risk = "critical"
        elif fanout >= 50 or len(impacted) >= 75:
            risk = "high"
        elif fanout >= 15 or len(impacted) >= 25 or warning_count >= 3:
            risk = "medium"
        else:
            risk = "low"

        review_required = risk in {"high", "critical"} or bool(touched_protected)
        if new_modules:
            reasons.append("New Python module(s) have no existing dependency graph edges; post-write graph analysis will be required.")
        if changed_modules:
            reasons.append(f"Architecture dependency graph identified {len(impacted)} affected module(s).")
        if fanout:
            reasons.append(f"Potential transitive dependents: {fanout}.")
        if touched_protected:
            reasons.append("A protected architecture area is touched; elevated review is required.")
        if warning_count:
            reasons.append(f"Existing architecture warnings: {warning_count}.")
        if not reasons:
            reasons.append("No dependency-based impact was identified from the current architecture snapshot.")

        confidence = 0.95 if not architecture_snapshot.analysis_errors else 0.75
        if not changed_modules and not changes:
            confidence = min(confidence, 0.5)

        return ImpactAnalysis(
            affected_modules=tuple(sorted(impacted)),
            affected_files=tuple(sorted(affected_files)),
            affected_components=tuple(sorted(changed_components)),
            direct_dependents=tuple(sorted(direct)),
            transitive_dependents=tuple(sorted(transitive)),
            newly_created_modules=tuple(sorted(new_modules)),
            protected_areas_touched=tuple(sorted(touched_protected)),
            architecture_warnings=tuple(architecture_snapshot.architecture_warnings),
            reasons=tuple(dict.fromkeys(reasons)),
            risk=risk,
            review_required=review_required,
            confidence=confidence,
        )

    @staticmethod
    def _component_for_path(path: str) -> str:
        parts = path.replace("\\", "/").strip("/").split("/")
        if not parts:
            return "."
        if parts[0] == "brain" and len(parts) >= 2:
            return "/".join(parts[:2])
        return parts[0]

    def _derive_tests(self, requirement: Requirement, changes: list[FileChange]) -> list[str]:
        tests = list(requirement.acceptance_criteria)
        if not tests and changes:
            tests.append("Run static validation for every changed Python file.")
            if any(change.path.endswith(".py") for change in changes):
                tests.append("Run targeted tests covering the changed behavior and its affected dependents.")
        return list(dict.fromkeys(tests))

    @staticmethod
    def _infer_intent(requirement: Requirement) -> str:
        text = requirement.raw_text.lower()
        for intent, terms in (
            ("create", ("create", "add", "build", "generate", "new file")),
            ("fix", ("fix", "repair", "bug", "error", "broken")),
            ("refactor", ("refactor", "restructure", "clean up")),
            ("remove", ("remove", "delete", "destroy")),
            ("modify", ("modify", "update", "change", "improve", "replace")),
        ):
            if any(term in text for term in terms):
                return intent
        return "inspect"

    @classmethod
    def _normalise_existing_paths(cls, paths: Iterable[str]) -> set[str]:
        result: set[str] = set()
        for path in paths:
            normalized = cls._normalise_path(path)
            if normalized:
                result.add(normalized)
        return result

    @staticmethod
    def _normalise_path(path: str) -> str | None:
        normalized = str(path).strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized or normalized.startswith("/"):
            return None
        candidate = Path(normalized)
        if ".." in candidate.parts:
            return None
        return candidate.as_posix()

    @classmethod
    def _protected_path_reason(cls, path: str) -> str | None:
        normalized = path.replace("\\", "/").strip("/")
        lower = normalized.lower()
        if any(lower.startswith(prefix) for prefix in cls.PROTECTED_PREFIXES):
            return "protected repository area"
        if Path(normalized).name.lower() in cls.PROTECTED_NAMES:
            return "protected configuration or credential file"
        if any(fragment in Path(normalized).name.lower() for fragment in cls.SENSITIVE_NAME_FRAGMENTS):
            return "sensitive file name"
        return None

    @classmethod
    def _risk_for_path(cls, path: str) -> str:
        normalized = path.replace("\\", "/").strip("/")
        if normalized in cls.HIGH_RISK_PATHS:
            return "high"
        if cls._protected_path_reason(normalized):
            return "critical"
        if normalized.startswith("core/") or normalized.startswith("brain/"):
            return "medium"
        return "low"

    @staticmethod
    def _has_constraint(requirement: Requirement, value: str) -> bool:
        return value in set(requirement.constraints)

    @staticmethod
    def _is_create_only_requirement(requirement: Requirement) -> bool:
        metadata = requirement.metadata if isinstance(requirement.metadata, dict) else {}
        if metadata.get("create_only"):
            return True
        constraints = " ".join(requirement.constraints).lower()
        return any(phrase in constraints for phrase in ("create-only", "create only", "only create"))

    @staticmethod
    def _forbids_existing_modifications(requirement: Requirement) -> bool:
        constraints = set(requirement.constraints)
        return bool({"NO_MODIFY", "NO_MODIFY_EXISTING", "CREATE_ONLY"} & constraints)
