from brain.planner.models import ExecutionPlan


class Planner:

    async def create_plan(self, goal: str):

        plan = ExecutionPlan(goal)

        plan.add_step(
            "Understand Goal",
            "Understand what the user wants."
        )

        plan.add_step(
            "Choose Skills",
            "Determine which skills are required."
        )

        plan.add_step(
            "Execute",
            "Execute required actions."
        )

        plan.add_step(
            "Verify",
            "Verify the result."
        )

        return plan
