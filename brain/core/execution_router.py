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
    RESEARCH = "research"
    WEB = "web"
    TASK = "task"
    AUTOMATION = "automation"


@dataclass
class RouteDecision:
    route: Route
    confidence: float


CODING_VERBS = (
    "write",
    "create",
    "build",
    "generate",
    "implement",
    "fix",
    "debug",
    "explain",
    "optimize",
    "convert",
    "refactor",
)

CODING_TECH = (
    "python",
    "flask",
    "fastapi",
    "react",
    "next",
    "javascript",
    "typescript",
    "sql",
    "api",
    "docker",
    "java",
    "c++",
    "django",
    "algorithm",
    "github",
    "bug",
    "code",
)


def decide(query: str) -> RouteDecision:
    q = query.lower().strip()

    # Greetings
    if any(q.startswith(x) for x in (
        "hi",
        "hello",
        "hey",
        "good morning",
        "good evening",
    )):
        return RouteDecision(Route.GREETING, 1.0)

    # Coding
    if (
        any(v in q for v in CODING_VERBS)
        and
        any(t in q for t in CODING_TECH)
    ):
        return RouteDecision(Route.CODING, 0.98)

    # Memory
    if any(word in q for word in (
        "remember",
        "recall",
        "memory",
        "my name",
        "what do you know about me",
        "favorite",
        "favourite",
        "did i tell you",
    )):
        return RouteDecision(Route.MEMORY, 0.97)

    # Planning
    if any(word in q for word in (
        "plan",
        "roadmap",
        "schedule",
        "strategy",
        "goal",
        "career",
        "study plan",
    )):
        return RouteDecision(Route.PLANNER, 0.95)

    # Documents
    if any(word in q for word in (
        "pdf",
        "document",
        "notes",
        "ppt",
        "docx",
        "summarize",
        "summary",
    )):
        return RouteDecision(Route.DOCUMENT, 0.95)

    # Vision
    if any(word in q for word in (
        "image",
        "photo",
        "picture",
        "scan",
        "ocr",
        "camera",
    )):
        return RouteDecision(Route.VISION, 0.95)

    # Research / Web
    if any(word in q for word in (
        "latest",
        "news",
        "research",
        "compare",
        "search",
        "find",
    )):
        return RouteDecision(Route.RESEARCH, 0.95)

    # Task
    if any(word in q for word in (
        "remind",
        "todo",
        "task",
        "complete",
        "finish",
    )):
        return RouteDecision(Route.TASK, 0.95)

    return RouteDecision(Route.CHAT, 0.80)
