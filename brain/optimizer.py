from brain.plan import ExecutionPlan


class PlanOptimizer:
    """
    Optimizes an execution plan before it reaches the Executor.
    """

    def optimize(self, plan: ExecutionPlan) -> ExecutionPlan:
        if not plan or not plan.tasks:
            return plan

        # Remove duplicate tasks
        unique = []
        seen = set()

        for task in plan.tasks:
            key = (task.name, task.task_type)

            if key not in seen:
                seen.add(key)
                unique.append(task)

        plan.tasks = unique

        # Highest priority first
        plan.tasks.sort(
            key=lambda t: getattr(t, "priority", 0),
            reverse=True,
        )

        return plan
