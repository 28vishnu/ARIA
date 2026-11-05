from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable


logger = logging.getLogger("aria")


class EngineeringPhase(str, Enum):
    CREATED = "created"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    GRAPH_READY = "graph_ready"
    IMPLEMENTING = "implementing"
    VERIFYING = "verifying"
    TESTING = "testing"
    DIAGNOSING = "diagnosing"
    RECOVERING = "recovering"
    RETESTING = "retesting"
    REASSESSING = "reassessing"
    ACCEPTING = "accepting"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class LifecycleHook:
    """
    Callback registered against a lifecycle transition.

    Hooks are observational only. They cannot bypass lifecycle
    transition validation.
    """

    name: str
    callback: Callable[..., Any]


@dataclass(frozen=True)
class LifecycleStep:
    """
    Immutable description of a lifecycle transition.
    """

    sequence: int
    from_phase: EngineeringPhase | None
    to_phase: EngineeringPhase
    reason: str = ""
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "from_phase": (
                self.from_phase.value
                if self.from_phase
                else None
            ),
            "to_phase": self.to_phase.value,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class LifecycleExecution:
    """
    Complete lifecycle execution record.
    """

    success: bool
    phase: EngineeringPhase
    steps: tuple[LifecycleStep, ...] = ()
    error: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "phase": self.phase.value,
            "steps": [
                step.to_dict()
                for step in self.steps
            ],
            "error": self.error,
            "metadata": dict(self.metadata),
        }


# Compatibility alias used by older integrations.
LifecycleExecutionRecord = LifecycleExecution


