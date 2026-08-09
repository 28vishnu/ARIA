import random
from typing import Optional


class AddressingEngine:
    """
    Centralized ARIA addressing system.

    ARIA must never use the user's personal name as an honorific.
    Titles are selected naturally and can be expanded later without
    modifying every response formatter.
    """

    TITLES = (
        "Sir",
        "Master",
        "Commander",
        "Chief",
        "Boss",
    )

    # More formal titles for situations where ARIA should sound composed.
    FORMAL_TITLES = (
        "Sir",
        "Master",
        "Commander",
    )

    # Casual but respectful titles.
    CASUAL_TITLES = (
        "Sir",
        "Master",
        "Chief",
        "Boss",
    )

    def __init__(self):
        self._last_title: Optional[str] = None

    def get_address(
        self,
        context: str = "normal",
        preferred: Optional[str] = None,
    ) -> str:
        """
        Return a natural form of address.

        IMPORTANT:
        - Never use the user's name.
        - Avoid repeating the same title consecutively.
        - A valid explicit preference takes priority.
        """

        if preferred:
            preferred = str(preferred).strip()

            if self._is_valid_title(preferred):
                self._last_title = preferred
                return preferred

        context = str(context or "normal").lower().strip()

        if context in {
            "formal",
            "technical",
            "security",
            "warning",
            "important",
            "confirmation",
        }:
            candidates = self.FORMAL_TITLES

        elif context in {
            "casual",
            "greeting",
            "conversation",
        }:
            candidates = self.CASUAL_TITLES

        else:
            candidates = self.TITLES

        available = [
            title
            for title in candidates
            if title != self._last_title
        ]

        if not available:
            available = list(candidates)

        title = random.choice(available)

        self._last_title = title

        return title

    def _is_valid_title(self, title: str) -> bool:
        return title in self.TITLES

    def reset(self):
        """Reset title history."""
        self._last_title = None