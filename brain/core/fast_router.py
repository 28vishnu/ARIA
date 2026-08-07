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


def should_fast_route(query: str) -> FastDecision:
    q = query.strip().lower()

    if len(q) <= 20:
        if any(q.startswith(x) for x in FAST_PREFIXES):
            return FastDecision(True, "greeting")

    if len(q.split()) <= 5:
        return FastDecision(True, "simple")

    return FastDecision(False, "complex")