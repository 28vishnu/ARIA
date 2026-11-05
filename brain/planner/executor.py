class PlanExecutor:

    async def execute(self, plan):

        for step in plan.steps:
            step.completed = True

        return plan
