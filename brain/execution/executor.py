from typing import List, Dict, Any, Callable
from brain.plan import ExecutionPlan
from brain.task import Task

class Executor:
    """Executes the tasks defined in an ExecutionPlan sequentially using a scalable handler registry pattern."""
    def __init__(self):
        self.handlers: Dict[str, Callable[[Task], Dict[str, Any]]] = {
            "generate_greeting": self._generate_greeting,
            "reason_query": self._reason_query,
            "load_document": self._load_document,
            "summarize_content": self._summarize_content,
            "format_summary": self._format_summary,
            "query_memory": self._query_memory,
            "format_memory_response": self._format_memory_response,
            "execute_search": self._execute_search,
            "format_search_results": self._format_search_results,
        }

    def execute(self, plan: ExecutionPlan) -> List[Dict[str, Any]]:
        """Iterates through all tasks in the execution plan and executes them via handlers."""
        results: List[Dict[str, Any]] = []

        for task in plan.tasks:
            result = self.execute_task(task)
            results.append(result)

        return results

    def execute_task(self, task: Task) -> Dict[str, Any]:
        """Dispatches an individual task to its registered handler."""
        handler = self.handlers.get(task.name, self._default_handler)
        return handler(task)

    def _generate_greeting(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": "completed",
            "output": "Hello! How can I assist you today?"
        }

    def _reason_query(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": "completed",
            "output": "Reasoned analysis completed for the query."
        }

    def _load_document(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": "completed",
            "output": "Target documents loaded into active context."
        }

    def _summarize_content(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": "completed",
            "output": "Document summary generated successfully."
        }

    def _format_summary(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": "completed",
            "output": "Formatted summary ready for presentation."
        }

    def _query_memory(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": "completed",
            "output": "Relevant past information retrieved from memory."
        }

    def _format_memory_response(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": "completed",
            "output": "Memory response formatted."
        }

    def _execute_search(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": "completed",
            "output": "Search execution complete."
        }

    def _format_search_results(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": "completed",
            "output": "Search results formatted."
        }

    def _default_handler(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": "completed",
            "output": "Default conversational response generated."
        }
