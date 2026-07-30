from dataclasses import dataclass
import re


@dataclass
class Intent:
    name: str
    confidence: float


class IntentAnalyzer:
    """
    ARIA's first-stage intent understanding layer.

    Fast, obvious intents can be recognised locally.

    Ambiguous natural-language requests can be delegated to the
    language model so ARIA does not require an ever-growing list
    of hard-coded phrases.
    """

    def __init__(self, llm_router=None):
        self.llm_router = llm_router

    async def analyze(self, query: str) -> Intent:
        q = self._normalize(query)

        if not q:
            return Intent("chat", 0.50)

        # =====================================================
        # GREETING
        # =====================================================

        greetings = {
            "hi",
            "hello",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
        }

        if q in greetings:
            return Intent("greeting", 0.99)

        # =====================================================
        # DOCUMENT DELETE
        # =====================================================

        if self._looks_like_document_delete_all(q):
            return Intent("delete_all_documents", 0.99)

        if self._looks_like_document_delete(q):
            return Intent("delete_document", 0.99)

        # =====================================================
        # MEMORY DELETE
        # =====================================================

        if q.startswith((
            "forget ",
            "delete ",
            "remove ",
            "clear ",
        )):
            return Intent("memory_delete", 0.99)

        # =====================================================
        # EXPLICIT MEMORY LANGUAGE
        # =====================================================

        if self._contains_any(q, (
            "remember that ",
            "remember this ",
            "remember my ",
            "save that ",
            "save this ",
            "store that ",
            "store this ",
            "keep this in mind",
        )):
            return Intent("memory_store", 0.99)

        # =====================================================
        # DOCUMENT REQUESTS
        # =====================================================

        # User wants the original stored document/file returned.
        if self._looks_like_document_retrieval(q):
            return Intent("document_retrieve", 0.99)

        # User wants to know which documents ARIA has.
        if self._looks_like_document_listing(q):
            return Intent("document_list", 0.98)

        # User is asking about the contents of a stored document.
        if self._looks_like_document_question(q):
            return Intent("document_query", 0.97)

        # =====================================================
        # MEMORY RECALL
        # =====================================================

        if self._looks_like_personal_recall(q):
            return Intent("memory_recall", 0.97)

        # =====================================================
        # MEMORY STORE / PERSONAL FACT
        # =====================================================

        if self._looks_like_personal_statement(q):
            return Intent("memory_store", 0.94)

        # =====================================================
        # PYTHON EXECUTION
        # =====================================================

        if self._contains_any(q, (
            "run python",
            "execute python",
            "python code",
            "run code",
            "execute code",
            "python script",
            "print(",
        )):
            return Intent("python", 0.96)

        # =====================================================
        # CONTINUATION
        # =====================================================

        if q in {
            "continue",
            "go on",
            "tell me more",
            "explain more",
            "next",
            "and",
            "then",
        }:
            return Intent("continue", 0.90)

        # =====================================================
        # WRITING
        # =====================================================

        if self._contains_any(q, (
            "write ",
            "write an ",
            "write a ",
            "email ",
            "letter ",
            "essay ",
            "article ",
            "blog ",
            "story ",
            "poem ",
        )):
            return Intent("writing", 0.93)

        # =====================================================
        # EXPLICIT ACTION REQUEST
        # =====================================================

        if self._looks_like_action_request(q):
            return Intent("planner", 0.90)

        # =====================================================
        # SEMANTIC INTENT UNDERSTANDING
        # =====================================================
        #
        # Local rules above handle obvious/high-confidence cases.
        # Anything still ambiguous is understood semantically
        # instead of adding more and more keyword rules.
        # =====================================================

        semantic_intent = await self._semantic_intent(query)

        if (
            semantic_intent is not None
            and semantic_intent.confidence >= 0.70
        ):
            return semantic_intent

        # =====================================================
        # SAFE DEFAULT
        # =====================================================

        return Intent("chat", 0.80)

    # =========================================================
    # DOCUMENT INTENTS
    # =========================================================

    def _looks_like_document_delete_all(self, q: str) -> bool:
        """
        Detect requests to delete all stored documents.
        """

        patterns = (
            "delete all documents",
            "delete all my documents",
            "delete all pdfs",
            "delete all my pdfs",
            "delete all files",
            "delete all my files",
            "remove all documents",
            "remove all my documents",
            "remove all pdfs",
            "remove all my pdfs",
            "clear all documents",
            "clear my documents",
        )

        return self._contains_any(q, patterns)

    def _looks_like_document_delete(self, q: str) -> bool:
        """
        Detect requests to delete a specific stored document.

        Examples:
            Delete my resume
            Remove my CV
            Delete project report PDF
        """

        document_words = (
            "pdf",
            "document",
            "file",
            "resume",
            "cv",
            "report",
        )

        delete_words = (
            "delete",
            "remove",
        )

        has_document = any(
            word in q
            for word in document_words
        )

        has_delete = any(
            word in q
            for word in delete_words
        )

        return has_document and has_delete

    def _looks_like_document_retrieval(self, q: str) -> bool:
        """
        Detect requests for ARIA to return an original stored file.

        Examples:
            Give me my resume PDF
            Send my resume
            Get my CV
            Give me the project report
        """

        document_words = (
            "pdf",
            "document",
            "file",
            "resume",
            "cv",
            "report",
        )

        retrieval_words = (
            "give",
            "send",
            "get",
            "return",
            "download",
            "share",
            "show",
        )

        has_document = any(
            word in q
            for word in document_words
        )

        has_retrieval = any(
            word in q
            for word in retrieval_words
        )

        return has_document and has_retrieval

    def _looks_like_document_listing(self, q: str) -> bool:
        """
        Detect requests to list stored documents.
        """

        patterns = (
            "list my documents",
            "list my pdfs",
            "show my documents",
            "show my pdfs",
            "what documents do you have",
            "what pdfs do you have",
            "which documents do you have",
            "which pdfs do you have",
            "what files do you have",
            "list my files",
        )

        return self._contains_any(
            q,
            patterns
        )

    def _looks_like_document_question(self, q: str) -> bool:
        """
        Detect questions about document contents.

        Examples:
            Summarise my resume
            What skills are in my resume?
            What does my resume say?
            Explain my project PDF
        """

        document_words = (
            "pdf",
            "document",
            "resume",
            "cv",
            "report",
        )

        question_words = (
            "summarize",
            "summarise",
            "summary",
            "explain",
            "what",
            "which",
            "who",
            "where",
            "when",
            "how",
            "tell me about",
            "according to",
        )

        has_document = any(
            word in q
            for word in document_words
        )

        has_question = any(
            word in q
            for word in question_words
        )

        return has_document and has_question

    # =========================================================
    # PERSONAL MEMORY RECALL
    # =========================================================

    def _looks_like_personal_recall(self, q: str) -> bool:
        """
        Detect questions asking ARIA about previously known
        information concerning the user.

        The important distinction is:

        "What is Python?"
            -> general knowledge

        "What am I studying?"
            -> personal memory

        "Which country was I interested in?"
            -> personal memory

        "Where was I planning to study?"
            -> personal memory
        """

        # Explicit remembering language
        if self._contains_any(q, (
            "do you remember",
            "did you remember",
            "can you remember",
            "what do you remember",
            "what did i tell you",
            "what have i told you",
            "did i tell you",
            "recall my",
            "remember my",
        )):
            return True

        # Strong first-person ownership
        personal_markers = (
            " my ",
            " i ",
            " me ",
            " mine ",
        )

        padded = f" {q} "

        has_personal_reference = any(
            marker in padded
            for marker in personal_markers
        )

        # Questions about the user's own state/history/plans
        first_person_patterns = (
            r"\bwhat am i\b",
            r"\bwho am i\b",
            r"\bwhere am i\b",
            r"\bwhen am i\b",
            r"\bwhich .* was i\b",
            r"\bwhat .* was i\b",
            r"\bwhere .* was i\b",
            r"\bwhen .* was i\b",
            r"\bwhat .* did i\b",
            r"\bwhere .* did i\b",
            r"\bwhich .* did i\b",
            r"\bwhat .* do i\b",
            r"\bwhere .* do i\b",
            r"\bwhich .* do i\b",
            r"\bwhat .* have i\b",
            r"\bwhere .* have i\b",
            r"\bwhich .* have i\b",
        )

        if any(
            re.search(pattern, q)
            for pattern in first_person_patterns
        ):
            return True

        # Possessive personal questions
        question_starters = (
            "what",
            "what's",
            "who",
            "where",
            "when",
            "which",
            "how",
        )

        if (
            q.startswith(question_starters)
            and has_personal_reference
        ):
            return True

        # Personal plans/preferences/history
        personal_subjects = (
            "my plan",
            "my goal",
            "my preference",
            "my favourite",
            "my favorite",
            "my birthday",
            "my name",
            "my degree",
            "my college",
            "my university",
            "my project",
            "my career",
            "my future",
            "my destination",
            "my country",
            "my education",
        )

        if self._contains_any(q, personal_subjects):
            return True

        return False

    # =========================================================
    # PERSONAL STATEMENT / MEMORY CANDIDATE
    # =========================================================

    def _looks_like_personal_statement(self, q: str) -> bool:
        """
        Detect likely user facts/preferences/plans.

        The MemoryEngine remains responsible for deciding whether
        the information is actually worth storing.
        """

        personal_starts = (
            "i am ",
            "i'm ",
            "im ",
            "i study ",
            "i work ",
            "i live ",
            "i prefer ",
            "i like ",
            "i love ",
            "i hate ",
            "i want ",
            "i plan ",
            "i'm planning ",
            "i am planning ",
            "my name ",
            "my favorite ",
            "my favourite ",
            "my goal ",
            "my plan ",
            "my preference ",
            "my college ",
            "my university ",
            "my degree ",
        )

        if q.startswith(personal_starts):
            return True

        # Natural future-plan statements
        if (
            q.startswith("i ")
            and self._contains_any(q, (
                " planning to ",
                " want to ",
                " hope to ",
                " intend to ",
                " prefer to ",
                " would like to ",
            ))
        ):
            return True

        return False

    # =========================================================
    # SEMANTIC INTENT UNDERSTANDING
    # =========================================================

    async def _semantic_intent(self, query: str) -> Intent | None:
        """
        Uses ARIA's language intelligence when local rules cannot
        confidently understand the user's intention.

        This avoids requiring hard-coded phrases for every possible
        way a person can express the same meaning.
        """

        if not self.llm_router:
            return None

        system_prompt = """
You are ARIA's intent understanding system.

Determine what the user is trying to do from meaning, not keywords.

Available intents:

memory_store
- The user is telling ARIA a personal fact, preference, plan,
  decision, background detail, or something useful to remember.

memory_recall
- The user is asking ARIA about information previously shared
  about themselves.

memory_delete
- The user wants stored personal information forgotten.

planner
- The user wants ARIA to create a plan, roadmap, schedule,
  strategy, or organised sequence of actions.

writing
- The user wants text written, rewritten, edited, or drafted.

python
- The user explicitly wants Python code executed.

greeting
- The message is primarily a greeting.

chat
- General questions, explanations, conversation, or anything
  that does not belong to the intents above.

Important distinction:

"I had a backup plan for my master's. It's Germany."
=> memory_store

"Make me a backup plan for doing my master's in Germany."
=> planner

"My favourite car is Porsche."
=> memory_store

"What car did I say I liked?"
=> memory_recall

"What is a Porsche?"
=> chat

Return ONLY valid JSON:

{
  "intent": "chat",
  "confidence": 0.95
}
"""

        try:
            response = await self.llm_router.chat(
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": query
                    }
                ],
                temperature=0.0,
                max_tokens=100
            )

            cleaned = str(response).strip()

            if cleaned.startswith("```"):
                cleaned = re.sub(
                    r"^```(?:json)?\s*",
                    "",
                    cleaned,
                    flags=re.IGNORECASE
                )
                cleaned = re.sub(
                    r"\s*```$",
                    "",
                    cleaned
                ).strip()

            import json

            data = json.loads(cleaned)

            intent_name = str(
                data.get("intent", "")
            ).strip().lower()

            confidence = float(
                data.get("confidence", 0.0)
            )

            allowed = {
                "memory_store",
                "memory_recall",
                "memory_delete",
                "planner",
                "writing",
                "python",
                "greeting",
                "chat",
            }

            if intent_name not in allowed:
                return None

            confidence = max(
                0.0,
                min(confidence, 1.0)
            )

            return Intent(
                intent_name,
                confidence
            )

        except Exception:
            return None

    # =========================================================
    # ACTION REQUEST
    # =========================================================

    def _looks_like_action_request(self, q: str) -> bool:
        """
        Planner detection should focus on actual commands,
        not merely the presence of words such as 'make'.
        """

        action_starts = (
            "create ",
            "build ",
            "generate ",
            "develop ",
            "design ",
            "make ",
        )

        return q.startswith(action_starts)

    # =========================================================
    # HELPERS
    # =========================================================

    def _contains_any(self, text: str, phrases) -> bool:
        return any(
            phrase in text
            for phrase in phrases
        )

    def _normalize(self, query: str) -> str:
        return re.sub(
            r"\s+",
            " ",
            str(query or "").lower()
        ).strip()
