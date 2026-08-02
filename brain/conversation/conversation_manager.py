from typing import Optional, Dict, Any, List


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
                "last_subject": None,
                "current_intent": None,
                "last_user_message": None,
                "last_assistant_message": None,
                "entities": [],
                "active_document": None,
                "active_plan": None,
                "turn_count": 0,
                "user_goal": None,
                "pending_followup": None,
                "conversation_summary": "",
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

        if entities:
            session["entities"] = entities
            new_topic = str(entities[0]) if isinstance(entities, list) and entities else str(entities)
        else:
            entities = []
            session["entities"] = entities
            new_topic = self.extract_topic(user_message)

        if new_topic:
            if new_topic != session.get("current_topic"):
                session["previous_topic"] = session.get("current_topic")
                session["current_topic"] = new_topic
            session["last_subject"] = new_topic

    def get_context(self, session_id: str) -> Dict[str, Any]:
        """
        Return current formatted conversation context for the session.
        """
        session = self.get_session(session_id)
        return {
            "topic": session.get("current_topic"),
            "previous_topic": session.get("previous_topic"),
            "last_subject": session.get("last_subject"),
            "intent": session.get("current_intent"),
            "entities": session.get("entities"),
            "last_user": session.get("last_user_message"),
            "last_assistant": session.get("last_assistant_message"),
            "document": session.get("active_document"),
            "plan": session.get("active_plan"),
            "user_goal": session.get("user_goal"),
            "pending_followup": session.get("pending_followup"),
            "conversation_summary": session.get("conversation_summary"),
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
        Resolve simple contextual references using the last subject or current topic of the session.
        """
        if not query:
            return query

        session = self.get_session(session_id)
        subject = session.get("last_subject") or session.get("current_topic")
        cleaned = query.strip()

        if not subject:
            return cleaned

        lower = cleaned.lower()

        if lower.startswith("compare it with "):
            other = cleaned[len("Compare it with "):]
            return f"Compare {subject} with {other}"

        if lower.startswith("compare it to "):
            other = cleaned[len("Compare it to "):]
            return f"Compare {subject} to {other}"

        if lower == "why":
            return f"Why {session.get('last_user_message')}"

        if lower.startswith("why "):
            return f"Why {subject} {cleaned[4:]}"

        if lower == "continue":
            return f"Continue explaining {subject}"

        if lower == "more":
            return f"Tell me more about {subject}"

        words = cleaned.split()

        words = [
            subject if w.lower() in ("it", "this", "that") else w
            for w in words
        ]

        return " ".join(words)

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

    def set_user_goal(
        self,
        session_id,
        goal,
    ):
        session = self.get_session(session_id)
        session["user_goal"] = goal

    def set_pending_followup(
        self,
        session_id,
        followup,
    ):
        session = self.get_session(session_id)
        session["pending_followup"] = followup

    def clear_session(self, session_id: str) -> None:
        """
        Delete session entirely.
        """
        if session_id in self._sessions:
            del self._sessions[session_id]

    def extract_topic(self, text: str) -> Optional[str]:
        """
        Lightweight topic extractor.
        Used only when no entities are supplied.
        """

        if not text:
            return None

        COMMON_TOPICS = {
            "python",
            "java",
            "javascript",
            "c++",
            "docker",
            "linux",
            "mongodb",
            "postgres",
            "redis",
            "fastapi",
            "django",
            "flask",
        }

        words = text.lower().split()

        for word in words:
            word = word.strip(".,?!")
            if word in COMMON_TOPICS:
                return word.title()

        return None
