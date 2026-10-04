"""Unified lifecycle contract for ARIA autonomous engineering.

Step 4 defines the lifecycle coordinator around EngineeringSession.

The lifecycle coordinator:
- owns phase progression
- records transitions
- prevents independent subsystem state
- exposes lifecycle hooks for future integration

It does not itself edit files, execute commands, deploy, push GitHub,
or invent engineering decisions. Those remain specialized responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

from .engineering_session import (
    EngineeringSession,
    SessionTransition,
)
from .engineering_state import EngineeringPhase


LifecycleHook = Callable[
    [EngineeringSession],
    Awaitable[None] | None,
]


@dataclass(frozen=True)
class LifecycleStep:
    """Description of one canonical engineering phase."""

    phase: EngineeringPhase
    description: str
    required_before: tuple[EngineeringPhase, ...] = ()
    terminal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "description": self.description,
            "required_before": [
                item.value
                for item in self.required_before
            ],
            "terminal": self.terminal,
        }


@dataclass
class LifecycleExecution:
    """Auditable lifecycle execution information."""

    session_id: str
    started: bool = False
    completed: bool = False
    transitions: list[SessionTransition] = field(
        default_factory=list
    )
    errors: list[str] = field(
        default_factory=list
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started": self.started,
            "completed": self.completed,
            "transitions": [
                item.to_dict()
                for item in self.transitions
            ],
            "errors": list(self.errors),
        }


class EngineeringLifecycle:
    """Canonical lifecycle coordinator.

    This class becomes the bridge between ARIA's existing specialized
    engineering services and the authoritative EngineeringSession.

    Future steps will attach:
        requirement -> repository -> planning -> graph -> implementation
        -> verification -> testing -> diagnosis -> recovery -> acceptance

    The lifecycle itself remains deliberately policy-light. It provides
    deterministic state ownership and transition recording.
    """

    VERSION = "PHASE1-ENGINEERING-LIFECYCLE-20261004"

    STEPS: tuple[LifecycleStep, ...] = (
        LifecycleStep(
            phase=EngineeringPhase.CREATED,
            description="Engineering session created.",
        ),
        LifecycleStep(
            phase=EngineeringPhase.UNDERSTANDING,
            description=(
                "Understand the requirement and inspect the repository."
            ),
            required_before=(
                EngineeringPhase.CREATED,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.PLANNING,
            description=(
                "Build the adaptive engineering plan."
            ),
            required_before=(
                EngineeringPhase.UNDERSTANDING,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.GRAPH_READY,
            description=(
                "Build and validate the engineering task graph."
            ),
            required_before=(
                EngineeringPhase.PLANNING,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.IMPLEMENTING,
            description=(
                "Implement the highest-priority ready work."
            ),
            required_before=(
                EngineeringPhase.GRAPH_READY,
                EngineeringPhase.REASSESSING,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.VERIFYING,
            description=(
                "Verify implementation and gather evidence."
            ),
            required_before=(
                EngineeringPhase.IMPLEMENTING,
                EngineeringPhase.RETESTING,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.TESTING,
            description=(
                "Run relevant targeted and required tests."
            ),
            required_before=(
                EngineeringPhase.VERIFYING,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.DIAGNOSING,
            description=(
                "Determine the root cause of a failure."
            ),
            required_before=(
                EngineeringPhase.TESTING,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.RECOVERING,
            description=(
                "Apply a justified repair based on evidence."
            ),
            required_before=(
                EngineeringPhase.DIAGNOSING,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.RETESTING,
            description=(
                "Retest after recovery."
            ),
            required_before=(
                EngineeringPhase.RECOVERING,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.REASSESSING,
            description=(
                "Reassess the plan and task graph using new evidence."
            ),
            required_before=(
                EngineeringPhase.RETESTING,
                EngineeringPhase.VERIFYING,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.ACCEPTING,
            description=(
                "Make the final engineering acceptance decision."
            ),
            required_before=(
                EngineeringPhase.VERIFYING,
                EngineeringPhase.TESTING,
                EngineeringPhase.REASSESSING,
            ),
        ),
        LifecycleStep(
            phase=EngineeringPhase.ACCEPTED,
            description=(
                "Requirement and acceptance criteria are genuinely satisfied."
            ),
            required_before=(
                EngineeringPhase.ACCEPTING,
            ),
            terminal=True,
        ),
        LifecycleStep(
            phase=EngineeringPhase.BLOCKED,
            description=(
                "Engineering cannot continue without an external dependency."
            ),
            terminal=True,
        ),
        LifecycleStep(
            phase=EngineeringPhase.FAILED,
            description=(
                "Engineering ended without satisfying the requirement."
            ),
            terminal=True,
        ),
    )

    def __init__(
        self,
        session: EngineeringSession,
        *,
        hooks: dict[
            EngineeringPhase,
            Sequence[LifecycleHook],
        ] | None = None,
    ) -> None:
        if not isinstance(
            session,
            EngineeringSession,
        ):
            raise TypeError(
                "EngineeringLifecycle requires an EngineeringSession."
            )

        self.session = session

        self._hooks: dict[
            EngineeringPhase,
            tuple[LifecycleHook, ...],
        ] = {
            phase: tuple(items)
            for phase, items in (
                hooks or {}
            ).items()
        }

        self._execution = LifecycleExecution(
            session_id=session.session_id
        )

    # ------------------------------------------------------------------
    # Lifecycle information
    # ------------------------------------------------------------------

    @classmethod
    def definition(cls) -> tuple[LifecycleStep, ...]:
        """Return the canonical lifecycle definition."""

        return cls.STEPS

    @classmethod
    def step(
        cls,
        phase: EngineeringPhase,
    ) -> LifecycleStep:
        for item in cls.STEPS:
            if item.phase is phase:
                return item

        raise KeyError(
            f"No lifecycle definition exists for {phase.value}."
        )

    @property
    def execution(self) -> LifecycleExecution:
        return self._execution

    @property
    def phase(self) -> EngineeringPhase:
        return self.session.phase

    @property
    def completed(self) -> bool:
        return self._execution.completed

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------

    async def start(self) -> LifecycleExecution:
        """Start the lifecycle at UNDERSTANDING.

        No engineering work is executed here. This only establishes the
        authoritative lifecycle state. Actual subsystem execution is added
        by later integration steps.
        """

        if self._execution.started:
            return self._execution

        self._execution.started = True

        if self.session.phase is EngineeringPhase.CREATED:
            transition = self.session.transition(
                EngineeringPhase.UNDERSTANDING,
                reason=(
                    "Autonomous engineering lifecycle started."
                ),
                metadata={
                    "lifecycle_version": self.VERSION,
                },
            )

            self._execution.transitions.append(
                transition
            )

        await self._run_hooks(
            EngineeringPhase.UNDERSTANDING
        )

        return self._execution

    async def advance(
        self,
        phase: EngineeringPhase,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        """Advance the authoritative session to a specific phase."""

        if not self._execution.started:
            raise RuntimeError(
                "Engineering lifecycle has not been started."
            )

        if self.session.terminal:
            raise RuntimeError(
                "Engineering lifecycle is already terminal: "
                f"{self.session.phase.value}"
            )

        self._validate_transition(
            phase
        )

        transition = self.session.transition(
            phase,
            reason=reason,
            metadata=metadata,
        )

        self._execution.transitions.append(
            transition
        )

        await self._run_hooks(
            phase
        )

        if phase in (
            EngineeringPhase.ACCEPTED,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        ):
            self._execution.completed = True

        return transition

    async def accept(
        self,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        """Enter ACCEPTED after acceptance has been explicitly decided."""

        if self.session.phase is not EngineeringPhase.ACCEPTING:
            raise RuntimeError(
                "Acceptance must be entered through the ACCEPTING phase."
            )

        acceptance = self.session.state.acceptance

        if not bool(
            acceptance.get(
                "requirement_satisfied",
                False,
            )
        ):
            raise RuntimeError(
                "Cannot accept engineering work before the "
                "requirement is satisfied."
            )

        if not bool(
            acceptance.get(
                "acceptance_satisfied",
                False,
            )
        ):
            raise RuntimeError(
                "Cannot accept engineering work before all "
                "acceptance criteria are satisfied."
            )

        return await self.advance(
            EngineeringPhase.ACCEPTED,
            reason=reason,
            metadata=metadata,
        )

    async def block(
        self,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        """Terminate the lifecycle as externally blocked."""

        return await self.advance(
            EngineeringPhase.BLOCKED,
            reason=reason,
            metadata=metadata,
        )

    async def fail(
        self,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        """Terminate the lifecycle as failed."""

        return await self.advance(
            EngineeringPhase.FAILED,
            reason=reason,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Hook registration
    # ------------------------------------------------------------------

    def register_hook(
        self,
        phase: EngineeringPhase,
        hook: LifecycleHook,
    ) -> None:
        """Register a future subsystem hook for a lifecycle phase."""

        if not callable(hook):
            raise TypeError(
                "Lifecycle hook must be callable."
            )

        existing = self._hooks.get(
            phase,
            (),
        )

        self._hooks[phase] = (
            *existing,
            hook,
        )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "session": self.session.snapshot(),
            "execution": self._execution.to_dict(),
            "definition": [
                item.to_dict()
                for item in self.STEPS
            ],
        }

    # ------------------------------------------------------------------
    # Internal validation
    # ------------------------------------------------------------------

    def _validate_transition(
        self,
        target: EngineeringPhase,
    ) -> None:
        current = self.session.phase

        if target is current:
            return

        definition = self.step(
            target
        )

        if not definition.required_before:
            return

        allowed_previous = set(
            definition.required_before
        )

        if current not in allowed_previous:
            raise RuntimeError(
                "Invalid engineering lifecycle transition: "
                f"{current.value} -> {target.value}. "
                f"Expected one of: "
                f"{sorted(item.value for item in allowed_previous)}"
            )

    async def _run_hooks(
        self,
        phase: EngineeringPhase,
    ) -> None:
        for hook in self._hooks.get(
            phase,
            (),
        ):
            result = hook(
                self.session
            )

            if hasattr(
                result,
                "__await__",
            ):
                await result


__all__ = [
    "LifecycleHook",
    "LifecycleStep",
    "LifecycleExecution",
    "EngineeringLifecycle",
]