from typing import Dict, Any

class WorkingMemory:
    """Ephemeral scratchpad for active task state, temporary variables, and session artifacts."""
    def __init__(self):
        self._memory: Dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """Stores or updates a key-value pair in working memory."""
        self._memory[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieves a value by key, returning the default if not found."""
        return self._memory.get(key, default)

    def delete(self, key: str) -> None:
        """Removes a key from working memory if it exists."""
        if key in self._memory:
            del self._memory[key]

    def contains(self, key: str) -> bool:
        """Checks if a key exists in working memory."""
        return key in self._memory

    def update(self, data: Dict[str, Any]) -> None:
        """Updates working memory with a dictionary of key-value pairs."""
        if isinstance(data, dict):
            self._memory.update(data)

    def clear(self) -> None:
        """Clears all ephemeral entries from working memory."""
        self._memory.clear()

    def snapshot(self) -> Dict[str, Any]:
        """Returns a copy of the current working memory store."""
        return dict(self._memory)
