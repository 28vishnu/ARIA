import logging
import random
from typing import Dict, Any
from personality.response import SystemResponse

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
            else:
                reply = self._format_fallback(data)

            return self._post_process(reply)

        except Exception as e:
            logger.exception("[PersonalityEngine ERROR] Failed to format response: %s", e)
            return "Operation completed, though a formatting error occurred, Sir."

    def _format_error(self, error_msg: str) -> str:
        error_msg = error_msg or ""
        if "no profile" in error_msg.lower() or "no relevant" in error_msg.lower():
            return "I couldn't find any stored records matching that request, Sir."
        return f"I encountered a slight complication: {error_msg}"

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

    def _format_fallback(self, data: Any) -> str:
        if isinstance(data, dict):
            if "message" in data:
                return str(data["message"])
            if data:
                formatted_pairs = [f"{k}: {v}" for k, v in data.items() if v]
                if formatted_pairs:
                    return "Here is the information retrieved, Sir:\n" + "\n".join(formatted_pairs)

        if isinstance(data, str) and data.strip():
            return data

        return "Task executed successfully, Sir."

    def _post_process(self, reply: str) -> str:
        """Ensures consistent formatting and punctuation."""
        reply = reply.strip()
        if reply and reply[-1] not in ".!?":
            reply += "."
        return reply
