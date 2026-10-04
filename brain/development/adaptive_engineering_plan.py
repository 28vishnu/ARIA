from __future__ import annotations

"""
ARIA Phase 1 — Step 43
Adaptive Engineering Plan

Maintains a living engineering strategy around the deterministic ChangePlan.
The deterministic plan remains the safety boundary; this layer adapts:
- current objective state
- evidence collected
- verification focus
- repair strategy
- next engineering action

It is deliberately generic and does not special-case individual tests.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class PlanRevision:
    revision: int
    trigger: str
    state: str
    objective: str
    completed: tuple[str, ...] = ()
    remaining: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    verification_focus: tuple[str, ...] = ()
    repair_strategy: tuple[str, ...] = ()
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "trigger": self.trigger,
            "state": self.state,
            "objective": self.objective,
            "completed": list(self.completed),
            "remaining": list(self.remaining),
            "evidence": list(self.evidence),
            "next_actions": list(self.next_actions),
            "verification_focus": list(self.verification_focus),
            "repair_strategy": list(self.repair_strategy),
            "confidence": self.confidence,
        }


@dataclass
class AdaptiveEngineeringPlan:
    requirement: str
    original_plan: dict[str, Any] = field(default_factory=dict)
    revisions: list[PlanRevision] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    state: str = "planned"

    VERSION = "PHASE1-ADAPTIVE-PLAN-20261004"

    def initialize(self, plan: Any) -> PlanRevision:
        plan_dict = self._to_dict(plan)
        self.original_plan = plan_dict

        changes = plan_dict.get("changes", []) or []
        planned_paths = tuple(
            str(item.get("path", ""))
            for item in changes
            if isinstance(item, dict) and item.get("path")
        )

        revision = PlanRevision(
            revision=0,
            trigger="initial_plan",
            state="planned",
            objective=self.requirement,
            remaining=planned_paths,
            evidence=(
                "Deterministic change plan established.",
                "Original plan remains the safety boundary.",
            ),
            next_actions=(
                "Inspect the verified repository context.",
                "Implement the smallest coherent change set.",
                "Verify acceptance criteria with evidence.",
            ),
            verification_focus=(
                "Requirement acceptance criteria",
                "Static validation",
                "Relevant targeted tests",
            ),
            repair_strategy=(
                "Diagnose evidence before changing code.",
                "Repair the root cause rather than the symptom.",
                "Retest after every coherent repair.",
            ),
            confidence="medium",
        )
        self.revisions = [revision]
        self.state = revision.state
        return revision

    def revise(
        self,
        *,
        trigger: str,
        test_result: Any | None = None,
        failure: Any | None = None,
        validation: Any | None = None,
        repository_summary: dict[str, Any] | None = None,
        changed_paths: Iterable[str] = (),
    ) -> PlanRevision:
        previous = self.revisions[-1] if self.revisions else self.initialize(
            self.original_plan
        )

        test_data = self._to_dict(test_result)
        failure_data = self._to_dict(failure)
        validation_data = self._to_dict(validation)

        evidence = self._collect_evidence(
            test_data,
            failure_data,
            validation_data,
            repository_summary or {},
        )
        self.evidence.extend(evidence)

        passed = self._passed(test_result)
        validation_ok = self._validation_ok(validation)
        failure_detected = self._failed(test_result, failure)

        if passed and validation_ok:
            state = "verified"
            next_actions = (
                "Re-check the complete acceptance criteria.",
                "Confirm no unrelated behavior was changed.",
                "Finalize only after independent evidence agrees.",
            )
        elif failure_detected:
            state = "diagnosing" if not failure_data else "repairing"
            next_actions = (
                "Inspect the exact failure evidence and execution context.",
                "Identify the smallest root-cause hypothesis.",
                "Repair only evidence-supported code or tests.",
                "Re-run targeted verification and reassess the plan.",
            )
        else:
            state = "investigating"
            next_actions = (
                "Gather stronger execution evidence.",
                "Compare observed behavior with acceptance criteria.",
                "Update the implementation strategy from the evidence.",
            )

        completed = list(previous.completed)
        for path in changed_paths:
            normalized = str(path).strip()
            if normalized and normalized not in completed:
                completed.append(normalized)

        remaining = [
            path
            for path in previous.remaining
            if path not in completed
        ]

        revision = PlanRevision(
            revision=previous.revision + 1,
            trigger=str(trigger),
            state=state,
            objective=self.requirement,
            completed=tuple(completed[-160:]),
            remaining=tuple(remaining[-160:]),
            evidence=tuple(evidence[-40:]),
            next_actions=tuple(next_actions),
            verification_focus=self._verification_focus(
                test_data,
                failure_data,
                validation_data,
            ),
            repair_strategy=self._repair_strategy(
                failure_data,
                test_data,
            ),
            confidence=self._confidence(
                test_result,
                failure,
                validation,
            ),
        )

        self.revisions.append(revision)
        self.state = state
        return revision

    def build_prompt_section(self) -> str:
        revision = self.revisions[-1] if self.revisions else None

        lines = [
            "",
            "ADAPTIVE ENGINEERING PLAN:",
            f"Plan engine version: {self.VERSION}",
            f"State: {self.state}",
            f"Requirement objective: {self.requirement}",
            "",
            "IMPORTANT: The deterministic ChangePlan remains the safety boundary. "
            "Adapt strategy from evidence, but never bypass path, permission, "
            "security, or scope controls.",
        ]

        if revision is None:
            lines.append("No adaptive revision exists yet.")
            return "\n".join(lines)

        lines.extend(
            [
                f"Revision: {revision.revision}",
                f"Trigger: {revision.trigger}",
                f"Confidence: {revision.confidence}",
                "",
                "Evidence:",
            ]
        )
        lines.extend(f"- {item}" for item in revision.evidence)

        lines.extend(["", "Completed work:"])
        lines.extend(
            f"- {item}" for item in revision.completed
        )

        lines.extend(["", "Remaining planned work:"])
        lines.extend(
            f"- {item}" for item in revision.remaining
        )

        lines.extend(["", "Next engineering actions:"])
        lines.extend(
            f"- {item}" for item in revision.next_actions
        )

        lines.extend(["", "Verification focus:"])
        lines.extend(
            f"- {item}" for item in revision.verification_focus
        )

        lines.extend(["", "Repair strategy:"])
        lines.extend(
            f"- {item}" for item in revision.repair_strategy
        )

        lines.extend(
            [
                "",
                "Adaptive reasoning rules:",
                "- Treat new evidence as a reason to reassess the plan, not blindly repeat it.",
                "- Preserve successful work unless evidence proves it is wrong.",
                "- Prefer the smallest coherent root-cause repair.",
                "- If evidence is insufficient, gather evidence instead of guessing.",
                "- Do not call an unfamiliar failure category a root cause by itself.",
                "- Do not broaden scope merely because unrelated checks fail.",
                "- Reassess acceptance after every meaningful repair.",
            ]
        )

        return "\n".join(lines)

    @staticmethod
    def _to_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        method = getattr(value, "to_dict", None)
        if callable(method):
            try:
                result = method()
                return dict(result) if isinstance(result, dict) else {}
            except Exception:
                return {}
        return {}

    @classmethod
    def _passed(cls, value: Any) -> bool:
        data = cls._to_dict(value)
        return bool(data.get("passed", False))

    @classmethod
    def _failed(cls, test_result: Any, failure: Any) -> bool:
        if failure is not None:
            data = cls._to_dict(failure)
            if data.get("failed") is True:
                return True
        data = cls._to_dict(test_result)
        if "passed" in data:
            return not bool(data.get("passed"))
        return False

    @classmethod
    def _validation_ok(cls, value: Any) -> bool:
        if value is None:
            return True
        data = cls._to_dict(value)
        return bool(data.get("valid", False))

    @staticmethod
    def _collect_evidence(
        test_data: dict[str, Any],
        failure_data: dict[str, Any],
        validation_data: dict[str, Any],
        repository_summary: dict[str, Any],
    ) -> list[str]:
        result: list[str] = []

        for label, data in (
            ("test", test_data),
            ("failure", failure_data),
            ("validation", validation_data),
        ):
            if not data:
                continue
            summary = data.get("summary") or data.get("error")
            if summary:
                result.append(f"{label}: {str(summary)[:1200]}")
            for key in (
                "return_code", "timed_out", "stdout", "stderr",
                "command", "failure_category", "root_cause",
            ):
                if key in data and data[key] not in (None, "", [], {}):
                    value = str(data[key])
                    result.append(
                        f"{label}.{key}: {value[:1600]}"
                    )

        for key in (
            "file_count", "relevant_files", "confidence", "warnings",
        ):
            if key in repository_summary and repository_summary[key]:
                result.append(
                    f"repository.{key}: "
                    f"{str(repository_summary[key])[:1600]}"
                )

        return result[-40:]

    @staticmethod
    def _verification_focus(
        test_data: dict[str, Any],
        failure_data: dict[str, Any],
        validation_data: dict[str, Any],
    ) -> tuple[str, ...]:
        focus = [
            "Requirement acceptance criteria",
            "Static validation",
            "Targeted tests covering the changed behavior",
        ]

        if failure_data:
            focus.insert(
                0,
                "Exact failure command, exit status, stdout, stderr, and traceback",
            )

        if test_data.get("timed_out"):
            focus.insert(
                0,
                "Execution timeout/resource evidence before code changes",
            )

        if not validation_data.get("valid", True):
            focus.insert(0, "Static validation diagnostics")

        return tuple(dict.fromkeys(focus))

    @staticmethod
    def _repair_strategy(
        failure_data: dict[str, Any],
        test_data: dict[str, Any],
    ) -> tuple[str, ...]:
        if not failure_data and not test_data:
            return (
                "Establish observable evidence before modifying code.",
                "Use repository architecture and acceptance criteria to choose the repair.",
            )

        strategy = [
            "Reproduce or inspect the failure using the strongest available evidence.",
            "Separate environmental/tooling failures from product-code failures.",
            "Form a root-cause hypothesis before editing.",
            "Apply the smallest coherent repair.",
            "Retest and reassess instead of repeating the same repair blindly.",
        ]

        if failure_data.get("failure_category") in {None, "", "unknown"}:
            strategy.insert(
                0,
                "Unknown failure category is insufficient evidence; inspect raw execution output.",
            )

        return tuple(strategy)

    @staticmethod
    def _confidence(
        test_result: Any,
        failure: Any,
        validation: Any,
    ) -> str:
        test_data = AdaptiveEngineeringPlan._to_dict(test_result)
        failure_data = AdaptiveEngineeringPlan._to_dict(failure)
        validation_data = AdaptiveEngineeringPlan._to_dict(validation)

        if (
            test_data
            and "passed" in test_data
            and validation_data
            and "valid" in validation_data
            and not failure_data
        ):
            return "high"
        if failure_data or test_data:
            return "medium"
        return "low"

    @staticmethod
    def _to_dict_plan(plan: Any) -> dict[str, Any]:
        return AdaptiveEngineeringPlan._to_dict(plan)

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "requirement": self.requirement,
            "state": self.state,
            "original_plan": dict(self.original_plan),
            "evidence": list(self.evidence[-120:]),
            "revisions": [
                revision.to_dict()
                for revision in self.revisions[-30:]
            ],
        }
