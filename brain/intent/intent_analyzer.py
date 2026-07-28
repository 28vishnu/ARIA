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

        greetings = {
            "hi", "hello", "hey", "good morning",
            "good evening", "good afternoon"
        }

        if q in greetings:
            return Intent("greeting", 0.99)

        if q.startswith(("remember", "recall", "what did i")):
            return Intent("memory", 0.95)

        if any(word in q for word in ("create", "build", "generate", "develop")):
            return Intent("task", 0.90)

        return Intent("general", 0.80)