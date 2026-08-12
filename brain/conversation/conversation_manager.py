import re
json
from typing import Any, Dict, List, Optional


class ConversationManager:
    """
    Manages runtime conversation state, turn history, context extraction,
    follow-up detection, and pronoun/reference resolution for ARIA.
    """

    def __init__(self, llm_router: Optional[Any] = None):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self.llm_router = llm_router

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
                "last_compared_entities": [],
                "last_question": None,
                "last_answer": None,
                "active_task": None,
                "active_code": None,
                "pending_reference": None,
                "last_entity": None,
                "last_person": None,
                "last_company": None,
                "last_place": None,
                "last_language": None,
                "user_name": None,

                # Generic conversational state
                "working_context": {},
                "conversation_history": [],
            }
        return self._sessions[session_id]

    def extract_entities(self, text: str) -> List[str]:
        """
        Extract simple named entities from conversation text.
        """

        if not text:
            return []

        pattern = (
            r"\b[A-Z][a-zA-Z0-9_-]+"
            r"(?:\s+[A-Z][a-zA-Z0-9_-]+)*\b"
        )

        matches = re.findall(pattern, text)

        stop_words = {
            "What",
            "Who",
            "Where",
            "When",
            "Why",
            "How",
            "Is",
            "The",
            "A",
            "An",
            "And",
            "Or",
            "To",
            "In",
            "On",
            "Of",
            "For",
        }

        return [
            match
            for match in matches
            if match not in stop_words
        ]

    async def extract_entities_async(self, text: str) -> List[str]:
        """
        Asynchronous wrapper for entity extraction.
        """
        return self.extract_entities(text)

    def extract_topic(self, text: str) -> Optional[str]:
        """
        Extract a basic topic or entity from text using fallback rules or regex.
        """
        ents = self.extract_entities(text)
        if ents:
            return ents[0]
        return None

    async def update_turn_async(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        intent: Optional[str] = None,
        entities: Optional[List[Any]] = None,
    ) -> None:
        """
        Asynchronous version of update_turn to support LLM fallback entity extraction if needed.
        """
        session = self.get_session(session_id)

        # Deterministically remember the user's name.
        name_match = re.search(
            r"\bmy\s+name\s+is\s+([A-Za-z][A-Za-z .'-]{1,50})\s*$",
            user_message.strip(),
            re.IGNORECASE,
        )

        if name_match:
            name = name_match.group(1).strip()
            name = re.sub(r"\s+", " ", name)
            session["user_name"] = name

        session["last_user_message"] = user_message
        session["last_assistant_message"] = assistant_message
        session["last_question"] = user_message
        session["last_answer"] = assistant_message
        session["turn_count"] = session.get("turn_count", 0) + 1
        history = session.setdefault("conversation_history", [])

        history.append({
            "user": user_message,
            "assistant": assistant_message,
        })

        if len(history) > 20:
            del history[:-20]

        if intent is not None:
            session["current_intent"] = intent

        if entities:
            session["entities"] = entities
            new_topic = str(entities[0]) if isinstance(entities, list) and entities else str(entities)
        else:
            extracted_ents = await self.extract_entities_async(user_message)
            if extracted_ents:
                session["entities"] = extracted_ents
                new_topic = extracted_ents[0]
            else:
                session["entities"] = []
                new_topic = self.extract_topic(user_message)

        if not new_topic:
            new_topic = session.get("current_topic")

        session["last_entity"] = new_topic

        # Classify entity categories
        if new_topic:
            lower_topic = new_topic.lower()
            languages = {"python", "java", "javascript", "c++", "c", "r", "go", "rust", "typescript"}
            companies = {"tesla", "openai", "google", "microsoft", "apple", "amazon", "meta", "netflix"}
            places = {"italy", "new york", "usa", "india", "tokyo", "london", "france", "germany"}
            persons = {"elon musk", "bill gates", "steve jobs", "guido van rossum"}

            if lower_topic in languages:
                session["last_language"] = new_topic
            elif lower_topic in companies:
                session["last_company"] = new_topic
            elif lower_topic in places:
                session["last_place"] = new_topic
            elif lower_topic in persons or len(new_topic.split()) == 2:
                session["last_person"] = new_topic

        if "compare" in user_message.lower():
            extracted = await self.extract_entities_async(user_message)
            if len(extracted) >= 2:
                session["last_compared_entities"] = extracted

        if new_topic:
            if new_topic != session.get("current_topic"):
                session["previous_topic"] = session.get("current_topic")
                session["current_topic"] = new_topic
            session["last_subject"] = new_topic

    def update_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        intent: Optional[str] = None,
        entities: Optional[List[Any]] = None,
    ) -> None:
        """
        Synchronous wrapper for turn update using regex/fallback entity extraction.
        """
        session = self.get_session(session_id)

        # Deterministically remember the user's name.
        name_match = re.search(
            r"\bmy\s+name\s+is\s+([A-Za-z][A-Za-z .'-]{1,50})\s*$",
            user_message.strip(),
            re.IGNORECASE,
        )

        if name_match:
            name = name_match.group(1).strip()
            name = re.sub(r"\s+", " ", name)
            session["user_name"] = name

        session["last_user_message"] = user_message
        session["last_assistant_message"] = assistant_message
        session["last_question"] = user_message
        session["last_answer"] = assistant_message
        session["turn_count"] = session.get("turn_count", 0) + 1
        history = session.setdefault("conversation_history", [])

        history.append({
            "user": user_message,
            "assistant": assistant_message,
        })

        if len(history) > 20:
            del history[:-20]

        if intent is not None:
            session["current_intent"] = intent

        if entities:
            session["entities"] = entities
            new_topic = str(entities[0]) if isinstance(entities, list) and entities else str(entities)
        else:
            extracted_ents = self.extract_entities(user_message)
            if extracted_ents:
                session["entities"] = extracted_ents
                new_topic = extracted_ents[0]
            else:
                session["entities"] = []
                new_topic = self.extract_topic(user_message)

        if not new_topic:
            new_topic = session.get("current_topic")

        session["last_entity"] = new_topic

        if new_topic:
            lower_topic = new_topic.lower()
            languages = {"python", "java", "javascript", "c++", "c", "r", "go", "rust", "typescript"}
            companies = {"tesla", "openai", "google", "microsoft", "apple", "amazon", "meta", "netflix"}
            places = {"italy", "new york", "usa", "india", "tokyo", "london", "france", "germany"}
            persons = {"elon musk", "bill gates", "steve jobs", "guido van rossum"}

            if lower_topic in languages:
                session["last_language"] = new_topic
            elif lower_topic in companies:
                session["last_company"] = new_topic
            elif lower_topic in places:
                session["last_place"] = new_topic
            elif lower_topic in persons or len(new_topic.split()) == 2:
                session["last_person"] = new_topic

        if "compare" in user_message.lower():
            extracted = self.extract_entities(user_message)
            if len(extracted) >= 2:
                session["last_compared_entities"] = extracted

        if new_topic:
            if new_topic != session.get("current_topic"):
                session["previous_topic"] = session.get("current_topic")
                session["current_topic"] = new_topic
            session["last_subject"] = new_topic

    def get_context(self, session_id: str) -> Dict[str, Any]:
        """
        Return the complete conversational context for the session.
        """

        session = self.get_session(session_id)

        return {
            "topic": session.get("current_topic"),
            "previous_topic": session.get("previous_topic"),
            "last_subject": session.get("last_subject"),
            "current_intent": session.get("current_intent"),
            "entities": session.get("entities", []),

            "last_user": session.get("last_user_message"),
            "last_assistant": session.get("last_assistant_message"),

            "document": session.get("active_document"),
            "plan": session.get("active_plan"),
            "user_goal": session.get("user_goal"),
            "pending_followup": session.get("pending_followup"),

            "conversation_summary": session.get(
                "conversation_summary",
                ""
            ),

            "last_person": session.get("last_person"),
            "last_company": session.get("last_company"),
            "last_place": session.get("last_place"),
            "last_language": session.get("last_language"),

            "conversation_history": session.get(
                "conversation_history",
                []
            ),

            "working_context": session.get(
                "working_context",
                {}
            ),
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
            "give example",
            "python example",
            "java example",
            "which is easier",
        )

        if cleaned in followup_starters:
            return True

        for starter in followup_starters:
            if cleaned.startswith(starter + " ") or cleaned.startswith(starter + ","):
                return True

        return False

    def resolve_followup(
        self,
        session_id: str,
        query: str,
    ) -> str:
        """
        Lightweight fallback for conversational references.

        The ConversationManager does not decide what a reference means.
        Higher-level reasoning owns semantic interpretation.

        This method only supplies the most recent conversational subject
        when a higher-level reasoning system is unavailable.
        """

        if not query:
            return query

        session = self.get_session(session_id)

        subject = (
            session.get("last_subject")
            or session.get("current_topic")
            or session.get("last_entity")
        )

        cleaned = query.strip()

        if not subject:
            return cleaned

        lower = cleaned.lower()

        if lower == "continue":
            return f"Continue explaining {subject}"

        if lower == "more":
            return f"Tell me more about {subject}"

        return cleaned

    def resolve_reference(self, session_id: str, query: str) -> str:
        """
        Resolve simple contextual references using the last subject or current topic of the session.
        """
        if not query:
            return query

        session = self.get_session(session_id)
        subject = session.get("last_subject") or session.get("current_topic")
        cleaned = query.strip()
        lower = cleaned.lower()

        if lower == "give example":
            compared = session.get("last_compared_entities", [])
            if len(compared) >= 2:
                a, b = compared[0], compared[1]
                return f"Give an example comparing {a} and {b}."
            if subject:
                return f"Give an example of {subject}."

        if lower == "python example":
            return "Give a Python example."

        if lower == "java example":
            return "Give a Java example."

        if lower == "which is easier":
            compared = session.get("last_compared_entities", [])
            if len(compared) >= 2:
                a, b = compared[0], compared[1]
                return f"Which is easier between {a} and {b}?"
            if subject:
                return f"Which is easier involving {subject}?"

        if not subject:
            return cleaned

        if lower.startswith("compare it with "):
            other = cleaned[len("compare it with "):]
            return f"Compare {subject} with {other}"

        if lower.startswith("compare it to "):
            other = cleaned[len("compare it to "):]
            return f"Compare {subject} to {other}"

        if lower == "why":
            return f"Why is {subject} better?"

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
