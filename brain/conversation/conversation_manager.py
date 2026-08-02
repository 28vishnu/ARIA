from typing import Any, Dict, List, Optional


class ConversationManager:
    """
    Manages runtime conversation state, turn history, context extraction,
    follow-up detection, and pronoun/reference resolution for ARIA.
    """

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """
        Get the session state by ID. Create it with default structure if absent.
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "current_topic": None,
                "previous_topic": None,
                "current_intent": None,
                "last_user_message": None,
                "last_assistant_message": None,
                "entities": [],
                "active_document": None,
                "active_plan": None,
                "turn_count": 0,
            }
        return self._sessions[session_id]

    def update_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        intent: Optional[str] = None,
        entities: Optional[List[Any]] = None,
    ) -> None:
        """
        Update session runtime state for a completed turn:
        - save last user message
        - save last assistant reply
        - increment turn count
        - update current intent
        - update entities
        - if entities exist, update current topic & move old topic -> previous_topic
        """
        session = self.get_session(session_id)

        session["last_user_message"] = user_message
        session["last_assistant_message"] = assistant_message
        session["turn_count"] = session.get("turn_count", 0) + 1

        if intent is not None:
            session["current_intent"] = intent

        if entities is not None:
            session["entities"] = entities
            if entities:
                # Extract first entity or joined entities as the new topic
                new_topic = str(entities[0]) if isinstance(entities, list) and entities else str(entities)
                if new_topic and new_topic != session.get("current_topic"):
                    session["previous_topic"] = session.get("current_topic")
                    session["current_topic"] = new_topic

    def get_context(self, session_id: str) -> Dict[str, Any]:
        """
        Return current formatted conversation context for the session.
        """
        session = self.get_session(session_id)
        return {
            "topic": session.get("current_topic"),
            "previous_topic": session.get("previous_topic"),
            "intent": session.get("current_intent"),
            "entities": session.get("entities"),
            "last_user": session.get("last_user_message"),
            "last_assistant": session.get("last_assistant_message"),
            "document": session.get("active_document"),
            "plan": session.get("active_plan"),
        }

    def is_followup(self, query: str) -> bool:
        """
        Detect simple follow-ups based on initial words or exact matches.
        """
        if not query:
            return False

        cleaned = query.strip().lower()
        followup_starters = (
            "continue",
            "go on",
            "more",
            "why",
            "how",
            "what about",
            "that",
            "it",
            "those",
            "them",
            "second",
            "third",
            "first",
            "explain",
            "expand",
            "elaborate",
            "compare",
        )

        # Check if exact match or starts with any of the followup starters
        if cleaned in followup_starters:
            return True

        for starter in followup_starters:
            if cleaned.startswith(starter + " ") or cleaned.startswith(starter + ","):
                return True

        return False

    def resolve_reference(self, session_id: str, query: str) -> str:
        """
        Resolve simple contextual references (like 'Continue', 'Compare it', etc.)
        using the current topic of the session.
        """
        if not query:
            return query

        session = self.get_session(session_id)
        current_topic = session.get("current_topic")
        cleaned = query.strip()
        lower_cleaned = cleaned.lower()

        if not current_topic:
            return cleaned

        # Example 1: "Continue" -> "Continue explaining Python."
        if lower_cleaned == "continue":
            return f"Continue explaining {current_topic}."

        # Example 2: "Explain the second point." (Contains ordinal/reference)
        # We append "about [current_topic]" if not already present
        if "it" in lower_cleaned.split() or "that" in lower_cleaned.split():
            resolved = cleaned
            for pronoun in [" it", " that"]:
                if pronoun in resolved.lower():
                    # Replace reference pronoun with topic mention smoothly
                    resolved = resolved.replace(pronoun, f" {current_topic}")
                    resolved = resolved.replace(pronoun.upper(), f" {current_topic}")
            return resolved

        if lower_cleaned.startswith("compare it"):
            return cleaned.lower().replace("compare it", f"Compare {current_topic}", 1)

        if lower_cleaned == "more" or lower_cleaned == "go on":
            return f"Tell me more about {current_topic}."

        return cleaned

    def set_active_document(self, session_id: str, document: Any) -> None:
        """
        Store document id/name.
        """
        session = self.get_session(session_id)
        session["active_document"] = document

    def clear_active_document(self, session_id: str) -> None:
        """
        Clear active document.
        """
        session = self.get_session(session_id)
        session["active_document"] = None

    def set_active_plan(self, session_id: str, plan: Any) -> None:
        """
        Store active plan.
        """
        session = self.get_session(session_id)
        session["active_plan"] = plan

    def clear_active_plan(self, session_id: str) -> None:
        """
        Clear active plan.
        """
        session = self.get_session(session_id)
        session["active_plan"] = None

    def clear_session(self, session_id: str) -> None:
        """
        Delete session entirely.
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
