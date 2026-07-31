import logging
import re
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from brain.memory.memory_engine import MemoryEngine

if TYPE_CHECKING:
    from brain.llm.llm_router import LLMRouter

logger = logging.getLogger("aria")


class MemoryConversationManager:
    """
    Handles direct interaction with ARIA's persistent memory.

    Important principle:
    If ARIA already knows the answer from memory, it should answer
    directly without requiring an external LLM.
    """

    def __init__(
        self,
        memory_engine: MemoryEngine,
        llm_router: Optional["LLMRouter"] = None
    ):
        self.memory_engine = memory_engine
        self.llm_router = llm_router
