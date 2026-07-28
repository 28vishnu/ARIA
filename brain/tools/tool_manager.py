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

    def register(self, tool: BaseTool):
        self.tools.append(tool)

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

        return best_tool 