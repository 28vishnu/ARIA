import re


class ConversationStyle:
    """
    Final presentation layer for ARIA.

    This layer should make responses feel controlled, intelligent and
    assistant-like without changing the factual meaning produced by
    the underlying LLM, memory system, document system or tools.
    """

    @staticmethod
    def apply(reply: str) -> str:

        if not reply:
            return ""

        reply = str(reply).strip()

        if not reply:
            return ""

        # -----------------------------------------------------
        # Protect code-heavy responses
        # -----------------------------------------------------

        if "```" in reply:
            return ConversationStyle._clean_code_response(reply)

        # -----------------------------------------------------
        # Remove common generic chatbot openings
        # -----------------------------------------------------

        reply = ConversationStyle._remove_generic_openings(reply)

        # -----------------------------------------------------
        # Clean excessive Markdown / visual noise
        # -----------------------------------------------------

        reply = ConversationStyle._clean_markdown(reply)

        # -----------------------------------------------------
        # Remove generic chatbot endings
        # -----------------------------------------------------

        reply = ConversationStyle._remove_generic_endings(reply)

        # -----------------------------------------------------
        # Clean spacing
        # -----------------------------------------------------

        reply = ConversationStyle._clean_spacing(reply)

        return reply.strip()

    @staticmethod
    def follow_up(reply: str, query: str) -> str:
        """
        ARIA should not automatically attach generic offers after every
        response. A follow-up should only exist when the actual answer
        naturally requires one.

        Therefore the personality layer does not manufacture follow-ups.
        """

        return reply.strip()

    # =========================================================
    # CLEANING
    # =========================================================

    @staticmethod
    def _remove_generic_openings(reply: str) -> str:

        patterns = [
            r"^\s*certainly[.!,:-]*\s*",
            r"^\s*absolutely[.!,:-]*\s*",
            r"^\s*of course[.!,:-]*\s*",
            r"^\s*sure[.!,:-]*\s*",
            r"^\s*here'?s what i found[.!:]*\s*",
            r"^\s*here'?s a detailed explanation[.!:]*\s*",
            r"^\s*i'?ve broken it down below[.!:]*\s*",
            r"^\s*i'?d be happy to help[.!,:-]*\s*",
            r"^\s*i'?d be glad to help[.!,:-]*\s*",
        ]

        for pattern in patterns:
            reply = re.sub(
                pattern,
                "",
                reply,
                count=1,
                flags=re.IGNORECASE
            )

        return reply.strip()

    @staticmethod
    def _remove_generic_endings(reply: str) -> str:

        patterns = [
            r"\s*Would you like me to .*?\?\s*$",
            r"\s*Do you want me to .*?\?\s*$",
            r"\s*Need me to .*?\?\s*$",
            r"\s*I can also .*? if you'd like\.?\s*$",
            r"\s*I can expand this into a complete plan\.?\s*$",
            r"\s*Let me know if you'd like .*?\.?\s*$",
            r"\s*Let me know if you want .*?\.?\s*$",
            r"\s*Feel free to ask .*?\.?\s*$",
            r"\s*Feel free to let me know .*?\.?\s*$",
            r"\s*Hope this helps[.!]*\s*$",
            r"\s*I hope this helps[.!]*\s*$",
        ]

        changed = True

        while changed:
            old = reply

            for pattern in patterns:
                reply = re.sub(
                    pattern,
                    "",
                    reply,
                    flags=re.IGNORECASE | re.DOTALL
                )

            changed = reply != old

        return reply.strip()

    @staticmethod
    def _clean_markdown(reply: str) -> str:

        # Remove Markdown heading markers while preserving heading text.
        reply = re.sub(
            r"(?m)^\s*#{1,6}\s+",
            "",
            reply
        )

        # Remove decorative underline headings:
        #
        # Python Overview
        # ===============
        #
        reply = re.sub(
            r"(?m)^\s*[=-]{4,}\s*$",
            "",
            reply
        )

        # Convert bold text to normal text.
        reply = re.sub(
            r"\*\*(.*?)\*\*",
            r"\1",
            reply,
            flags=re.DOTALL
        )

        # Remove stray emphasis markers.
        reply = re.sub(
            r"(?<!\*)\*(?!\*)",
            "",
            reply
        )

        # Convert Markdown bullets to a cleaner bullet.
        reply = re.sub(
            r"(?m)^\s*[-*]\s+",
            "• ",
            reply
        )

        return reply

    @staticmethod
    def _clean_spacing(reply: str) -> str:

        # Remove trailing spaces from lines.
        reply = "\n".join(
            line.rstrip()
            for line in reply.splitlines()
        )

        # Never allow huge empty areas.
        reply = re.sub(
            r"\n{3,}",
            "\n\n",
            reply
        )

        # Remove spaces before punctuation.
        reply = re.sub(
            r"\s+([,.!?;:])",
            r"\1",
            reply
        )

        return reply.strip()

    @staticmethod
    def _clean_code_response(reply: str) -> str:
        """
        Avoid modifying code blocks because Markdown characters may be
        syntactically meaningful.

        We only remove known generic text appended after the response.
        """

        reply = ConversationStyle._remove_generic_endings(reply)

        return reply.strip()
