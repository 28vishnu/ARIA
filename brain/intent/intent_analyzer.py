from dataclasses import dataclass
import re


@dataclass
class Intent:
    name: str
    confidence: float


class IntentAnalyzer:
    """
    Lightweight first-stage intent classifier.

    This layer identifies broad conversational intent.
    It should recognize natural variations without trying
    to understand every possible sentence through hard-coded rules.
    """

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
        # PLANNER
        # =====================================================

        if self._looks_like_action_request(q):
            return Intent("planner", 0.90)

        # =====================================================
        # DEFAULT CONVERSATION
        # =====================================================

        return Intent("chat", 0.80)

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