class EngineeringLifecycle:
    """
    Canonical engineering lifecycle state machine.

    This class owns lifecycle transition validity only.

    It does NOT:
      - execute code
      - run shell commands
      - write repository files
      - push GitHub
      - deploy
      - authorize protected actions

    Those responsibilities remain in their respective boundaries.
    """

    # ------------------------------------------------------------
    # Canonical transition graph
    # ------------------------------------------------------------

    _TRANSITIONS: dict[
        EngineeringPhase,
        set[EngineeringPhase],
    ] = {
        EngineeringPhase.CREATED: {
            EngineeringPhase.UNDERSTANDING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.UNDERSTANDING: {
            EngineeringPhase.PLANNING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.PLANNING: {
            EngineeringPhase.GRAPH_READY,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.GRAPH_READY: {
            EngineeringPhase.IMPLEMENTING,
            EngineeringPhase.VERIFYING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.IMPLEMENTING: {
            EngineeringPhase.VERIFYING,
            EngineeringPhase.TESTING,
            EngineeringPhase.DIAGNOSING,
            EngineeringPhase.RECOVERING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.VERIFYING: {
            EngineeringPhase.TESTING,
            EngineeringPhase.DIAGNOSING,
            EngineeringPhase.RECOVERING,
            EngineeringPhase.REASSESSING,
            EngineeringPhase.ACCEPTING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.TESTING: {
            EngineeringPhase.DIAGNOSING,
            EngineeringPhase.RECOVERING,
            EngineeringPhase.RETESTING,
            EngineeringPhase.REASSESSING,
            EngineeringPhase.ACCEPTING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.DIAGNOSING: {
            EngineeringPhase.RECOVERING,
            EngineeringPhase.IMPLEMENTING,
            EngineeringPhase.TESTING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.RECOVERING: {
            EngineeringPhase.RETESTING,
            EngineeringPhase.IMPLEMENTING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.RETESTING: {
            EngineeringPhase.REASSESSING,
            EngineeringPhase.DIAGNOSING,
            EngineeringPhase.RECOVERING,
            EngineeringPhase.ACCEPTING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.REASSESSING: {
            EngineeringPhase.IMPLEMENTING,
            EngineeringPhase.VERIFYING,
            EngineeringPhase.TESTING,
            EngineeringPhase.DIAGNOSING,
            EngineeringPhase.ACCEPTING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.ACCEPTING: {
            EngineeringPhase.ACCEPTED,
            EngineeringPhase.REASSESSING,
            EngineeringPhase.VERIFYING,
            EngineeringPhase.TESTING,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.ACCEPTED: {
            EngineeringPhase.ACCEPTED,
        },
        EngineeringPhase.BLOCKED: {
            EngineeringPhase.UNDERSTANDING,
            EngineeringPhase.PLANNING,
            EngineeringPhase.IMPLEMENTING,
            EngineeringPhase.VERIFYING,
            EngineeringPhase.FAILED,
        },
        EngineeringPhase.FAILED: {
            EngineeringPhase.UNDERSTANDING,
            EngineeringPhase.PLANNING,
            EngineeringPhase.IMPLEMENTING,
            EngineeringPhase.DIAGNOSING,
            EngineeringPhase.RECOVERING,
            EngineeringPhase.FAILED,
        },
    }

    def __init__(
        self,
        *,
        initial_phase: EngineeringPhase = (
            EngineeringPhase.CREATED
        ),
        hooks: Iterable[LifecycleHook] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.phase = self._coerce_phase(
            initial_phase
        )

        self.steps: list[
            LifecycleStep
        ] = []

        self.hooks: dict[
            str,
            list[LifecycleHook],
        ] = {}

        self.metadata: dict[str, Any] = dict(
            metadata
            or {}
        )

        if hooks:
            for hook in hooks:
                self.add_hook(hook)

    # ------------------------------------------------------------
    # Phase helpers
    # ------------------------------------------------------------

    @staticmethod
    def _coerce_phase(
        value: Any,
    ) -> EngineeringPhase:
        if isinstance(
            value,
            EngineeringPhase,
        ):
            return value

        return EngineeringPhase(
            str(value)
            .strip()
            .lower()
        )

    @property
    def current_phase(
        self,
    ) -> EngineeringPhase:
        return self.phase

    @property
    def current(
        self,
    ) -> str:
        return self.phase.value

    @property
    def history(
        self,
    ) -> tuple[LifecycleStep, ...]:
        return tuple(
            self.steps
        )

    @property
    def is_terminal(
        self,
    ) -> bool:
        return self.phase in {
            EngineeringPhase.ACCEPTED,
            EngineeringPhase.FAILED,
            EngineeringPhase.BLOCKED,
        }

    # ------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------

    def add_hook(
        self,
        hook: LifecycleHook,
    ) -> None:
        if not isinstance(
            hook,
            LifecycleHook,
        ):
            raise TypeError(
                "hook must be a LifecycleHook"
            )

        self.hooks.setdefault(
            hook.name,
            [],
        ).append(hook)

    def register_hook(
        self,
        name: str,
        callback: Callable[..., Any],
    ) -> LifecycleHook:
        hook = LifecycleHook(
            name=str(name),
            callback=callback,
        )

        self.add_hook(
            hook
        )

        return hook

    def _run_hooks(
        self,
        step: LifecycleStep,
    ) -> None:
        """
        Hooks are best-effort observers.

        A hook failure never corrupts the lifecycle transition.
        """

        hook_names = (
            "transition",
            step.to_phase.value,
        )

        for hook_name in hook_names:
            for hook in self.hooks.get(
                hook_name,
                (),
            ):
                try:
                    result = hook.callback(
                        step
                    )

                    # Lifecycle itself remains synchronous.
                    # Async hooks are intentionally not awaited here.
                    if hasattr(
                        result,
                        "__await__",
                    ):
                        logger.warning(
                            "[EngineeringLifecycle] "
                            "Async hook ignored | hook=%s",
                            hook.name,
                        )

                except Exception:
                    logger.exception(
                        "[EngineeringLifecycle] "
                        "Lifecycle hook failed | hook=%s",
                        hook.name,
                    )

    # ------------------------------------------------------------
    # Transition validation
    # ------------------------------------------------------------

    def can_transition(
        self,
        target: EngineeringPhase | str,
    ) -> bool:
        target_phase = self._coerce_phase(
            target
        )

        return target_phase in (
            self._TRANSITIONS.get(
                self.phase,
                set(),
            )
        )

    def allowed_transitions(
        self,
    ) -> tuple[EngineeringPhase, ...]:
        return tuple(
            self._TRANSITIONS.get(
                self.phase,
                set(),
            )
        )

    def require_transition(
        self,
        target: EngineeringPhase | str,
    ) -> None:
        target_phase = self._coerce_phase(
            target
        )

        if not self.can_transition(
            target_phase
        ):
            raise RuntimeError(
                "Invalid engineering lifecycle "
                f"transition: "
                f"{self.phase.value} -> "
                f"{target_phase.value}"
            )

    # ------------------------------------------------------------
    # Core transition
    # ------------------------------------------------------------

    def transition(
        self,
        target: EngineeringPhase | str,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        force: bool = False,
    ) -> LifecycleStep:
        target_phase = self._coerce_phase(
            target
        )

        if not force:
            self.require_transition(
                target_phase
            )

        previous = self.phase

        step = LifecycleStep(
            sequence=len(
                self.steps
            ) + 1,
            from_phase=previous,
            to_phase=target_phase,
            reason=str(
                reason
                or ""
            ),
            metadata=dict(
                metadata
                or {}
            ),
        )

        self.phase = target_phase
        self.steps.append(
            step
        )

        self._run_hooks(
            step
        )

        logger.info(
            "[EngineeringLifecycle] "
            "%s -> %s | reason=%s",
            previous.value,
            target_phase.value,
            reason,
        )

        return step

    # ------------------------------------------------------------
    # Canonical phase methods
    # ------------------------------------------------------------

    def mark_created(
        self,
        *,
        reason: str = "Engineering session created.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        if self.phase == EngineeringPhase.CREATED:
            return self._record_same_phase(
                reason=reason,
                metadata=metadata,
            )

        return self.transition(
            EngineeringPhase.CREATED,
            reason=reason,
            metadata=metadata,
        )

    def mark_understanding(
        self,
        *,
        reason: str = "Requirement understanding started.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.UNDERSTANDING,
            reason=reason,
            metadata=metadata,
        )

    def mark_planning(
        self,
        *,
        reason: str = "Engineering planning started.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.PLANNING,
            reason=reason,
            metadata=metadata,
        )

    def mark_graph_ready(
        self,
        *,
        reason: str = "Engineering task graph is ready.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.GRAPH_READY,
            reason=reason,
            metadata=metadata,
        )

    def mark_implementing(
        self,
        *,
        reason: str = "Implementation started.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.IMPLEMENTING,
            reason=reason,
            metadata=metadata,
        )

    def mark_verifying(
        self,
        *,
        reason: str = "Verification started.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.VERIFYING,
            reason=reason,
            metadata=metadata,
        )

    def mark_testing(
        self,
        *,
        reason: str = "Testing started.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.TESTING,
            reason=reason,
            metadata=metadata,
        )

    def mark_diagnosing(
        self,
        *,
        reason: str = "Failure diagnosis started.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.DIAGNOSING,
            reason=reason,
            metadata=metadata,
        )

    def mark_recovering(
        self,
        *,
        reason: str = "Recovery started.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.RECOVERING,
            reason=reason,
            metadata=metadata,
        )

    def mark_retesting(
        self,
        *,
        reason: str = "Retesting started.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.RETESTING,
            reason=reason,
            metadata=metadata,
        )

    def mark_reassessing(
        self,
        *,
        reason: str = "Engineering result is being reassessed.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.REASSESSING,
            reason=reason,
            metadata=metadata,
        )

    def mark_accepting(
        self,
        *,
        reason: str = "Acceptance evaluation started.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.ACCEPTING,
            reason=reason,
            metadata=metadata,
        )

    def mark_accepted(
        self,
        *,
        reason: str = "Engineering requirement accepted.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        return self.transition(
            EngineeringPhase.ACCEPTED,
            reason=reason,
            metadata=metadata,
        )

    def mark_blocked(
        self,
        *,
        reason: str = "Engineering operation blocked.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        if self.phase == EngineeringPhase.BLOCKED:
            return self._record_same_phase(
                reason=reason,
                metadata=metadata,
            )

        return self.transition(
            EngineeringPhase.BLOCKED,
            reason=reason,
            metadata=metadata,
        )

    def mark_failed(
        self,
        *,
        reason: str = "Engineering operation failed.",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleStep:
        if self.phase == EngineeringPhase.FAILED:
            return self._record_same_phase(
                reason=reason,
                metadata=metadata,
            )

        return self.transition(
            EngineeringPhase.FAILED,
            reason=reason,
            metadata=metadata,
        )

    # ------------------------------------------------------------
    # Same-phase records
    # ------------------------------------------------------------

    def _record_same_phase(
        self,
        *,
        reason: str,
        metadata: dict[str, Any] | None,
    ) -> LifecycleStep:
        step = LifecycleStep(
            sequence=len(
                self.steps
            ) + 1,
            from_phase=self.phase,
            to_phase=self.phase,
            reason=str(
                reason
                or ""
            ),
            metadata=dict(
                metadata
                or {}
            ),
        )

        self.steps.append(
            step
        )

        self._run_hooks(
            step
        )

        return step

    # ------------------------------------------------------------
    # Execution helper
    # ------------------------------------------------------------

    def execute(
        self,
        steps: Iterable[
            EngineeringPhase | str
        ],
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleExecution:
        start_index = len(
            self.steps
        )

        try:
            for target in steps:
                self.transition(
                    target,
                    reason=reason,
                    metadata=metadata,
                )

            return LifecycleExecution(
                success=True,
                phase=self.phase,
                steps=tuple(
                    self.steps[
                        start_index:
                    ]
                ),
                metadata=dict(
                    metadata
                    or {}
                ),
            )

        except Exception as exc:
            logger.exception(
                "[EngineeringLifecycle] "
                "Lifecycle execution failed."
            )

            return LifecycleExecution(
                success=False,
                phase=self.phase,
                steps=tuple(
                    self.steps[
                        start_index:
                    ]
                ),
                error=str(exc),
                metadata=dict(
                    metadata
                    or {}
                ),
            )

    # ------------------------------------------------------------
    # Snapshot / restore
    # ------------------------------------------------------------

    def snapshot(
        self,
    ) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "steps": [
                step.to_dict()
                for step in self.steps
            ],
            "metadata": dict(
                self.metadata
            ),
        }

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return self.snapshot()

    @classmethod
    def restore(
        cls,
        snapshot: dict[str, Any] | None,
    ) -> "EngineeringLifecycle":
        data = dict(
            snapshot
            or {}
        )

        phase = cls._coerce_phase(
            data.get(
                "phase",
                EngineeringPhase.CREATED.value,
            )
        )

        lifecycle = cls(
            initial_phase=phase,
            metadata=data.get(
                "metadata",
                {},
            ),
        )

        restored_steps: list[
            LifecycleStep
        ] = []

        for raw_step in data.get(
            "steps",
            [],
        ):
            if not isinstance(
                raw_step,
                dict,
            ):
                continue

            from_value = raw_step.get(
                "from_phase"
            )

            from_phase = (
                cls._coerce_phase(
                    from_value
                )
                if from_value
                else None
            )

            try:
                to_phase = cls._coerce_phase(
                    raw_step.get(
                        "to_phase"
                    )
                )
            except Exception:
                continue

            restored_steps.append(
                LifecycleStep(
                    sequence=int(
                        raw_step.get(
                            "sequence",
                            len(
                                restored_steps
                            )
                            + 1,
                        )
                    ),
                    from_phase=from_phase,
                    to_phase=to_phase,
                    reason=str(
                        raw_step.get(
                            "reason",
                            "",
                        )
                    ),
                    metadata=dict(
                        raw_step.get(
                            "metadata",
                            {},
                        )
                        or {}
                    ),
                )
            )

        lifecycle.steps = restored_steps

        # The persisted phase is authoritative for restoration.
        lifecycle.phase = phase

        return lifecycle

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict[str, Any] | None,
    ) -> "EngineeringLifecycle":
        return cls.restore(
            snapshot
        )

    # ------------------------------------------------------------
    # Status / health
    # ------------------------------------------------------------

    def status(
        self,
    ) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "terminal": self.is_terminal,
            "step_count": len(
                self.steps
            ),
            "allowed_transitions": [
                phase.value
                for phase in self.allowed_transitions()
            ],
        }

    def health(
        self,
    ) -> dict[str, Any]:
        return {
            "healthy": True,
            "phase": self.phase.value,
            "step_count": len(
                self.steps
            ),
        }