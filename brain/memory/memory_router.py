from typing import Dict, Any, Optional
from brain.memory.working_memory import WorkingMemory

class MemoryRouter:
    """Unified abstraction router for ARIA's memory subsystems (initially wrapping WorkingMemory)."""
    def __init__(self, working_memory: WorkingMemory):
        self.working_memory = working_memory

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieves a value from working memory through the router."""
        return self.working_memory.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Stores a value in working memory through the router."""
        self.working_memory.set(key, value)

    def delete(self, key: str) -> None:
        """Removes a key from working memory through the router."""
        self.working_memory.delete(key)

    def clear(self) -> None:
        """Clears working memory through the router."""
        self.working_memory.clear()

    def snapshot(self) -> Dict[str, Any]:
        """Returns a snapshot of working memory through the router."""
        return self.working_memory.snapshot()
