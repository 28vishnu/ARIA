import re
from enum import Enum
from dataclasses import dataclass


class Route(str, Enum):
    GREETING = "greeting"
    CHAT = "chat"
    CODING = "coding"
    TIME = "time"
    WEATHER = "weather"
    MEMORY = "memory"
    DOCUMENT = "document"
    VISION = "vision"
    TOOL = "tool"
    PLANNER = "planner"
    RESEARCH = "research"
    WEB = "web"
    TASK = "task"
    AUTOMATION = "automation"
    CALCULATOR = "calculator"


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

CONTEXTUAL_CALCULATOR_PHRASES = (
    "add ",
    "plus ",
    "subtract ",
    "minus ",
    "multiply ",
    "times ",
    "divide ",
    "divided by ",
    "multiply by ",
    "times by ",
    "add by ",
    "subtract by ",
    "increase by ",
    "decrease by ",
    "double ",
    "triple ",
    "half ",
    "half of ",
)


# =========================================================
# ACTION / EXECUTION REQUESTS
# =========================================================
#
# These phrases describe requests where ARIA should perform
# an action instead of merely generating a conversational
# response.
#
# Such requests should enter the Planner → Executor pipeline.
# =========================================================

ACTION_VERBS = (
    "create",
    "write",
    "read",
    "delete",
    "remove",
    "rename",
    "move",
    "copy",
    "save",
    "open",
    "close",
    "send",
    "notify",
    "notification",
    "set",
    "change",
    "update",
    "download",
    "upload",
    "run",
    "execute",
)

ACTION_TARGETS = (
    "file",
    "folder",
    "directory",
    "notification",
    "alert",
    "message",
    "reminder",
)


def contains_weather_term(q: str) -> bool:
    weather_terms = (
        "weather",
        "temperature",
        "forecast",
        "rain",
        "raining",
        "sunny",
        "cloudy",
        "humidity",
        "wind",
        "snow",
        "storm",
        "thunderstorm",
        "precipitation",
        "climate",
        "hot",
        "cold",
    )

    return any(
        re.search(rf"\b{re.escape(term)}\b", q)
        for term in weather_terms
    )


def contains_file_reference(q: str) -> bool:
    """
    Detect likely file references.

    Examples:
        test.txt
        notes.md
        data.json
        report.pdf
    """

    return bool(
        re.search(
            r"\b[\w\-]+\.(?:"
            r"txt|md|json|csv|py|js|ts|html|css|"
            r"pdf|docx|xlsx|pptx"
            r")\b",
            q,
            re.IGNORECASE,
        )
    )


def decide(
    query: str,
    context: dict | None = None,
) -> RouteDecision:
    q = query.lower().strip()

    # =========================================================
    # PHASE 4 — ACTIVE AUTONOMOUS GOAL
    # =========================================================
    #
    # If ARIA is currently working toward an autonomous goal,
    # ordinary follow-up requests should remain inside the
    # planner/workflow pipeline even when the user does not
    # explicitly say "plan", "goal", or "steps".
    # =========================================================
    context = context or {}

    autonomous_goal = (
        context.get("autonomous_goal")
        or context.get("goal")
    )

    if isinstance(autonomous_goal, dict):
        autonomous_goal_id = str(
            autonomous_goal.get(
                "goal_id",
                "",
            )
            or ""
        ).strip()

        if autonomous_goal_id:
            logger.info(
                "[ExecutionRouter] Active autonomous goal detected: %s",
                autonomous_goal.get("title", ""),
            )

            return RouteDecision(
                Route.PLANNER,
                0.99,
            )

    # Greetings
    if any(q.startswith(x) for x in (
        "hi",
        "hello",
        "hey",
        "good morning",
        "good evening",
    )):
        return RouteDecision(Route.GREETING, 1.0)

    # Time
    if any(word in q for word in (
        "what time",
        "current time",
        "local time",
        "time in",
        "what's the time",
        "whats the time",
        "tell me the time",
        "clock",
    )):
        return RouteDecision(Route.TIME, 0.99)

    # Weather
    if contains_weather_term(q):
        return RouteDecision(Route.WEATHER, 0.99)

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

    # Calculator / deterministic mathematics
    if (
        any(word in q for word in (
            "calculate",
            "calculator",
            "compute",
            "solve",
            "what is",
        ))
        and any(
            symbol in q
            for symbol in (
                "+",
                "-",
                "*",
                "/",
                "%",
                "^",
                "×",
                "÷",
            )
        )
    ):
        return RouteDecision(Route.CALCULATOR, 0.99)

    # Direct arithmetic expression
    if (
        any(symbol in q for symbol in (
            "+",
            "*",
            "/",
            "%",
            "^",
            "×",
            "÷",
        ))
        and any(char.isdigit() for char in q)
    ):
        return RouteDecision(Route.CALCULATOR, 0.99)

    # Contextual calculator follow-up
    if any(
        phrase in q
        for phrase in CONTEXTUAL_CALCULATOR_PHRASES
    ):
        return RouteDecision(Route.CALCULATOR, 0.98)

    # =========================================================
    # ACTION EXECUTION
    # =========================================================
    #
    # Detect requests that require ARIA to actually perform an
    # action. These must go through:
    #
    # Planner
    #     ↓
    # ExecutionPlan
    #     ↓
    # Executor
    #     ↓
    # ActionManager
    #
    # Instead of falling through to normal CHAT / LLM response.
    # =========================================================
    if (
        any(
            re.search(
                rf"\b{re.escape(verb)}\b",
                q,
            )
            for verb in ACTION_VERBS
        )
        and
        (
            any(
                re.search(
                    rf"\b{re.escape(target)}\b",
                    q,
                )
                for target in ACTION_TARGETS
            )
            or contains_file_reference(q)
        )
    ):
        return RouteDecision(
            Route.PLANNER,
            0.98,
        )

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
