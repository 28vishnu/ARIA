from typing import List
from brain.models.decision import Decision
from brain.models.context import Context
from brain.memory.memory_router import MemoryRouter
from brain.plan import ExecutionPlan
from brain.task import Task

class Planner:
    """Converts a Decision and Context into a strongly-typed ExecutionPlan using explicit Task skills and inputs."""
    def __init__(self, memory_router: MemoryRouter):
        self.memory_router = memory_router

    def plan(self, decision: Decision, context: Context) -> ExecutionPlan:
        action = decision.action
        tasks: List[Task] = []

        if action == "respond":
            goal = "Respond to user greeting"
            tasks = [
                Task(id="task_1", name="generate_greeting", skill="chat", input={})
            ]
        elif action == "answer":
            goal = "Answer user question with reasoning"
            tasks = [
                Task(id="task_1", name="reason_query", skill="reasoning", input={"query": context.intent.original_query if context.intent else ""}),
                Task(id="task_2", name="format_answer", skill="chat", input={})
            ]
        elif action == "summarize_document":
            goal = "Summarize uploaded document"
            tasks = [
                Task(id="task_1", name="load_document", skill="document", input={"documents": context.documents}),
                Task(id="task_2", name="summarize_content", skill="document", input={}),
                Task(id="task_3", name="format_summary", skill="chat", input={})
            ]
        elif action == "recall_memory":
            goal = "Retrieve information from memory"
            tasks = [
                Task(id="task_1", name="query_memory", skill="memory", input={"query": context.intent.original_query if context.intent else ""}),
                Task(id="task_2", name="format_memory_response", skill="chat", input={})
            ]
        elif action == "search_documents":
            goal = "Search available documents or memory"
            tasks = [
                Task(id="task_1", name="execute_search", skill="search", input={"selected_skills": decision.selected_skills}),
                Task(id="task_2", name="format_search_results", skill="chat", input={})
            ]
        else:
            goal = "General conversation handle"
            tasks = [
                Task(id="task_1", name="default_chat", skill="chat", input={})
            ]

        return ExecutionPlan(goal=goal, tasks=tasks)
