from typing import Any, Dict, Iterator, List, Optional


class AgentWorkflow:
    """
    Represents an ordered workflow of specialised agents.

    The workflow stores execution steps and their results without
    executing agents itself. AgentCoordinator remains responsible
    for actual execution.
    """

    def __init__(
        self,
        name: str = "default",
        context: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.context = (
            context
            if isinstance(context, dict)
            else {}
        )

        self.agents: List[Any] = []
        self.steps: List[Dict[str, Any]] = []
        self.results: List[Dict[str, Any]] = []

        self.status = "created"

    def add(
        self,
        agent,
        task: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Add a specialist agent to the workflow.

        Existing callers using add(agent) remain compatible.
        """

        self.agents.append(agent)

        step = {
            "agent": getattr(
                agent,
                "name",
                agent,
            ),
            "task": task,
            "metadata": (
                metadata
                if isinstance(metadata, dict)
                else {}
            ),
            "status": "pending",
        }

        self.steps.append(step)

        return step

    def add_step(
        self,
        agent: str,
        task: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Add a named execution step without requiring the agent
        object to be available yet.
        """

        step = {
            "agent": agent,
            "task": task,
            "metadata": (
                metadata
                if isinstance(metadata, dict)
                else {}
            ),
            "status": "pending",
        }

        self.steps.append(step)

        return step

    def set_context(
        self,
        context: Optional[Dict[str, Any]],
    ):
        """
        Replace workflow context safely.
        """

        self.context = (
            dict(context)
            if isinstance(context, dict)
            else {}
        )

    def update_context(
        self,
        **values,
    ):
        """
        Add or update shared workflow context.
        """

        self.context.update(values)

    def record_result(
        self,
        agent: str,
        result: Any,
        success: bool = True,
        confidence: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Store the result of an executed workflow step.
        """

        record = {
            "agent": agent,
            "result": result,
            "success": bool(success),
            "confidence": float(
                confidence or 0.0
            ),
        }

        self.results.append(record)

        # Update matching pending step.
        for step in self.steps:
            if (
                step.get("agent") == agent
                and step.get("status") == "pending"
            ):
                step["status"] = (
                    "completed"
                    if success
                    else "failed"
                )
                break

        return record

    def get_results(self) -> List[Dict[str, Any]]:
        """
        Return workflow execution results.
        """

        return list(self.results)

    def pending_steps(self) -> List[Dict[str, Any]]:
        """
        Return steps that have not completed.
        """

        return [
            step
            for step in self.steps
            if step.get("status") == "pending"
        ]

    def start(self):
        """
        Mark the workflow as ready for execution.
        """

        self.status = "running"

    def complete(self):
        """
        Mark the workflow as completed.
        """

        self.status = "completed"

    def fail(self):
        """
        Mark the workflow as failed.
        """

        self.status = "failed"

    def __iter__(self) -> Iterator[Any]:
        return iter(self.agents)

    def __len__(self) -> int:
        return len(self.agents)

    def __repr__(self) -> str:
        return (
            f"AgentWorkflow("
            f"name={self.name!r}, "
            f"agents={len(self.agents)}, "
            f"steps={len(self.steps)}, "
            f"status={self.status!r}"
            f")"
        )