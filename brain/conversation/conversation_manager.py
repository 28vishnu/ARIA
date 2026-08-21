import re
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
                "active_comparison": False,
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
                "recent_topics": [],
                "user_name": None,

                # Generic conversational state
                "working_context": {},
                "conversation_history": [],
                "state_version": 1,

                # Generic previous-result context.
                # This is capability-independent: calculator, coding,
                # tools, workflows, searches, etc. may store structured results here.
                "last_result": None,
                "last_result_source": None,
                "last_result_operation": None,
            }
        else:
            session = self._sessions[session_id]
            session.setdefault("working_context", {})
            session.setdefault("last_result", None)
            session.setdefault("last_result_source", None)
            session.setdefault("last_result_operation", None)
            session.setdefault("conversation_history", [])
            session.setdefault("last_compared_entities", [])
            session.setdefault("active_comparison", False)
            session.setdefault("recent_topics", [])
            session.setdefault("state_version", 1)

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

            # Greetings are not conversation topics.
            "Hello",
            "Hi",
            "Hey",
            "Good",
            "Morning",
            "Afternoon",
            "Evening",
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

    def _remember_topic(
        self,
        session: Dict[str, Any],
        topic: Optional[str],
    ) -> None:
        """Keep the two most recent meaningful conversation topics."""

        if not topic:
            return

        topic = str(topic).strip()

        if not topic:
            return

        recent = session.setdefault("recent_topics", [])

        # Don't duplicate the current topic.
        recent = [
            item for item in recent
            if str(item).lower() != topic.lower()
        ]

        recent.append(topic)

        # Keep only the two most recent topics.
        session["recent_topics"] = recent[-2:]

    def _update_comparison_state(
        self,
        session: Dict[str, Any],
        user_message: str,
        entities: List[str],
    ) -> None:
        """
        Maintain comparison context only while the conversation is
        actually discussing the compared subjects.

        A new explicit topic automatically ends the old comparison.
        """

        text = str(user_message or "").strip().lower()
        cleaned_entities = self._clean_entities(entities)

        comparison_signal = bool(
            re.search(
                r"\b(compare|comparing|comparison|versus|vs\.?)\b",
                text,
                re.IGNORECASE,
            )
        )

        between_signal = bool(
            re.search(
                r"\bbetween\b.+\band\b",
                text,
                re.IGNORECASE,
            )
        )

        # ---------------------------------------------------------
        # 1. Explicitly establish a NEW comparison
        # ---------------------------------------------------------
        if (
            (comparison_signal or between_signal)
            and len(cleaned_entities) >= 2
        ):
            session["last_compared_entities"] = cleaned_entities[:]
            session["active_comparison"] = True

            session["last_subject"] = {
                "type": "comparison",
                "entities": cleaned_entities[:],
            }

            return

        existing = self._clean_entities(
            session.get("last_compared_entities", [])
        )

        # ---------------------------------------------------------
        # 2. Determine whether this is a legitimate comparison
        #    follow-up.
        # ---------------------------------------------------------
        comparison_followup_patterns = (
            "which one",
            "which is",
            "which would",
            "which has",
            "which performs",
            "what about",
            "how about",
            "why",
            "continue",
            "tell me more",
            "give example",
            "explain",
        )

        is_followup = (
            session.get("active_comparison")
            and len(existing) >= 2
            and (
                text in comparison_followup_patterns
                or text.startswith(
                    tuple(
                        pattern + " "
                        for pattern in comparison_followup_patterns
                    )
                )
                or text.startswith(
                    tuple(
                        pattern + ","
                        for pattern in comparison_followup_patterns
                    )
                )
            )
        )

        if is_followup:
            return

        # ---------------------------------------------------------
        # 3. NEW TOPIC = terminate old comparison
        #
        # Example:
        #   TCP
        #   UDP
        #   Which one is faster?
        #   What is photosynthesis?
        #
        # The photosynthesis question must NOT remain attached
        # to the TCP/UDP comparison.
        # ---------------------------------------------------------
        if cleaned_entities:
            entity_names = {
                entity.lower()
                for entity in cleaned_entities
            }

            comparison_entities = {
                entity.lower()
                for entity in existing
            }

            if not entity_names.intersection(comparison_entities):
                session["active_comparison"] = False
                session["last_compared_entities"] = []

        # ---------------------------------------------------------
        # 4. Explicit comparison language without enough entities
        #    should not create fake comparison state.
        # ---------------------------------------------------------
        if comparison_signal or between_signal:
            if len(cleaned_entities) < 2:
                return

            session["active_comparison"] = False
            session["last_compared_entities"] = []

    def _clean_entities(
        self,
        entities: Optional[List[Any]],
    ) -> List[str]:
        if not entities:
            return []

        invalid = {
            "what",
            "which",
            "who",
            "where",
            "when",
            "why",
            "how",
            "is",
            "are",
            "was",
            "were",
            "the",
            "this",
            "that",
            "it",
            "compare",
            "comparing",
            "comparison",
            "versus",
            "vs",
            "and",
        }

        result = []

        for entity in entities:
            value = str(entity).strip()

            if not value:
                continue

            if value.lower() in invalid:
                continue

            if value not in result:
                result.append(value)

        return result

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
            extracted_ents = self._clean_entities(entities)
        else:
            extracted_ents = await self.extract_entities_async(
                user_message
            )

            extracted_ents = self._clean_entities(
                extracted_ents
            )

        if extracted_ents:
            session["entities"] = extracted_ents
            new_topic = extracted_ents[0]
        else:
            # Preserve previous state for follow-up questions.
            session["entities"] = session.get(
                "entities",
                [],
            )
            new_topic = None

        self._update_comparison_state(
            session,
            user_message,
            extracted_ents,
        )

        if (
            session.get("active_comparison")
            and len(session.get("last_compared_entities", [])) >= 2
        ):
            compared = session["last_compared_entities"]

            session["last_entity"] = compared[-1]

            if session.get("current_topic") != "comparison":
                session["previous_topic"] = session.get("current_topic")
                session["current_topic"] = "comparison"

            session["last_subject"] = {
                "type": "comparison",
                "entities": compared[:],
            }

            new_topic = "comparison"

        else:
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
            elif lower_topic in persons:
                session["last_person"] = new_topic

        if new_topic:
            if new_topic != session.get("current_topic"):
                session["previous_topic"] = session.get("current_topic")
                session["current_topic"] = new_topic

            self._remember_topic(session, new_topic)

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
            extracted_ents = self._clean_entities(entities)
        else:
            extracted_ents = self.extract_entities(
                user_message
            )

            extracted_ents = self._clean_entities(
                extracted_ents
            )

        if extracted_ents:
            session["entities"] = extracted_ents
            new_topic = extracted_ents[0]
        else:
            # Preserve previous state for follow-up questions.
            session["entities"] = session.get(
                "entities",
                [],
            )
            new_topic = None

        self._update_comparison_state(
            session,
            user_message,
            extracted_ents,
        )

        if (
            session.get("active_comparison")
            and len(session.get("last_compared_entities", [])) >= 2
        ):
            compared = session["last_compared_entities"]

            session["last_entity"] = compared[-1]

            if session.get("current_topic") != "comparison":
                session["previous_topic"] = session.get("current_topic")
                session["current_topic"] = "comparison"

            session["last_subject"] = {
                "type": "comparison",
                "entities": compared[:],
            }

            new_topic = "comparison"

        else:
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
            elif lower_topic in persons:
                session["last_person"] = new_topic

        if new_topic:
            if new_topic != session.get("current_topic"):
                session["previous_topic"] = session.get("current_topic")
                session["current_topic"] = new_topic

            self._remember_topic(session, new_topic)

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
            "subject_type": (
                session.get("last_subject", {}).get("type")
                if isinstance(session.get("last_subject"), dict)
                else None
            ),
            "subject_entities": (
                session.get("last_subject", {}).get("entities", [])
                if isinstance(session.get("last_subject"), dict)
                else []
            ),
            "current_intent": session.get("current_intent"),
            "entities": session.get("entities", []),
            "active_entities": session.get(
                "entities",
                [],
            ),
            "last_compared_entities": session.get(
                "last_compared_entities",
                [],
            ),
            "compared_entities": session.get(
                "last_compared_entities",
                [],
            ),
            "active_comparison": bool(
                session.get(
                    "active_comparison",
                    False,
                )
            ),
            "user_name": session.get(
                "user_name"
            ),

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

            "last_result": session.get("last_result"),
            "last_result_source": session.get("last_result_source"),
            "last_result_operation": session.get("last_result_operation"),
        }

    def set_last_result(
        self,
        session_id: str,
        result: Any,
        *,
        source: Optional[str] = None,
        operation: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Store the latest structured result for contextual reasoning.

        Capability-independent. Any subsystem may publish a meaningful result.
        """
        session = self.get_session(session_id)

        session["last_result"] = {
            "value": result,
            "source": source,
            "operation": operation,
            "metadata": metadata or {},
        }

        session["last_result_source"] = source
        session["last_result_operation"] = operation

    def get_last_result(
        self,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Return the latest structured result for this conversation.
        """
        session = self.get_session(session_id)

        result = session.get("last_result")

        if not isinstance(result, dict):
            return None

        return result

    def set_last_calculation(
        self,
        session_id: str,
        expression: str,
        result: Any,
    ) -> None:
        """
        Backward-compatible calculator helper.

        Calculator-specific code may continue calling this method, but the
        actual storage is handled by the generic result mechanism.
        """
        self.set_last_result(
            session_id,
            result,
            source="calculator",
            operation=expression,
            metadata={
                "expression": expression,
            },
        )

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
        Resolve conversational references before the cognitive core sees them.

        Important:
        - A follow-up such as "Which one is faster?" must inherit the
          comparison established by the conversation, even when the
          comparison was implicit (for example, "What is TCP?" followed
          by "What is UDP?").
        - Short follow-ups such as "Why?", "What about gaming?", and
          "Which one is easier?" must retain the active subject.
        - Never turn an unrelated word such as "Compare" into an entity.
        """
        if not query:
            return query

        session = self.get_session(session_id)
        cleaned = query.strip()
        lower = cleaned.lower()

        compared = self._clean_entities(
            session.get("last_compared_entities", [])
        )

        active_comparison = bool(
            session.get("active_comparison") and len(compared) >= 2
        )

        # ---------------------------------------------------------
        # 1. Recover an implicit comparison from recent turns.
        #
        # Example:
        #   User: What is TCP?
        #   User: What is UDP?
        #   User: Which one is faster?
        #
        # update_turn() runs after the current answer, so the current
        # follow-up cannot rely on comparison state being created for
        # the current turn. Recover the two most recent distinct
        # entities from adjacent recent user turns instead.
        # ---------------------------------------------------------
        comparison_followup_starters = (
            "which one",
            "which is",
            "which would",
            "which has",
            "which performs",
            "what about",
            "how about",
        )

        # Check the immediately previous user message.
        # This is important because a new topic may have been asked
        # immediately before the current follow-up, while the old
        # comparison state is still active until update_turn() runs.
        previous_user_message = str(
            session.get("last_user_message") or ""
        ).strip()

        previous_entities = self._clean_entities(
            self.extract_entities(previous_user_message)
        )

        previous_has_new_topic = bool(
            previous_entities
            and not any(
                entity.lower() in {
                    item.lower() for item in compared
                }
                for entity in previous_entities
            )
        )

        # If the previous user turn clearly introduced a new subject,
        # never attach the current follow-up to the old comparison.
        #
        # Example:
        #   What is TCP?
        #   What is UDP?
        #   Which one is faster?
        #   What is photosynthesis?
        #   Why is it important?
        #
        # The last question must resolve to photosynthesis, NOT TCP/UDP.
        if previous_has_new_topic:
            active_comparison = False
            compared = []
            session["active_comparison"] = False
            session["last_compared_entities"] = []

        is_comparison_followup = (
            lower in {
                "which one",
                "which is better",
                "which is faster",
                "which is slower",
                "which is easier",
                "which is safer",
                "which is cheaper",
                "which is more reliable",
                "which would you choose",
                "what about performance",
                "what about jobs",
                "why",
            }
            or lower.startswith(comparison_followup_starters)
        )

        if not active_comparison and is_comparison_followup:
            recent_topics = session.get("recent_topics", [])

            if len(recent_topics) >= 2:
                compared = recent_topics[-2:]
                active_comparison = True

                session["last_compared_entities"] = compared[:]
                session["active_comparison"] = True

                session["last_subject"] = {
                    "type": "comparison",
                    "entities": compared[:],
                }
            else:
                history = session.get("conversation_history", [])

                # ---------------------------------------------------------
                # IMPORTANT:
                # Only inspect the immediately preceding user turns.
                #
                # Never search deep history for a comparison because that
                # can incorrectly turn:
                #
                #   TCP
                #   UDP
                #   ...
                #   Photosynthesis
                #   Why is it important?
                #
                # into a TCP/UDP question.
                # ---------------------------------------------------------
                recent_user_turns = []

                for turn in reversed(history[-3:]):
                    if not isinstance(turn, dict):
                        continue

                    user_message = str(
                        turn.get("user", "")
                    ).strip()

                    if not user_message:
                        continue

                    recent_user_turns.append(user_message)

                    if len(recent_user_turns) >= 2:
                        break

                recent_entities = []

                for user_message in recent_user_turns:
                    entities = self._clean_entities(
                        self.extract_entities(user_message)
                    )

                    if not entities:
                        continue

                    entity = entities[0]

                    if not any(
                        entity.lower() == existing.lower()
                        for existing in recent_entities
                    ):
                        recent_entities.append(entity)

                # Only recover an implicit comparison when BOTH
                # immediately recent turns contain distinct entities.
                if len(recent_entities) == 2:
                    compared = list(reversed(recent_entities[:2]))

                    active_comparison = True

                    session["last_compared_entities"] = compared[:]
                    session["active_comparison"] = True

                    session["last_subject"] = {
                        "type": "comparison",
                        "entities": compared[:],
                    }

        # ---------------------------------------------------------
        # 2. Resolve direct comparison follow-ups.
        # ---------------------------------------------------------
        if active_comparison:
            a, b = compared[0], compared[1]

            if (
                lower in {
                    "which one",
                    "which is better",
                    "which is faster",
                    "which is slower",
                    "which is easier",
                    "which is safer",
                    "which is cheaper",
                    "which is more reliable",
                    "which would you choose",
                    "what about performance",
                    "what about jobs",
                }
                or lower.startswith(
                    (
                        "which one ",
                        "which is ",
                        "which would ",
                        "which has ",
                        "which performs ",
                        "what about ",
                        "how about ",
                    )
                )
            ):
                return f"{cleaned} between {a} and {b}."

            # "Why?" should inherit the previous comparison rather than
            # resolving against the dictionary-shaped last_subject.
            if lower == "why":
                previous_question = str(
                    session.get("last_question") or ""
                ).lower()

                if "faster" in previous_question:
                    return f"Why is {b} generally faster than {a}?"

                if "slower" in previous_question:
                    return f"Why is {a} generally slower than {b}?"

                if "easier" in previous_question:
                    return f"Why is one of {a} and {b} easier?"

                if "better" in previous_question:
                    return f"Why is one of {a} and {b} better?"

                return f"Why is the difference between {a} and {b}?"

            if lower == "give example":
                return f"Give an example comparing {a} and {b}."

        # ---------------------------------------------------------
        # 3. Other lightweight references.
        #
        # For pronoun follow-ups such as:
        #
        #   What is photosynthesis?
        #   Why is it important?
        #   How does it work?
        #
        # prefer the most recent meaningful user question over an
        # old topic such as a greeting.
        # ---------------------------------------------------------

        subject = None

        # First try the most recent user message stored in the session.
        previous_user_message = str(
            session.get("last_user_message") or ""
        ).strip()

        if previous_user_message:
            previous_entities = self._clean_entities(
                self.extract_entities(previous_user_message)
            )

            if previous_entities:
                subject = previous_entities[0]

        # Fall back to normal conversational state.
        if not subject:
            subject = (
                session.get("current_topic")
                or session.get("last_subject")
                or session.get("last_entity")
            )

        # Pronoun-based follow-ups should inherit the previous subject.
        pronoun_followup = bool(
            re.search(
                r"\b(it|this|that|these|those)\b",
                lower,
                re.IGNORECASE,
            )
        )

        if pronoun_followup and subject:
            words = cleaned.split()

            words = [
                str(subject) if word.lower() in {
                    "it",
                    "this",
                    "that",
                    "these",
                    "those",
                } else word
                for word in words
            ]

            return " ".join(words)

        if isinstance(subject, dict):
            subject_entities = subject.get("entities") or []
            if subject_entities:
                subject = " and ".join(map(str, subject_entities))
            else:
                subject = subject.get("type") or None

        if lower == "python example":
            return "Give a Python example."

        if lower == "java example":
            return "Give a Java example."

        if lower == "which is easier" and active_comparison:
            a, b = compared[0], compared[1]
            return f"Which is easier between {a} and {b}?"

        if not subject:
            return cleaned

        if lower.startswith("compare it with "):
            other = cleaned[len("compare it with "):]
            return f"Compare {subject} with {other}"

        if lower.startswith("compare it to "):
            other = cleaned[len("compare it to "):]
            return f"Compare {subject} to {other}"

        if lower == "why":
            return f"Why is {subject} important?"

        if lower.startswith("why "):
            remainder = cleaned[4:].strip()

            if remainder:
                return f"Why is {subject} {remainder}"

            return f"Why is {subject} important?"

        if lower == "continue":
            return f"Continue explaining {subject}"

        if lower == "more":
            return f"Tell me more about {subject}"

        words = cleaned.split()

        words = [
            str(subject)
            if w.lower() in ("it", "this", "that", "these", "those")
            else w
            for w in words
        ]

        return " ".join(words)
