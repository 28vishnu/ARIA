from typing import List, Dict, Any
from brain.models.decision import Decision
from brain.models.context import Context
from brain.memory.memory_router import MemoryRouter
from brain.plan import ExecutionPlan
from brain.task import Task

class Planner:
    """Converts a Decision and Context into a strongly-typed ExecutionPlan without performing execution."""
    def __init__(self, memory_router: MemoryRouter):
        self.memory_router = memory_router

    def plan(self, decision: Decision, context: Context) -> ExecutionPlan:
        """Generates a strongly-typed execution plan based on the active decision action."""
        action = decision.action
        tasks: List[Task] = []

        if action == "respond":
            goal = "Respond to user greeting"
            tasks = [
                Task(id="task_1", name="generate_greeting", parameters={})
            ]
        elif action == "answer":
            goal = "Answer user question with reasoning"
            tasks = [
                Task(id="task_1", name="reason_query", parameters={"query": context.intent.original_query if context.intent else ""}),
                Task(id="task_2", name="format_answer", parameters={})
            ]
        elif action == "summarize_document":
            goal = "Summarize uploaded document"
            tasks = [
                Task(id="task_1", name="load_document", parameters={"documents": context.documents}),
                Task(id="task_2", name="summarize_content", parameters={}),
                Task(id="task_3", name="format_summary", parameters={})
            ]
        elif action == "recall_memory":
            goal = "Retrieve information from memory"
            tasks = [
                Task(id="task_1", name="query_memory", parameters={"query": context.intent.original_query if context.intent else ""}),
                Task(id="task_2", name="format_memory_response", parameters={})
            ]
        elif action == "search_documents":
            goal = "Search available documents or memory"
            tasks = [
                Task(id="task_1", name="execute_search", parameters={"selected_skills": decision.selected_skills}),
                Task(id="task_2", name="format_search_results", parameters={})
            ]
        else:
            goal = "General conversation handle"
            tasks = [
                Task(id="task_1", name="default_chat", parameters={})
            ]

        return ExecutionPlan(goal=goal, tasks=tasks)
