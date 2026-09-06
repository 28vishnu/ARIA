import asyncio
import copy
import inspect
import logging
import time
from typing import List, Optional, Dict, Any, Tuple

from brain.tools.base_tool import BaseTool

logger = logging.getLogger("aria")


class ToolManager:
    """
    ARIA Phase-11 canonical tool orchestration layer.

    Responsibilities:
      - Register/retrieve tools safely.
      - Support canonical names and aliases.
      - Select the best available tool for a query.
      - Execute tools through one controlled path.
      - Enforce bounded execution time.
      - Track usage, failures, latency and recent execution state.
      - Expose capability/health information to the cognitive layer.

    This class remains model-agnostic and adds no local LLM/Ollama
    dependency.
    """

    VERSION = "11.7"
    DEFAULT_SELECTION_THRESHOLD = 0.25
    DEFAULT_EXECUTION_TIMEOUT = 60.0
    MAX_EXECUTION_TIMEOUT = 600.0
    MAX_HISTORY = 100

    def __init__(
        self,
        selection_threshold: float = DEFAULT_SELECTION_THRESHOLD,
        execution_timeout: float = DEFAULT_EXECUTION_TIMEOUT,
    ):
        self.tools: List[BaseTool] = []

        self.tool_usage: Dict[str, int] = {}
        self.tool_failures: Dict[str, int] = {}
        self.tool_latency: Dict[str, float] = {}
        self.tool_aliases: Dict[str, str] = {}

        self.selection_threshold = self._clamp(
            selection_threshold,
            0.0,
            1.0,
            self.DEFAULT_SELECTION_THRESHOLD,
        )

        self.execution_timeout = self._clamp(
            execution_timeout,
            1.0,
            self.MAX_EXECUTION_TIMEOUT,
            self.DEFAULT_EXECUTION_TIMEOUT,
        )

        self.execution_history: List[Dict[str, Any]] = []

        # Registration is normally startup-only, but this lock prevents
        # accidental concurrent mutation from corrupting registry state.
        self._lock = asyncio.Lock()

    # =========================================================
    # GENERIC HELPERS
    # =========================================================

    @staticmethod
    def _clamp(
        value: Any,
        minimum: float,
        maximum: float,
        default: float,
    ) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = default

        if numeric != numeric:  # NaN
            numeric = default

        return max(
            minimum,
            min(
                numeric,
                maximum,
            ),
        )

    @staticmethod
    def _normalize_name(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _normalize_alias(value: Any) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _safe_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return dict(
            context
            if isinstance(context, dict)
            else {}
        )

    @staticmethod
    def _result_success(result: Any) -> bool:
        if result is None:
            return False

        if isinstance(result, dict):
            if "success" in result:
                return bool(result.get("success"))
            return True

        success = getattr(
            result,
            "success",
            None,
        )

        if success is None:
            return True

        return bool(success)

    @staticmethod
    def _result_error(result: Any) -> Optional[str]:
        if result is None:
            return None

        if isinstance(result, dict):
            error = result.get("error")
        else:
            error = getattr(
                result,
                "error",
                None,
            )

        return str(error) if error else None

    def _record_history(
        self,
        entry: Dict[str, Any],
    ):
        self.execution_history.append(
            copy.deepcopy(entry)
        )

        if len(self.execution_history) > self.MAX_HISTORY:
            del self.execution_history[:-self.MAX_HISTORY]

    def _canonical_name(
        self,
        name: Any,
    ) -> str:
        requested = self._normalize_name(name)

        if not requested:
            return ""

        return self.tool_aliases.get(
            requested.lower(),
            requested,
        )

    # =========================================================
    # REGISTRATION
    # =========================================================

    def register(
        self,
        tool: BaseTool,
        aliases: Optional[List[str]] = None,
    ) -> BaseTool:
        """
        Register a tool exactly once.

        Duplicate registration returns the existing canonical instance.
        Alias collisions are replaced only when they point to the same
        canonical tool; unrelated collisions are rejected.
        """
        if not isinstance(tool, BaseTool):
            raise TypeError(
                "tool must inherit from BaseTool"
            )

        name = self._normalize_name(
            getattr(
                tool,
                "name",
                "",
            )
        )

        if not name:
            raise ValueError(
                "tool.name cannot be empty"
            )

        existing = self.get(name)

        if existing is not None:
            logger.warning(
                "[ToolManager] Tool already registered: %s; "
                "keeping existing instance.",
                name,
            )

            # Still allow missing aliases to be attached safely.
            self._register_aliases(
                existing.name,
                aliases or [],
            )

            return existing

        self.tools.append(tool)

        self.tool_usage[name] = 0
        self.tool_failures[name] = 0
        self.tool_latency[name] = 0.0

        self._register_aliases(
            name,
            aliases or [],
        )

        logger.info(
            "[ToolManager] Registered tool: %s",
            name,
        )

        return tool

    def _register_aliases(
        self,
        canonical_name: str,
        aliases: List[str],
    ):
        canonical = self._normalize_name(
            canonical_name
        )

        for alias in aliases:
            alias_name = self._normalize_alias(
                alias
            )

            if not alias_name:
                continue

            if alias_name == canonical.lower():
                continue

            existing_target = self.tool_aliases.get(
                alias_name
            )

            if (
                existing_target is not None
                and existing_target != canonical
            ):
                logger.warning(
                    "[ToolManager] Alias collision rejected: "
                    "%s -> %s (already maps to %s)",
                    alias_name,
                    canonical,
                    existing_target,
                )
                continue

            self.tool_aliases[
                alias_name
            ] = canonical

    def unregister(
        self,
        name: str,
    ) -> bool:
        """Remove a canonical tool and all aliases targeting it."""
        canonical = self._canonical_name(name)

        if not canonical:
            return False

        tool = next(
            (
                item
                for item in self.tools
                if item.name == canonical
            ),
            None,
        )

        if tool is None:
            return False

        self.tools = [
            item
            for item in self.tools
            if item.name != canonical
        ]

        self.tool_usage.pop(
            canonical,
            None,
        )
        self.tool_failures.pop(
            canonical,
            None,
        )
        self.tool_latency.pop(
            canonical,
            None,
        )

        self.tool_aliases = {
            alias: target
            for alias, target in self.tool_aliases.items()
            if target != canonical
        }

        logger.info(
            "[ToolManager] Unregistered tool: %s",
            canonical,
        )

        return True

    # =========================================================
    # LOOKUP / CAPABILITIES
    # =========================================================

    def get(
        self,
        name: str,
    ) -> Optional[BaseTool]:
        """Get a tool by canonical name or alias."""
        canonical = self._canonical_name(name)

        if not canonical:
            return None

        for tool in self.tools:
            if tool.name == canonical:
                return tool

        return None

    def list_tools(self) -> List[str]:
        """Return canonical registered tool names."""
        return [
            tool.name
            for tool in self.tools
        ]

    def capabilities(self) -> List[Dict[str, Any]]:
        """
        Return safe capability metadata without exposing internal objects.
        """
        return [
            {
                "name": tool.name,
                "description": str(
                    getattr(
                        tool,
                        "description",
                        "",
                    )
                    or ""
                ),
                "available": self._tool_is_available(
                    tool,
                    {},
                ),
            }
            for tool in self.tools
        ]

    def tool_status(self) -> List[Dict[str, Any]]:
        """Return operational statistics for registered tools."""
        return [
            {
                "name": tool.name,
                "usage": self.tool_usage.get(
                    tool.name,
                    0,
                ),
                "failures": self.tool_failures.get(
                    tool.name,
                    0,
                ),
                "average_latency": round(
                    self.tool_latency.get(
                        tool.name,
                        0.0,
                    ),
                    4,
                ),
            }
            for tool in self.tools
        ]

    # =========================================================
    # AVAILABILITY / SELECTION
    # =========================================================

    @staticmethod
    def _tool_is_available(
        tool: BaseTool,
        context: Dict[str, Any],
    ) -> bool:
        """
        Optional availability gate.

        Existing BaseTool implementations remain compatible.
        """
        checker = getattr(
            tool,
            "is_available",
            None,
        )

        if checker is None:
            return True

        try:
            result = checker(context)

            # Support both sync and async availability checks.
            if inspect.isawaitable(result):
                logger.warning(
                    "[ToolManager] Async is_available() is not supported "
                    "by the synchronous availability interface for %s; "
                    "treating it as unavailable.",
                    tool.name,
                )
                return False

            return bool(result)

        except Exception:
            logger.exception(
                "[ToolManager] Availability check failed for %s.",
                tool.name,
            )
            return False

    async def _tool_is_available_async(
        self,
        tool: BaseTool,
        context: Dict[str, Any],
    ) -> bool:
        checker = getattr(
            tool,
            "is_available",
            None,
        )

        if checker is None:
            return True

        try:
            result = checker(context)

            if inspect.isawaitable(result):
                result = await result

            return bool(result)

        except Exception:
            logger.exception(
                "[ToolManager] Async availability check failed for %s.",
                tool.name,
            )
            return False

    async def select_tool(
        self,
        query: str,
        context: Optional[Dict[str, Any]],
    ) -> Optional[BaseTool]:
        """Select the highest-confidence available tool above the threshold."""
        if not str(query or "").strip():
            return None

        context = self._safe_context(
            context
        )

        candidates: List[
            Tuple[float, int, BaseTool]
        ] = []

        for index, tool in enumerate(
            list(self.tools)
        ):
            if not await self._tool_is_available_async(
                tool,
                context,
            ):
                logger.info(
                    "[ToolManager] %s unavailable.",
                    tool.name,
                )
                continue

            try:
                raw_score = await tool.can_handle(
                    str(query),
                    context,
                )

                score = self._clamp(
                    raw_score,
                    0.0,
                    1.0,
                    0.0,
                )

            except Exception:
                logger.exception(
                    "[ToolManager] can_handle failed for %s.",
                    tool.name,
                )

                self.tool_failures[
                    tool.name
                ] = self.tool_failures.get(
                    tool.name,
                    0,
                ) + 1

                continue

            logger.info(
                "[ToolManager] %s score=%.2f",
                tool.name,
                score,
            )

            if score >= self.selection_threshold:
                candidates.append(
                    (
                        score,
                        index,
                        tool,
                    )
                )

        if not candidates:
            logger.info(
                "[ToolManager] No tool exceeded selection threshold %.2f.",
                self.selection_threshold,
            )
            return None

        # Highest confidence wins. Registration order breaks ties.
        candidates.sort(
            key=lambda item: (
                -item[0],
                item[1],
            )
        )

        best_score, _, best_tool = candidates[0]

        logger.info(
            "[ToolManager] Selected %s with score=%.2f.",
            best_tool.name,
            best_score,
        )

        return best_tool

    # =========================================================
    # EXECUTION
    # =========================================================

    async def execute(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        tool_name: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute a named tool or automatically select one.

        Preferred contract:
            execute(query, context, tool_name=None, params=None)

        The native tool result is returned unchanged. A missing tool or
        failed execution returns None for compatibility with Phase-9 callers.
        """
        context = self._safe_context(
            context
        )

        if params:
            context.setdefault(
                "tool_params",
                copy.deepcopy(params),
            )

        requested_name = (
            str(tool_name).strip()
            if tool_name
            else None
        )

        # Selection is intentionally outside the execution lock because
        # can_handle() is observational and may be relatively expensive.
        if requested_name:
            tool = self.get(
                requested_name
            )
        else:
            tool = await self.select_tool(
                query,
                context,
            )

        if tool is None:
            self._record_history(
                {
                    "tool": requested_name,
                    "query": str(query or ""),
                    "success": False,
                    "error": "No executable tool found.",
                    "timestamp": time.time(),
                }
            )

            logger.info(
                "[ToolManager] No executable tool found for query."
            )
            return None

        # The lock serializes actual tool execution so shared external
        # resources cannot accidentally be driven concurrently through this
        # manager. Individual tools can still manage their own concurrency.
        async with self._lock:
            started = time.perf_counter()

            try:
                result = await asyncio.wait_for(
                    tool.execute(
                        str(query or ""),
                        context,
                    ),
                    timeout=self.execution_timeout,
                )

                elapsed = (
                    time.perf_counter()
                    - started
                )

                name = tool.name

                self.tool_usage[name] = (
                    self.tool_usage.get(
                        name,
                        0,
                    )
                    + 1
                )

                usage = self.tool_usage[name]
                previous = self.tool_latency.get(
                    name,
                    0.0,
                )

                self.tool_latency[name] = (
                    (
                        previous
                        * (usage - 1)
                    )
                    + elapsed
                ) / usage

                success = self._result_success(
                    result
                )

                error = self._result_error(
                    result
                )

                self._record_history(
                    {
                        "tool": name,
                        "query": str(query or ""),
                        "success": success,
                        "error": error,
                        "latency": round(
                            elapsed,
                            4,
                        ),
                        "timestamp": time.time(),
                    }
                )

                logger.info(
                    "[ToolManager] Executed %s in %.3fs.",
                    name,
                    elapsed,
                )

                return result

            except asyncio.TimeoutError:
                name = tool.name

                self.tool_failures[name] = (
                    self.tool_failures.get(
                        name,
                        0,
                    )
                    + 1
                )

                self._record_history(
                    {
                        "tool": name,
                        "query": str(query or ""),
                        "success": False,
                        "error": (
                            "Tool execution timed out."
                        ),
                        "latency": self.execution_timeout,
                        "timestamp": time.time(),
                    }
                )

                logger.error(
                    "[ToolManager] Tool timed out: %s after %.1fs.",
                    name,
                    self.execution_timeout,
                )

                return None

            except asyncio.CancelledError:
                logger.info(
                    "[ToolManager] Tool execution cancelled: %s.",
                    tool.name,
                )
                raise

            except Exception as exc:
                name = tool.name

                self.tool_failures[name] = (
                    self.tool_failures.get(
                        name,
                        0,
                    )
                    + 1
                )

                self._record_history(
                    {
                        "tool": name,
                        "query": str(query or ""),
                        "success": False,
                        "error": str(exc),
                        "timestamp": time.time(),
                    }
                )

                logger.exception(
                    "[ToolManager] Tool execution failed: %s.",
                    name,
                )

                return None

    # =========================================================
    # STATISTICS / HEALTH
    # =========================================================

    def most_used_tools(self):
        return sorted(
            self.tool_usage.items(),
            key=lambda item: (
                item[1],
                item[0],
            ),
            reverse=True,
        )

    def reset_statistics(self):
        for tool in self.tool_usage:
            self.tool_usage[tool] = 0

        for tool in self.tool_failures:
            self.tool_failures[tool] = 0

        for tool in self.tool_latency:
            self.tool_latency[tool] = 0.0

        self.execution_history.clear()

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "version": self.VERSION,
            "tool_count": len(self.tools),
            "tools": self.list_tools(),
            "aliases": dict(self.tool_aliases),
            "selection_threshold": self.selection_threshold,
            "execution_timeout": self.execution_timeout,
            "statistics": self.tool_status(),
            "history_size": len(
                self.execution_history
            ),
        }
