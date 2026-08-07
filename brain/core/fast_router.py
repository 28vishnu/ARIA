from dataclasses import dataclass


@dataclass
class FastDecision:
    fast: bool
    reason: str


FAST_PREFIXES = (
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "good morning",
    "good afternoon",
    "good evening",
)

MEMORY_PATTERNS = (
    "my name",
    "who am i",
    "remember",
    "recall",
    "what do you know about me",
    "my birthday",
    "my favourite",
    "my favorite",
    "what do i like",
    "what am i studying",
    "what do i study",
)


def should_fast_route(query: str) -> FastDecision:
    q = query.strip().lower()

    # Memory queries
    if any(x in q for x in MEMORY_PATTERNS):
        return FastDecision(True, "memory")

    # Greetings
    if any(q.startswith(x) for x in FAST_PREFIXES):
        return FastDecision(True, "greeting")

    # Coding
    coding_words = (
        "python",
        "flask",
        "java",
        "javascript",
        "react",
        "api",
        "code",
        "program",
        "function",
        "class",
        "algorithm",
    )

    if any(x in q for x in coding_words):
        return FastDecision(True, "coding")

    # Very short chat
    if len(q.split()) <= 5:
        return FastDecision(True, "simple")

    return FastDecision(False, "complex")