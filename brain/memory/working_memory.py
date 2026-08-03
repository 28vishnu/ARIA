import time
from typing import Dict, Any, Optional, List


class WorkingMemory:
    """Ephemeral scratchpad for active task state, temporary variables, and session artifacts."""

    def __init__(self):
        self._memory: Dict[str, Any] = {}
        self._last_update: Dict[str, float] = {}
        self._ttl = 1800  # 30 minutes
        self._active_topic: Optional[str] = None
        self._active_goal: Optional[str] = None
        self._active_document: Optional[Any] = None
        self._active_entities: List[Any] = []
        self._last_question: Optional[str] = None
        self._last_answer: Optional[str] = None
        self._active_person: Optional[str] = None
        self._active_company: Optional[str] = None
        self._active_place: Optional[str] = None
        self._active_language: Optional[str] = None
        self._reasoning_cache: Dict[str, Any] = {}
        self._answer_cache: Dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """Stores or updates a key-value pair in working memory."""
        self._memory[key] = value
        self._last_update[key] = time.time()

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieves a value by key, returning the default if not found or expired."""
        if key not in self._memory:
            return default

        age = time.time() - self._last_update.get(key, 0.0)
        if age > self._ttl:
            self.delete(key)
            return default

        return self._memory[key]

    def delete(self, key: str) -> None:
        """Removes a key from working memory if it exists."""
        if key in self._memory:
            del self._memory[key]
        if key in self._last_update:
            del self._last_update[key]

    def contains(self, key: str) -> bool:
        """Checks if a key exists in working memory and is not expired."""
        return self.get(key) is not None

    def update(self, data: Dict[str, Any]) -> None:
        """Updates working memory with a dictionary of key-value pairs."""
        if isinstance(data, dict):
            for k, v in data.items():
                self.set(k, v)

    def clear(self) -> None:
        """Clears all ephemeral entries from working memory."""
        self._memory.clear()
        self._last_update.clear()
        self._active_topic = None
        self._active_goal = None
        self._active_document = None
        self._active_entities = []
        self._last_question = None
        self._last_answer = None
        self._active_person = None
        self._active_company = None
        self._active_place = None
        self._active_language = None
        self._reasoning_cache.clear()
        self._answer_cache.clear()

    def snapshot(self) -> Dict[str, Any]:
        """Returns a copy of the current working memory store."""
        return dict(self._memory)

    def set_topic(self, topic: Optional[str]) -> None:
        self._active_topic = topic

    def get_topic(self) -> Optional[str]:
        return self._active_topic

    def set_goal(self, goal: Optional[str]) -> None:
        self._active_goal = goal

    def get_goal(self) -> Optional[str]:
        return self._active_goal

    def set_entities(self, entities: List[Any]) -> None:
        self._active_entities = list(entities)

    def get_entities(self) -> List[Any]:
        return self._active_entities

    def set_document(self, document: Any) -> None:
        self._active_document = document

    def get_document(self) -> Any:
        return self._active_document

    def remember_exchange(self, question: str, answer: str) -> None:
        self._last_question = question
        self._last_answer = answer

    def last_question(self) -> Optional[str]:
        return self._last_question

    def last_answer(self) -> Optional[str]:
        return self._last_answer

    def set_active_person(self, person: Optional[str]) -> None:
        self._active_person = person

    def get_active_person(self) -> Optional[str]:
        return self._active_person

    def set_active_company(self, company: Optional[str]) -> None:
        self._active_company = company

    def get_active_company(self) -> Optional[str]:
        return self._active_company

    def set_active_place(self, place: Optional[str]) -> None:
        self._active_place = place

    def get_active_place(self) -> Optional[str]:
        return self._active_place

    def set_active_language(self, language: Optional[str]) -> None:
        self._active_language = language

    def get_active_language(self) -> Optional[str]:
        return self._active_language

    def cache_answer(self, key: str, answer: Any) -> None:
        self._answer_cache[key] = answer

    def get_cached_answer(self, key: str) -> Any:
        return self._answer_cache.get(key)

    def cache_reasoning(self, key: str, reasoning: Any) -> None:
        self._reasoning_cache[key] = reasoning

    def get_cached_reasoning(self, key: str) -> Any:
        return self._reasoning_cache.get(key)
