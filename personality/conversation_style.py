import random


class ConversationStyle:

    SHORT = [
        "{}",
        "Certainly.\n\n{}",
        "Done.\n\n{}",
        "Of course.\n\n{}"
    ]

    MEDIUM = [
        "{}",
        "Here's what I found:\n\n{}",
        "Certainly.\n\n{}",
        "Absolutely.\n\n{}"
    ]

    LONG = [
        "{}",
        "Here's a detailed explanation.\n\n{}",
        "I've broken it down below.\n\n{}"
    ]

    @staticmethod
    def apply(reply: str) -> str:

        reply = reply.strip()

        if not reply:
            return ""

        # Never decorate code
        if "```" in reply:
            return reply

        # Never decorate greetings
        greetings = [
            "hello",
            "hi",
            "good morning",
            "good evening",
            "good afternoon",
            "greetings",
            "at your service"
        ]

        lower = reply.lower()

        if any(lower.startswith(x) for x in greetings):
            return reply

        # Short replies stay untouched
        if len(reply) < 80:
            return reply

        # Medium replies
        if len(reply) < 300:
            return random.choice([
                "{}",
                "Certainly.\n\n{}",
                "Here's what I found.\n\n{}"
            ]).format(reply)

        # Long replies
        return random.choice([
            "{}",
            "Here's a detailed explanation.\n\n{}"
        ]).format(reply)

    @staticmethod
    def follow_up(reply: str, query: str) -> str:

        q = query.lower()

        if any(x in q for x in ["email", "letter", "application"]):
            return reply + "\n\nWould you like me to tailor it for a specific person?"

        if any(x in q for x in ["python", "code", "program"]):
            return reply + "\n\nNeed me to explain or improve the code?"

        if any(x in q for x in ["math", "solve", "equation", "calculate"]):
            return reply + "\n\nI can also show the working if you'd like."

        if any(x in q for x in ["plan", "schedule"]):
            return reply + "\n\nI can expand this into a complete plan."

        return reply
