from enum import Enum
from dataclasses import dataclass


class Route(str, Enum):
    GREETING = "greeting"
    CHAT = "chat"
    CODING = "coding"
    MEMORY = "memory"
    DOCUMENT = "document"
    VISION = "vision"
    TOOL = "tool"
    PLANNER = "planner"


@dataclass
class RouteDecision:
    route: Route
    confidence: float


def decide(query: str) -> RouteDecision:
    q = query.lower()

    if any(
        q.startswith(x)
        for x in (
            "hi",
            "hello",
            "hey",
            "good morning",
            "good evening",
        )
    ):
        return RouteDecision(Route.GREETING, 1.0)

    if any(
        word in q
        for word in (
            "python",
            "flask",
            "fastapi",
            "react",
            "next",
            "javascript",
            "typescript",
            "code",
            "algorithm",
            "debug",
            "api",
            "sql",
        )
    ):
        return RouteDecision(Route.CODING, 0.95)

    if any(
        word in q
        for word in (
            "remember",
            "memory",
            "my name",
            "what do you know about me",
        )
    ):
        return RouteDecision(Route.MEMORY, 0.95)

    return RouteDecision(Route.PLANNER, 0.8)