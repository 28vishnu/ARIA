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

MEMORY_QUERY_PREFIXES = (
    "what is my",
    "what's my",
    "do you remember",
    "who am i",
)

CODING_WORDS = (
    "code",
    "python",
    "flask",
    "fastapi",
    "java",
    "javascript",
    "c++",
    "api",
    "algorithm",
    "program",
    "sql",
)


def should_fast_route(query: str) -> FastDecision:
    q = query.strip().lower()

    if any(q.startswith(x) for x in FAST_PREFIXES):
        return FastDecision(True, "greeting")

    if any(q.startswith(x) for x in MEMORY_QUERY_PREFIXES):
        return FastDecision(True, "memory")

    if any(word in q for word in CODING_WORDS):
        return FastDecision(False, "coding")

    if len(q.split()) <= 2:
        return FastDecision(True, "simple")

    return FastDecision(False, "complex")
