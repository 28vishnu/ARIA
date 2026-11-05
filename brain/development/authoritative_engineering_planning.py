"""Phase 1 authoritative adapters for repository-aware planning and task graphs.

These adapters reuse ARIA's existing development planning services while keeping
the AuthoritativeEngineeringOrchestrator as the single lifecycle owner.
"""
from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any


class AuthoritativeRepositoryContext:
    """Read-only repository context bridge."""

    VERSION = "PHASE1-REPOSITORY-CONTEXT-20261005"

    def __init__(self, repository_engine: Any = None) -> None:
        self.repository_engine = repository_engine

    def inspect(self, repository_path: str | None = None) -> dict[str, Any]:
        path = str(repository_path or os.getcwd())
        engine = self.repository_engine
        if engine is None:
            return {"success": False, "error": "No repository engine is connected.", "repository_path": path}
        method = getattr(engine, "inspect", None)
        if not callable(method):
            return {"success": False, "error": "Repository engine does not expose inspect().", "repository_path": path}
        try:
            snapshot = method(path)
            return {
                "success": True,
                "repository_path": path,
                "snapshot": snapshot,
                "source": "repository_manager",
            }
        except Exception as exc:
            return {
                "success": False,
                "repository_path": path,
                "error": f"{type(exc).__name__}: {exc}",
            }


class AuthoritativePlanningAdapter:
    """Bridge the existing ChangePlanner into the authoritative plan stage."""

    VERSION = "PHASE1-PLANNING-ADAPTER-20261005"

    def __init__(self, *, change_planner: Any = None, repository_context: AuthoritativeRepositoryContext | None = None) -> None:
        self.change_planner = change_planner
        self.repository_context = repository_context or AuthoritativeRepositoryContext()

    async def build(self, requirement: Any, *, knowledge: Any = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        metadata = dict(metadata or {})
        repo = self._repository_context(knowledge)
        if not repo.get("success"):
            return {"success": False, "error": repo.get("error", "Repository inspection failed."), "repository_context": repo}

        planner = self.change_planner
        if planner is not None and callable(getattr(planner, "plan", None)):
            try:
                snapshot = repo.get("snapshot")
                existing_paths = self._existing_paths(snapshot)
                plan = planner.plan(
                    requirement,
                    existing_paths=existing_paths,
                    repository_path=repo.get("repository_path"),
                )
                if getattr(plan, "blocked", False):
                    return {
                        "success": False,
                        "blocked": True,
                        "error": getattr(plan, "block_reason", None) or "Change plan blocked.",
                        "plan": plan,
                        "repository_context": repo,
                    }
                return {
                    "success": True,
                    "plan": plan,
                    "repository_context": repo,
                    "metadata": {"adapter": self.VERSION, **metadata},
                }
            except Exception as exc:
                return {
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "repository_context": repo,
                }

        return {
            "success": False,
            "error": "No compatible ChangePlanner is connected.",
            "repository_context": repo,
        }

    def _repository_context(self, knowledge: Any) -> dict[str, Any]:
        if isinstance(knowledge, dict):
            value = knowledge.get("repository_context")
            if isinstance(value, dict):
                return value
        return self.repository_context.inspect()

    @staticmethod
    def _existing_paths(snapshot: Any) -> tuple[str, ...]:
        if snapshot is None:
            return ()
        files = getattr(snapshot, "files", None)
        if files is None and isinstance(snapshot, dict):
            files = snapshot.get("files", ())
        result = []
        for item in files or ():
            path = getattr(item, "path", None)
            if path is None and isinstance(item, dict):
                path = item.get("path")
            if path:
                result.append(str(path).replace("\\", "/"))
        return tuple(result)


class AuthoritativeTaskGraphAdapter:
    """Bridge the existing IntelligentTaskGraph into the authoritative graph stage."""

    VERSION = "PHASE1-TASK-GRAPH-ADAPTER-20261005"

    def __init__(self, *, task_graph_engine: Any = None) -> None:
        self.task_graph_engine = task_graph_engine

    async def build(self, requirement: Any, *, plan: Any = None, knowledge: Any = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        engine = self.task_graph_engine
        if engine is None or not callable(getattr(engine, "build", None)):
            return {"success": False, "error": "No compatible IntelligentTaskGraph is connected."}

        repository_reasoning = None
        if isinstance(knowledge, dict):
            repository_reasoning = knowledge.get("repository_context")

        changes = getattr(plan, "changes", ())
        tests = getattr(plan, "tests", ())
        try:
            graph = engine.build(
                requirement=requirement,
                plan=plan,
                repository_reasoning=repository_reasoning,
                generated_changes=changes,
                selected_tests=tests,
            )
            blocked = tuple(getattr(graph, "blocked_tasks", ()) or ())
            warnings = tuple(getattr(graph, "graph_warnings", ()) or ())
            if blocked:
                return {
                    "success": False,
                    "blocked": True,
                    "error": f"Task graph contains blocked tasks: {list(blocked)}",
                    "task_graph": graph,
                }
            return {
                "success": True,
                "task_graph": graph,
                "metadata": {
                    "adapter": self.VERSION,
                    "warnings": list(warnings),
                },
            }
        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


__all__ = [
    "AuthoritativeRepositoryContext",
    "AuthoritativePlanningAdapter",
    "AuthoritativeTaskGraphAdapter",
]
