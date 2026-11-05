from typing import Optional


class AddressingEngine:
    """
    Centralized ARIA addressing system.

    ARIA never addresses the user by personal name.

    Use a stable, respectful default address. A consistent preference is
    more predictable than rotating titles on each response.
    """

    TITLES = ("Sir", "Master", "Commander", "Chief", "Boss")
    FORMAL_TITLES = ("Sir", "Master", "Commander")
    CASUAL_TITLES = ("Sir", "Master", "Chief", "Boss")

    CONTEXT_PREFERENCES = {
        "normal": ("Sir",),
        "technical": ("Sir",),
        "security": ("Sir",),
        "warning": ("Sir",),
        "important": ("Sir",),
        "confirmation": ("Sir",),
        "greeting": ("Sir",),
        "conversation": ("Sir",),
        "casual": ("Sir",),
    }

    def __init__(self):
        self._last_title: Optional[str] = None

    def get_address(
        self,
        context: str = "normal",
        preferred: Optional[str] = None,
    ) -> str:
        """Return the explicit valid preference or the stable default, Sir."""
        if preferred:
            preferred = str(preferred).strip()
            if self._is_valid_title(preferred):
                self._last_title = preferred
                return preferred

        context = str(context or "normal").lower().strip()
        candidates = self.CONTEXT_PREFERENCES.get(context, ("Sir",))
        title = candidates[0] if candidates else "Sir"
        self._last_title = title
        return title

    def _is_valid_title(self, title: str) -> bool:
        return title in self.TITLES

    def reset(self):
        self._last_title = None
