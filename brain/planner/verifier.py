class PlanVerifier:

    async def verify(self, plan):

        return all(step.completed for step in plan.steps)
