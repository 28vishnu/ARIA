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

        length = len(reply)

        if length < 80:
            return random.choice(ConversationStyle.SHORT).format(reply)

        elif length < 500:
            return random.choice(ConversationStyle.MEDIUM).format(reply)

        else:
            return random.choice(ConversationStyle.LONG).format(reply)