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

    async def apply_personality(
        self,
        session_id: str,
        user_text: str,
        response: SystemResponse,
    ) -> str:
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

            # Basic deterministic conversation styling first.
            reply = ConversationStyle.apply(reply)
            reply = ConversationStyle.follow_up(reply, user_text)

            # Universal ARIA personality pass.
            reply = await self._apply_aria_voice(
                user_text=user_text,
                reply=reply,
            )

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

        # ---------------------------------------------------------
        # 1. USER-FACING FINAL RESPONSE
        #
        # CognitiveCore already extracts the final task's natural
        # response into these top-level fields.
        # ---------------------------------------------------------

        response = data.get("response")

        if isinstance(response, str) and response.strip():
            return response.strip()

        message = data.get("message")

        if isinstance(message, str) and message.strip():
            return message.strip()

        # ---------------------------------------------------------
        # 2. LEGACY CHAT OUTPUT
        # ---------------------------------------------------------

        chat = data.get("chat")

        if isinstance(chat, dict):

            response = chat.get("response")

            if isinstance(response, str) and response.strip():
                return response.strip()

            message = chat.get("message")

            if isinstance(message, str) and message.strip():
                return message.strip()

        # ---------------------------------------------------------
        # 3. SEARCH THROUGH TASK OUTPUTS
        # ---------------------------------------------------------

        task_outputs = data.get(
            "task_outputs",
            {}
        )

        if isinstance(task_outputs, dict):

            # Reverse insertion order so the final task wins.
            for output in reversed(
                list(task_outputs.values())
            ):

                if not isinstance(output, dict):
                    continue

                for field in (
                    "response",
                    "content",
                    "message",
                    "answer",
                    "summary",
                ):

                    value = output.get(field)

                    if isinstance(value, str) and value.strip():
                        return value.strip()

        # ---------------------------------------------------------
        # 4. GENERIC NESTED OUTPUT FALLBACK
        # ---------------------------------------------------------

        for output in data.values():

            if not isinstance(output, dict):
                continue

            for field in (
                "response",
                "content",
                "message",
                "answer",
                "summary",
            ):

                value = output.get(field)

                if isinstance(value, str) and value.strip():
                    return value.strip()

        # ---------------------------------------------------------
        # 5. NOTHING USER-FACING WAS RETURNED
        # ---------------------------------------------------------

        return "Execution completed successfully, Sir."

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

        # File actions
        if action_name == "file_action":
            if isinstance(result, dict):

                # READ
                if "content" in result:
                    content = str(result["content"])

                    if content:
                        return content

                    return "The file is empty, Sir."

                # WRITE
                if result.get("status") == "written successfully":
                    return "File written successfully, Sir."

            return "File operation completed successfully, Sir."

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

    async def _apply_aria_voice(
        self,
        user_text: str,
        reply: str,
    ) -> str:
        """
        Universal ARIA personality pass.

        Rewrites presentation only.
        Facts, code, numbers, URLs, commands, filenames,
        warnings and technical details must remain unchanged.
        """

        reply = str(reply or "").strip()

        if not reply:
            return reply

        if self.llm_router is None:
            return reply

        # Avoid wasting an LLM call on very small deterministic replies.
        if len(reply) < 40:
            return reply

        messages = [
            {
                "role": "system",
                "content": (
                    "You are the final voice layer for ARIA. The input may be technically "
                    "correct but stylistically poor. Rewrite it substantially when necessary. "
                    "Preserve facts, numbers, warnings, URLs, code, and important details, "
                    "but completely change wording, structure, pacing, and explanation style "
                    "when that produces a more natural response.\n\n"

                    "ARIA is a sophisticated personal AI assistant: "
                    "calm, composed, precise, highly intelligent, "
                    "efficient, observant, and subtly personable.\n\n"

                    "STYLE:\n"
                    "- Speak naturally to the user, as an intelligent personal AI assistant.\n"
                    "- Prefer spoken, conversational English over academic or article-style prose.\n"
                    "- Never sound like a textbook, Wikipedia article, corporate report, or research paper unless the user requests that style.\n"
                    "- Avoid unnecessarily formal phrases such as 'redefines', 'represents a paradigm', 'the overarching theme', or 'transitioning from theoretical promise'.\n"
                    "- Do not show off technical knowledge. Use technical detail only when it improves the answer.\n"
                    "- Start with the clearest direct explanation, then add the important implication.\n"
                    "- Use contractions and natural transitions when appropriate.\n"
                    "- Vary sentence length so responses sound spoken rather than generated from a template.\n"
                    "- Keep the composed, precise, understated manner of a highly capable cinematic AI assistant.\n"
                    "- Do not imitate or quote any specific copyrighted character's dialogue or catchphrases.\n"
                    "- Address the user as 'Sir' occasionally when natural, but never mechanically in every response.\n"
                    "- Speak like an advanced personal AI briefing its operator.\n"
                    "- Be elegant and concise rather than verbose.\n"
                    "- Prefer natural conversational prose over report-like dumps.\n"
                    "- Lead with the useful answer, not generic introductions.\n"
                    "- For complex information, organize it cleanly.\n"
                    "- Use bullets only when they genuinely improve readability.\n"
                    "- Avoid excessive headings and corporate-report language.\n"
                    "- Be proactive when there is an obvious useful implication.\n"
                    "- A small amount of dry wit is acceptable when appropriate.\n"
                    "- Never become theatrical, cheesy, submissive, or exaggerated.\n"
                    "- Do not imitate or quote any fictional character.\n"
                    "- Maintain ARIA's own identity.\n"
                    "- Match technical depth to the user's question.\n"
                    "- Default to an intelligent conversational explanation, not a textbook lecture.\n"
                    "- Do not introduce equations, notation, implementation details, or jargon unless they are necessary or explicitly requested.\n"
                    "- Explain the big picture first; expand only when useful.\n"
                    "- For simple questions, prefer roughly 2-5 short paragraphs over long structured reports.\n"
                    "- Do not mechanically add headings such as 'Key principles', 'How it works', or 'Why it matters'.\n"
                    "- Sound like a capable personal assistant speaking directly to one person, not an encyclopedia article.\n"
                    "- When useful, end with one concise insight or implication rather than a generic offer to continue.\n\n"

                    "CRITICAL FIDELITY RULES:\n"
                    "- Change presentation and wording only.\n"
                    "- Do NOT add new factual claims.\n"
                    "- Do NOT remove important factual information.\n"
                    "- Do NOT change numbers, dates, prices, measurements, "
                    "statistics, names, URLs, filenames, commands, or code.\n"
                    "- Do NOT turn uncertainty into certainty.\n"
                    "- Preserve warnings, qualifications, citations, and sources.\n"
                    "- Never fabricate information to make the answer sound smarter.\n"
                    "- If the draft contains code, preserve the code exactly.\n"
                    "- If the draft contains instructions, preserve their meaning "
                    "and ordering exactly.\n\n"

                    "Avoid generic chatbot phrases such as:\n"
                    "- 'Here is a concise summary...'\n"
                    "- 'Based on the provided information...'\n"
                    "- 'As an AI...'\n"
                    "- 'I hope this helps.'\n\n"

                    "Return ONLY the rewritten response. "
                    "Do not explain what you changed."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"USER MESSAGE:\n{user_text}\n\n"
                    f"DRAFT RESPONSE:\n{reply}"
                ),
            },
        ]

        try:
            styled = await self.llm_router.chat(
                messages,
                temperature=0.45,
                max_tokens=1800,
            )

            styled = str(styled or "").strip()

            if styled:
                logger.info(
                    "[Personality] Universal ARIA voice applied."
                )
                return styled

        except Exception:
            # Personality must never break an otherwise valid response.
            logger.exception(
                "[Personality] Universal ARIA voice pass failed. "
                "Using original response."
            )

        return reply

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
