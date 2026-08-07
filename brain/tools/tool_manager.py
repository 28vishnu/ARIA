import logging
from typing import List, Optional, Dict, Any

from brain.tools.base_tool import BaseTool

logger = logging.getLogger("aria")


class ToolManager:
    """
    Registers tools and selects the best one for a task.
    """

    def __init__(self):
        self.tools: List[BaseTool] = []
        self.tool_usage = {}

    def register(self, tool: BaseTool):
        self.tools.append(tool)
        self.tool_usage[tool.name] = 0

        logger.info(
            "[ToolManager] Registered tool: %s",
            tool.name
        )

    def get(self, name: str) -> Optional[BaseTool]:
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    async def select_tool(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> Optional[BaseTool]:

        best_tool = None
        best_score = 0.0

        for tool in self.tools:

            score = await tool.can_handle(
                query,
                context
            )

            logger.info(
                "[ToolManager] %s score=%.2f",
                tool.name,
                score
            )

            if score > best_score:
                best_score = score
                best_tool = tool

        if best_tool is not None:
            self.tool_usage[best_tool.name] += 1

        return best_tool 

    def most_used_tools(self):

        return sorted(
            self.tool_usage.items(),
            key=lambda x: x[1],
            reverse=True,
        )

    def reset_statistics(self):

        for tool in self.tool_usage:
            self.tool_usage[tool] = 0
