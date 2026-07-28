from dataclasses import dataclass


@dataclass
class Intent:
    name: str
    confidence: float


class IntentAnalyzer:
    """
    Performs lightweight intent classification.
    """

    async def analyze(self, query: str) -> Intent:
        q = query.lower().strip()

        # Greeting
        greetings = {
            "hi", "hello", "hey",
            "good morning",
            "good afternoon",
            "good evening"
        }

        if q in greetings:
            return Intent("greeting", 0.99)

        # Memory Delete
        if q.startswith(("forget", "delete", "remove", "clear")):
            return Intent("memory_delete", 0.99)

        # Memory Store / Update
        if (
            q.startswith(("my ", "i am", "i'm"))
            and any(x in q for x in (
                " is ",
                " like ",
                " love ",
                " prefer "
            ))
        ):
            return Intent("memory_store", 0.96)

        # Memory Recall
        if (
            q.startswith((
                "what is my",
                "what's my",
                "who is my",
                "where is my",
                "when is my",
                "which is my",
                "recall",
                "remember"
            ))
            or "favorite" in q
            or "favourite" in q
            or "birthday" in q
            or "dob" in q
        ):
            return Intent("memory_recall", 0.97)

        # Planner
        if any(word in q for word in (
            "create",
            "build",
            "generate",
            "develop",
            "design",
            "make"
        )):
            return Intent("planner", 0.92)

        # Continue previous conversation
        if q in (
            "continue",
            "go on",
            "tell me more",
            "explain more",
            "next"
        ):
            return Intent("continue", 0.90)

        # Writing
        if any(word in q for word in [
            "write",
            "email",
            "letter",
            "essay",
            "article",
            "blog",
            "story",
            "poem",
            "professional"
        ]):
            return Intent("writing", 0.93)

        # Default chat
        return Intent("chat", 0.80)
