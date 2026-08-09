import re
import json
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

                # Calculation context
                "last_calculation": None,
                "last_calculation_result": None,
            }
        return self._sessions[session_id]

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

        session["last_user_message"] = user_message
        session["last_assistant_message"] = assistant_message
        session["last_question"] = user_message
        session["last_answer"] = assistant_message
        session["turn_count"] = session.get("turn_count", 0) + 1

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

        session["last_user_message"] = user_message
        session["last_assistant_message"] = assistant_message
        session["last_question"] = user_message
        session["last_answer"] = assistant_message
        session["turn_count"] = session.get("turn_count", 0) + 1

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
        Return current formatted conversation context for the session.
        """
        session = self.get_session(session_id)
        return {
            "topic": session.get("current_topic"),
            "previous_topic": session.get("previous_topic"),
            "last_subject": session.get("last_subject"),
            "current_intent": session.get("current_intent"),
            "entities": session.get("entities"),
            "last_user": session.get("last_user_message"),
            "last_assistant": session.get("last_assistant_message"),
            "document": session.get("active_document"),
            "plan": session.get("active_plan"),
            "user_goal": session.get("user_goal"),
            "pending_followup": session.get("pending_followup"),
            "conversation_summary": session.get("conversation_summary"),
            "last_person": session.get("last_person"),
            "last_company": session.get("last_company"),
            "last_place": session.get("last_place"),
            "last_language": session.get("last_language"),
            "last_calculation": session.get("last_calculation"),
            "last_calculation_result": session.get("last_calculation_result"),
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
        Resolve a new user query against the previous conversation turn.

        This is intentionally lightweight and deterministic.
        It does not call the LLM.

        Examples:
            "What about tomorrow?"
            "Divide that by 10"
            "What about India?"
            "Explain it"
        """

        if not query:
            return query

        session = self.get_session(session_id)

        previous_user = session.get("last_user_message")
        previous_assistant = session.get("last_assistant_message")
        subject = (
            session.get("last_subject")
            or session.get("current_topic")
            or session.get("last_entity")
        )

        cleaned = query.strip()

        if not previous_user and not previous_assistant:
            return cleaned

        lower = cleaned.lower()

        # -------------------------------------------------
        # Calculator follow-ups
        # -------------------------------------------------

        last_result = session.get("last_calculation_result")

        calculator_phrases = (
            "divide that",
            "multiply that",
            "add that",
            "subtract that",
            "divide it",
            "multiply it",
            "add it",
            "subtract it",
        )

        if any(lower.startswith(p) for p in calculator_phrases):
            if last_result:
                return (
                    f"{cleaned} using the previous result: "
                    f"{last_result}"
                )

        # -------------------------------------------------
        # Weather / location follow-ups
        # -------------------------------------------------

        weather_phrases = (
            "what about tomorrow",
            "what about today",
            "what about the next day",
            "and tomorrow",
            "tomorrow",
        )

        if lower in weather_phrases and subject:
            return f"{cleaned} for {subject}"

        # -------------------------------------------------
        # Pronoun references
        # -------------------------------------------------

        if subject:
            words = cleaned.split()

            resolved_words = []

            for word in words:
                punctuation = ""

                while word and word[-1] in ".,!?":
                    punctuation = word[-1] + punctuation
                    word = word[:-1]

                if word.lower() in {
                    "it",
                    "this",
                    "that",
                    "there",
                    "they",
                    "them",
                }:
                    resolved_words.append(
                        subject + punctuation
                    )
                else:
                    resolved_words.append(
                        word + punctuation
                    )

            return " ".join(resolved_words)

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

    def set_last_calculation(
        self,
        session_id: str,
        expression: str,
        result: Any,
    ) -> None:
        """
        Store the most recent successful calculation and its result.
        This allows follow-up mathematical commands such as:
            "divide that by 10"
            "add 50"
            "multiply it by 2"
        """
        session = self.get_session(session_id)

        session["last_calculation"] = expression
        session["last_calculation_result"] = result

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

        stripped = text.strip()
        if stripped and len(stripped.split()) <= 3:
            return stripped.title()

        return None

    def extract_entities(self, text: str) -> List[str]:
        """
        Step 1: Regex finding capitalized words/phrases (e.g., Elon Musk, New York, OpenAI).
        """
        if not text:
            return []

        # Find sequences of capitalized words
        pattern = r"\b[A-Z][a-zA-Z0-9_-]+(?:\s+[A-Z][a-zA-Z0-9_-]+)*\b"
        matches = re.findall(pattern, text)

        stop_words = {"What", "Who", "Where", "When", "Why", "How", "Is", "The", "A", "An", "And", "Or", "To", "In", "On", "Of", "For"}
        filtered = [m for m in matches if m not in stop_words]

        return filtered

    async def extract_entities_async(self, text: str) -> List[str]:
        """
        Step 1: Regex finding capitalized entities.
        Step 2: If regex fails or returns nothing, call llm_router to extract entities as JSON list.
        """
        entities = self.extract_entities(text)
        if entities:
            return entities

        if self.llm_router and hasattr(self.llm_router, "chat"):
            try:
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "Extract named entities (people, companies, places, programming languages, technologies) "
                            "from the given text. Return ONLY a valid JSON list of strings, e.g., [\"Tesla\", \"Python\"]. "
                            "If none are found, return []."
                        ),
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ]
                response = await self.llm_router.chat(messages, task="entity_extraction")
                if response:
                    cleaned = response.strip()
                    if cleaned.startswith("```json"):
                        cleaned = cleaned[7:]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    parsed = json.loads(cleaned.strip())
                    if isinstance(parsed, list):
                        return [str(item) for item in parsed]
            except Exception:
                pass

        return []
