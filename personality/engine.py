import logging
import random
import re
from typing import Dict, Any
from personality.response import SystemResponse
from personality.conversation_style import ConversationStyle

logger = logging.getLogger("aria")

class ResponseSource:
    """Constants for standardized routing of response sources."""
    CHAT = "chat"
    MEMORY = "memory"
    MEMORY_CONVERSATION = "memory_conversation"
    PROFILE = "profile"
    WEATHER = "weather"
    SEARCH = "search"
    TIME = "time"
    DATE = "date"
    CALCULATOR = "calculator"
    PLANNER = "planner_executor"
    GREETING = "greeting_fast_path"
    PLANNER_CONVERSATIONAL = "planner_conversational"


class PersonalityEngine:
    def __init__(self, llm_router=None):
        self.llm_router = llm_router

    def apply_personality(self, session_id: str, user_text: str, response: SystemResponse) -> str:
        """Transforms structured SystemResponse payloads into natural, contextual language."""
        try:
            if not response.success:
                return self._format_error(response.error)

            data = response.data or {}
            source = response.source
            intent = data.get("intent")

            # Route to specific private formatters
            if source == ResponseSource.TIME and "time" in data:
                reply = f"The current time is {data['time']}, Sir."
            elif source == ResponseSource.DATE and "date" in data:
                reply = f"Today is {data['date']}, Sir."
            elif source in [ResponseSource.WEATHER, ResponseSource.SEARCH] and "message" in data:
                reply = str(data["message"])
            elif source == ResponseSource.CHAT and "response" in data:
                reply = str(data["response"])
            elif source == "agent":
                if "response" in data:
                    reply = str(data["response"])
                elif "message" in data:
                    reply = str(data["message"])
                else:
                    reply = self._format_fallback(data)
            elif source == ResponseSource.CALCULATOR and "result" in data:
                reply = f"The answer is {data['result']}, Sir."
            elif source in [ResponseSource.GREETING, ResponseSource.PLANNER_CONVERSATIONAL] or intent in ["greeting", "conversational"]:
                reply = self._format_greeting(user_text)
            elif source in [ResponseSource.MEMORY, ResponseSource.PROFILE, ResponseSource.MEMORY_CONVERSATION]:
                reply = self._format_memory(data)
            elif source == ResponseSource.PLANNER:
                reply = self._format_planner(data)
            elif source == "action_manager":
                reply = self._format_action(data)
            else:
                reply = self._format_fallback(data)

            reply = ConversationStyle.apply(reply)
            reply = ConversationStyle.follow_up(reply, user_text)

            logger.info(
                "[Personality] Reply before post_process: %r",
                reply
            )
            return self._post_process(reply)

        except Exception as e:
            logger.exception("[PersonalityEngine ERROR] Failed to format response: %s", e)
            return "Operation completed, though a formatting error occurred, Sir."

    def _format_error(self, error_msg: str) -> str:
        error_msg = str(error_msg or "").strip()
        lowered = error_msg.lower()

        if "no profile" in lowered or "no relevant" in lowered:
            return "I couldn't find anything matching that request, Sir."

        if (
            "429" in lowered
            or "too many requests" in lowered
            or "rate limit" in lowered
            or "quota" in lowered
            or "all configured llm providers failed" in lowered
        ):
            return (
                "My AI services are temporarily rate-limited, Sir. "
                "Try again shortly."
            )

        if not error_msg:
            return (
                "I couldn't complete that request just now, Sir. "
                "Try again shortly."
            )

        logger.error(
            "[Personality] Internal operation error: %s",
            error_msg
        )

        return "I couldn't complete that operation, Sir."

    def _format_greeting(self, user_text: str) -> str:
        query = user_text.lower()
        if "how are you" in query:
            return "All systems operational and fully optimized, Sir. How may I assist you today?"
        elif "morning" in query:
            return "Good morning, Sir. All operational parameters are nominal."
        elif "evening" in query:
            return "Good evening, Sir. Ready for your instructions."

        responses = [
            "Greetings, Sir. ARIA operational and ready.",
            "Good to see you again, Sir.",
            "At your service, Sir.",
            "Systems online. How may I assist?",
            "Ready whenever you are, Sir."
        ]
        return random.choice(responses)

    def _format_memory(self, data: Any) -> str:
        data_dict = data if isinstance(data, dict) else {}

        # If the MemoryConversationManager already provided a natural response
        if "message" in data_dict:
            return str(data_dict["message"])

        memories = data_dict.get("memories", [])
        snippets = []
        for m in memories:
            if isinstance(m, dict):
                k = m.get("key") or m.get("field") or m.get("category") or "Detail"
                v = m.get("value") or m.get("content") or m.get("text") or m.get("summary")
                if v:
                    snippets.append(f"• {str(k).capitalize()}: {str(v)}")
                else:
                    snippets.append(f"• {str(m)}")
            else:
                snippets.append(f"• {str(m)}")

        if snippets:
            return "Here's what I found, Sir:\n\n" + "\n".join(snippets)

        return "No relevant records found, Sir."

    def _format_planner(self, data: Any) -> str:
        if not isinstance(data, dict):
            return "Task executed successfully, Sir."

        # NEW: if a Chat skill already generated a natural reply,
        # use it instead of exposing internal workflow details.
        chat = data.get("chat")

        if isinstance(chat, dict):
            if "response" in chat:
                return str(chat["response"])

            if "message" in chat:
                return str(chat["message"])

        # Otherwise look through every task
        for output in data.values():

            if not isinstance(output, dict):
                continue

            if "response" in output:
                return str(output["response"])

            if "message" in output:
                return str(output["message"])

        summaries = []

        for task_id, output in data.items():

            if isinstance(output, dict):
                status = output.get("status", "completed")
                summaries.append(f"{task_id}: {status}")
            else:
                summaries.append(f"{task_id}: {output}")

        return "Execution completed successfully, Sir. " + " | ".join(summaries)

    def _format_action(self, data: Any) -> str:
        if not isinstance(data, dict):
            return "Action completed successfully, Sir."

        action_name = data.get("action_name")
        result = data.get("result", {})

        if action_name == "notification_action":
            if isinstance(result, dict):
                message = result.get("message")

                if message:
                    return f"Notification dispatched: {message}, Sir."

            return "Notification dispatched successfully, Sir."

        # Generic formatting for future actions
        if isinstance(result, dict):
            if "message" in result:
                return str(result["message"])

            if "response" in result:
                return str(result["response"])

        return "Action completed successfully, Sir."

    def _format_fallback(self, data: Any) -> str:

        if isinstance(data, dict):

            # Highest priority
            if "response" in data:
                return str(data["response"])

            if "message" in data:
                return str(data["message"])

            if "result" in data:
                return str(data["result"])

            if "output" in data:
                return f"Python Output\n\n{data['output']}"

            # Last resort
            return "\n".join(str(v) for v in data.values() if v)

        if isinstance(data, str):
            return data

        return "Done."

    def _post_process(self, reply: str) -> str:
        """
        Final presentation cleanup for all ARIA responses.

        Keeps useful structure and code intact while removing
        unnecessary Markdown noise commonly produced by LLMs.
        """

        if reply is None:
            return "I couldn't generate a response, Sir."

        reply = str(reply).strip()

        if not reply:
            return "I couldn't generate a response, Sir."

        # -----------------------------------------------------
        # Protect fenced code blocks
        # -----------------------------------------------------

        code_blocks = []

        def protect_code(match):
            code_blocks.append(match.group(0))
            return f"__ARIA_CODE_BLOCK_{len(code_blocks) - 1}__"

        reply = re.sub(
            r"```[\s\S]*?```",
            protect_code,
            reply
        )

        # -----------------------------------------------------
        # Clean Markdown headings
        #
        # ## Python Basics -> Python Basics
        # ### Variables    -> Variables
        # -----------------------------------------------------

        reply = re.sub(
            r"(?m)^\s{0,3}#{1,6}\s+",
            "",
            reply
        )

        # -----------------------------------------------------
        # Remove Markdown bold/italic markers
        #
        # **Python** -> Python
        # __Python__ -> Python
        # -----------------------------------------------------

        reply = re.sub(
            r"\*\*(.*?)\*\*",
            r"\1",
            reply
        )

        reply = re.sub(
            r"__(.*?)__",
            r"\1",
            reply
        )

        # Simple italic Markdown
        reply = re.sub(
            r"(?<!\*)\*([^*\n]+)\*(?!\*)",
            r"\1",
            reply
        )

        # -----------------------------------------------------
        # Remove horizontal Markdown separators
        # -----------------------------------------------------

        reply = re.sub(
            r"(?m)^\s*(?:---+|\*\*\*+|___+)\s*$",
            "",
            reply
        )

        # -----------------------------------------------------
        # Normalize bullets
        #
        # - item
        # * item
        # + item
        #
        # becomes:
        #
        # • item
        # -----------------------------------------------------

        reply = re.sub(
            r"(?m)^\s*[-*+]\s+",
            "• ",
            reply
        )

        # -----------------------------------------------------
        # Clean excessive blank lines
        # -----------------------------------------------------

        reply = re.sub(
            r"\n[ \t]+\n",
            "\n\n",
            reply
        )

        reply = re.sub(
            r"\n{3,}",
            "\n\n",
            reply
        )

        # -----------------------------------------------------
        # Remove trailing spaces from each line
        # -----------------------------------------------------

        reply = "\n".join(
            line.rstrip()
            for line in reply.splitlines()
        )

        # -----------------------------------------------------
        # Restore protected code blocks
        # -----------------------------------------------------

        for index, block in enumerate(code_blocks):
            reply = reply.replace(
                f"__ARIA_CODE_BLOCK_{index}__",
                block
            )

        reply = reply.strip()

        # -----------------------------------------------------
        # Add punctuation only to simple one-line responses
        # -----------------------------------------------------

        if reply and "\n" not in reply:
            if reply[-1] not in ".!?":
                reply += "."

        return reply
