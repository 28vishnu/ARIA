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


FAST_CHAT_WORDS = (
    "how are you",
    "who are you",
    "what is your name",
    "good night",
    "goodbye",
    "bye",
    "ok",
    "okay",
    "yes",
    "no",
)


def should_fast_route(query: str) -> FastDecision:
    q = query.strip().lower()

    # Greetings
    if any(q.startswith(x) for x in FAST_PREFIXES):
        return FastDecision(True, "greeting")

    # Casual conversation
    if q in FAST_CHAT_WORDS:
        return FastDecision(True, "chat")

    # Coding / explanations should go directly to the LLM
    coding_keywords = (
        "write",
        "code",
        "python",
        "flask",
        "fastapi",
        "javascript",
        "typescript",
        "react",
        "next",
        "html",
        "css",
        "sql",
        "java",
        "c++",
        "api",
        "algorithm",
        "explain",
        "debug",
    )

    if any(word in q for word in coding_keywords):
        return FastDecision(True, "coding")

    # Very short chat
    if len(q.split()) <= 6:
        return FastDecision(True, "simple")

    return FastDecision(False, "complex")