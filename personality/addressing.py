import random
from typing import Optional


class AddressingEngine:
    """
    Centralized ARIA addressing system.

    ARIA never addresses the user by personal name.

    Titles vary naturally according to context while avoiding
    repetitive consecutive addressing.
    """

    TITLES = (
        "Sir",
        "Master",
        "Commander",
        "Chief",
        "Boss",
    )

    FORMAL_TITLES = (
        "Sir",
        "Master",
        "Commander",
    )

    CASUAL_TITLES = (
        "Sir",
        "Master",
        "Chief",
        "Boss",
    )

    CONTEXT_PREFERENCES = {
        "normal": (
            "Sir",
            "Master",
            "Commander",
            "Chief",
            "Boss",
        ),
        "technical": (
            "Sir",
            "Commander",
            "Master",
        ),
        "security": (
            "Sir",
            "Commander",
            "Master",
        ),
        "warning": (
            "Sir",
            "Commander",
            "Master",
        ),
        "important": (
            "Sir",
            "Master",
            "Commander",
        ),
        "confirmation": (
            "Sir",
            "Commander",
            "Master",
        ),
        "greeting": (
            "Sir",
            "Master",
            "Chief",
            "Boss",
        ),
        "conversation": (
            "Sir",
            "Master",
            "Chief",
            "Boss",
        ),
        "casual": (
            "Sir",
            "Master",
            "Chief",
            "Boss",
        ),
    }

    def __init__(self):
        self._last_title: Optional[str] = None

    def get_address(
        self,
        context: str = "normal",
        preferred: Optional[str] = None,
    ) -> str:
        """
        Select a natural form of address.

        Personal names are NEVER used.

        An explicit valid preference wins.
        Otherwise the context determines the candidate titles.
        The previous title is avoided whenever possible.
        """

        if preferred:
            preferred = str(preferred).strip()

            if self._is_valid_title(preferred):
                self._last_title = preferred
                return preferred

        context = str(context or "normal").lower().strip()

        candidates = self.CONTEXT_PREFERENCES.get(
            context,
            self.TITLES,
        )

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
        self._last_title = None