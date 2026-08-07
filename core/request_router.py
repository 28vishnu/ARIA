from enum import Enum


class Route(str, Enum):
    GREETING = "greeting"
    DOCUMENT = "document"
    MEMORY = "memory"
    VISION = "vision"
    TOOL = "tool"
    PLANNER = "planner"
    GENERAL = "general"


class RequestRouter:
    def route(self, intent: str) -> Route:
        intent = (intent or "").lower()

        if intent in ("greeting", "hello", "hi"):
            return Route.GREETING

        if "document" in intent or "pdf" in intent:
            return Route.DOCUMENT

        if "vision" in intent or "image" in intent:
            return Route.VISION

        if "memory" in intent:
            return Route.MEMORY

        if "tool" in intent or "action" in intent:
            return Route.TOOL

        if "plan" in intent or "task" in intent:
            return Route.PLANNER

        return Route.GENERAL
