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

        # Don't decorate code blocks
        if "```" in reply:
            return reply

        # Very short replies (math, yes/no, quick facts)
        if len(reply) < 40:
            return reply

        # Medium replies
        if len(reply) < 250:
            return random.choice([
                "{}",
                "Certainly.\n\n{}",
                "Of course.\n\n{}",
                "Here's what I found.\n\n{}"
            ]).format(reply)

        # Long replies
        return random.choice([
            "{}",
            "Here's a detailed explanation.\n\n{}",
            "I've broken it down below.\n\n{}"
        ]).format(reply)

    @staticmethod
    def follow_up(reply: str, query:
