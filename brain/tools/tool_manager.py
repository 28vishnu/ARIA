import asyncio
import logging
import time
from typing import List, Optional, Dict, Any, Tuple

from brain.tools.base_tool import BaseTool

logger = logging.getLogger("aria")


class ToolManager:
    """
    Central orchestration layer for ARIA tools.

    Responsibilities:
    - Register and retrieve tools safely.
    - Select the best tool for a query using confidence scores.
    - Execute tools through one controlled path.
    - Track usage, failures and execution latency.
    - Support aliases and tool availability checks from context.

    This class intentionally remains model-agnostic. It does not add any
    local LLM/Ollama dependency and works with the existing BaseTool API.
    """

    def __init__(
        self,
        selection_threshold: float = 0.25,
        execution_timeout: float = 60.0,
    ):
        self.tools: List[BaseTool] = []
        self.tool_usage: Dict[str, int] = {}
        self.tool_failures: Dict[str, int] = {}
        self.tool_latency: Dict[str, float] = {}
        self.tool_aliases: Dict[str, str] = {}

        self.selection_threshold = max(0.0, min(1.0, selection_threshold))
        self.execution_timeout = max(1.0, execution_timeout)
        self._lock = asyncio.Lock()

    def register(
        self,
        tool: BaseTool,
        aliases: Optional[List[str]] = None,
    ) -> BaseTool:
        """Register a tool once and optionally register lookup aliases."""
        if not isinstance(tool, BaseTool):
            raise TypeError("tool must inherit from BaseTool")

        name = str(tool.name).strip()
        if not name:
            raise ValueError("tool.name cannot be empty")

        existing = self.get(name)
        if existing is not None:
            logger.warning(
                "[ToolManager] Tool already registered: %s; keeping existing instance",
                name,
            )
            return existing

        self.tools.append(tool)
        self.tool_usage[name] = 0
        self.tool_failures[name] = 0
        self.tool_latency[name] = 0.0

        for alias in aliases or []:
            alias_name = str(alias).strip().lower()
            if alias_name and alias_name != name.lower():
                self.tool_aliases[alias_name] = name

        logger.info("[ToolManager] Registered tool: %s", name)
        return tool

    def unregister(self, name: str) -> bool:
        """Remove a tool and its aliases. Returns True when removed."""
        tool = self.get(name)
        if tool is None:
            return False

        canonical = tool.name
        self.tools = [item for item in self.tools if item.name != canonical]
        self.tool_usage.pop(canonical, None)
        self.tool_failures.pop(canonical, None)
        self.tool_latency.pop(canonical, None)

        self.tool_aliases = {
            alias: target
            for alias, target in self.tool_aliases.items()
            if target != canonical
        }

        logger.info("[ToolManager] Unregistered tool: %s", canonical)
        return True

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by canonical name or registered alias."""
        if not name:
            return None

        requested = str(name).strip()
        canonical = self.tool_aliases.get(requested.lower(), requested)

        for tool in self.tools:
            if tool.name == canonical:
                return tool
        return None

    def list_tools(self) -> List[str]:
        """Return registered canonical tool names."""
        return [tool.name for tool in self.tools]

    def tool_status(self) -> List[Dict[str, Any]]:
        """Return safe operational statistics for every registered tool."""
        return [
            {
                "name": tool.name,
                "usage": self.tool_usage.get(tool.name, 0),
                "failures": self.tool_failures.get(tool.name, 0),
                "average_latency": round(self.tool_latency.get(tool.name, 0.0), 4),
            }
            for tool in self.tools
        ]

    @staticmethod
    def _tool_is_available(
        tool: BaseTool,
        context: Dict[str, Any],
    ) -> bool:
        """
        Optional availability gate.

        A tool may expose `is_available(context)` without changing BaseTool.
        Existing tools remain fully compatible.
        """
        checker = getattr(tool, "is_available", None)
        if checker is None:
            return True

        try:
            result = checker(context)
            return bool(result)
        except Exception:
            logger.exception(
                "[ToolManager] Availability check failed for %s",
                tool.name,
            )
            return False

    async def select_tool(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> Optional[BaseTool]:
        """Select the highest-confidence available tool above the threshold."""
        if not query or not str(query).strip():
            return None

        context = context or {}
        candidates: List[Tuple[float, int, BaseTool]] = []

        for index, tool in enumerate(self.tools):
            if not self._tool_is_available(tool, context):
                logger.info("[ToolManager] %s unavailable", tool.name)
                continue

            try:
                raw_score = await tool.can_handle(query, context)
                score = float(raw_score)
            except Exception:
                logger.exception(
                    "[ToolManager] can_handle failed for %s",
                    tool.name,
                )
                self.tool_failures[tool.name] = self.tool_failures.get(tool.name, 0) + 1
                continue

            if score != score:  # NaN guard
                score = 0.0
            score = max(0.0, min(1.0, score))

            logger.info(
                "[ToolManager] %s score=%.2f",
                tool.name,
                score,
            )

            if score >= self.selection_threshold:
                candidates.append((score, index, tool))

        if not candidates:
            logger.info(
                "[ToolManager] No tool exceeded selection threshold %.2f",
                self.selection_threshold,
            )
            return None

        # Highest score wins. On an exact tie, preserve registration order.
        candidates.sort(key=lambda item: (-item[0], item[1]))
        best_score, _, best_tool = candidates[0]

        logger.info(
            "[ToolManager] Selected %s with score=%.2f",
            best_tool.name,
            best_score,
        )
        return best_tool

    async def execute(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        tool_name: Optional[str] = None,
    ) -> Any:
        """
        Execute a named tool or automatically select the best tool.

        Returns the tool's native result. If no tool can handle the query,
        returns None rather than inventing a result.
        """
        context = dict(context or {})

        async with self._lock:
            tool = self.get(tool_name) if tool_name else await self.select_tool(query, context)

            if tool is None:
                logger.info("[ToolManager] No executable tool found for query")
                return None

            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    tool.execute(query, context),
                    timeout=self.execution_timeout,
                )

                elapsed = time.perf_counter() - started
                self.tool_usage[tool.name] = self.tool_usage.get(tool.name, 0) + 1

                previous = self.tool_latency.get(tool.name, 0.0)
                usage = self.tool_usage[tool.name]
                self.tool_latency[tool.name] = (
                    ((previous * (usage - 1)) + elapsed) / usage
                )

                logger.info(
                    "[ToolManager] Executed %s in %.3fs",
                    tool.name,
                    elapsed,
                )
                return result

            except asyncio.TimeoutError:
                self.tool_failures[tool.name] = self.tool_failures.get(tool.name, 0) + 1
                logger.error(
                    "[ToolManager] Tool timed out: %s after %.1fs",
                    tool.name,
                    self.execution_timeout,
                )
                return None

            except Exception:
                self.tool_failures[tool.name] = self.tool_failures.get(tool.name, 0) + 1
                logger.exception(
                    "[ToolManager] Tool execution failed: %s",
                    tool.name,
                )
                return None

    def most_used_tools(self):
        return sorted(
            self.tool_usage.items(),
            key=lambda x: x[1],
            reverse=True,
        )

    def reset_statistics(self):
        for tool in self.tool_usage:
            self.tool_usage[tool] = 0

        for tool in self.tool_failures:
            self.tool_failures[tool] = 0

        for tool in self.tool_latency:
            self.tool_latency[tool] = 0.0
