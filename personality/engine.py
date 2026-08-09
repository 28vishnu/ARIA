import logging
import random
import re
from typing import Dict, Any, Optional
from personality.response import SystemResponse
from personality.conversation_style import ConversationStyle
from personality.addressing import AddressingEngine

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


GLOBAL_ARIA_STYLE = """
You are ARIA's final communication layer.

Rewrite the supplied answer into the voice of a highly capable,
calm, polished personal AI assistant.

CORE PERSONALITY:
- Be courteous, composed, intelligent, concise, and attentive.
- Sound like you are speaking directly to one person.
- Maintain a subtle sophisticated assistant personality.
- Address the user naturally when appropriate.
- Never sound robotic, cold, academic, or like a generic chatbot.
- Never imitate or quote a specific fictional character.

SHORT ANSWERS:
- Even very short answers should retain ARIA's personality.
- Prefer concise forms.
- Do not unnecessarily expand a simple answer.

CONVERSATION:
- Don't sound like an encyclopedia.
- Answer naturally.
- Lead with the answer.
- Use short paragraphs.
- Don't repeat the question.
- Don't overuse bullet lists.
- Only offer a follow-up if it genuinely helps.
- If the user asks a simple question, don't write a mini article.

DOCUMENTS:
- Never dump raw document formatting unless the user explicitly asks for it.
- Remove Markdown artifacts such as **, ###, ---, and unnecessary tables.
- Summarize rather than reproduce.
- Preserve only information relevant to the user's request.
- If the user asks for a summary, do not reproduce the entire document.
- Use short sections or bullets only when they genuinely improve readability.
- Do not announce "Document processed successfully" unless that information
  is actually useful to the user.

UNCERTAINTY:
- Never state predictions, speculation, or uncertain future events as facts.
- Clearly distinguish known facts from estimates and predictions.
- If something cannot currently be known, say so naturally and briefly.
- Never manufacture certainty merely to provide a decisive answer.

RESPONSE LENGTH:
- Match the user's requested depth.
- Simple question -> simple answer.
- Summary -> actual summary.
- Detailed explanation -> detailed answer.
- Do not turn every response into a report.

IMPORTANT:
The supplied answer contains the underlying information.
You may substantially rewrite its wording and structure.
Preserve facts, numbers, warnings, URLs, code, and important details.
Do not invent new factual claims.
Return ONLY the final user-facing response.
"""


class PersonalityEngine:
    def __init__(self, llm_router=None):
        self.llm_router = llm_router
        self.addressing = AddressingEngine()

        self.conversation_style = {
            "tone": "assistant",
            "verbosity": "balanced",
            "humor": False,
        }

    def update_style(
        self,
        tone=None,
        verbosity=None,
        humor=None,
    ):

        if tone is not None:
            self.conversation_style["tone"] = tone

        if verbosity is not None:
            self.conversation_style["verbosity"] = verbosity

        if humor is not None:
            self.conversation_style["humor"] = humor

    def current_style(self):

        return self.conversation_style

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
                reply = (
                    f"The current time is {data['time']}, "
                    f"{self._address('normal')}."
                )
            elif source == ResponseSource.DATE and "date" in data:
                reply = (
                    f"Today is {data['date']}, "
                    f"{self._address('normal')}."
                )
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
                reply = (
                    f"The answer is {data['result']}, "
                    f"{self._address('technical')}."
                )
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

            # Apply conversation styling only to normal conversational replies.
            # Memory/profile responses are already structured and must remain intact.
            if source not in {
                ResponseSource.MEMORY,
                ResponseSource.PROFILE,
                ResponseSource.MEMORY_CONVERSATION,
            }:
                reply = ConversationStyle.apply(reply)
                reply = ConversationStyle.follow_up(reply, user_text)

            # ---------------------------------------------------------
            # FACTUAL / ROUTED RESPONSES MUST NOT BE REINTERPRETED
            # ---------------------------------------------------------

            protected_sources = {
                ResponseSource.MEMORY,
                ResponseSource.PROFILE,
                ResponseSource.MEMORY_CONVERSATION,
                ResponseSource.TIME,
                ResponseSource.DATE,
                ResponseSource.WEATHER,
                ResponseSource.SEARCH,
                ResponseSource.CALCULATOR,
                ResponseSource.PLANNER,
                ResponseSource.PLANNER_CONVERSATIONAL,
                ResponseSource.GREETING,
                "fast_router",
                "execution_router",
                "coding_engine",
                "agent",
                "action_manager",
            }

            if source in protected_sources:
                reply = self._apply_addressing(
                    reply,
                    context=self._addressing_context(source),
                )
                return self._post_process(reply)

            # ---------------------------------------------------------
            # UNIVERSAL ARIA PERSONALITY PASS
            # ---------------------------------------------------------

            reply = await self._apply_aria_voice(
                user_text=user_text,
                reply=reply,
            )

            logger.info(
                "[Personality] Reply before post_process: %r",
                reply,
            )

            reply = self._apply_addressing(
                reply,
                context="normal",
            )

            return self._post_process(reply)

        except Exception as e:
            logger.exception(
                "[PersonalityEngine ERROR] Failed to format response: %s",
                e,
            )

            try:
                title = self._address("warning")
            except Exception:
                title = "Sir"

            return (
                f"Operation completed, though a formatting error occurred, "
                f"{title}."
            )

    def _address(
        self,
        context: str = "normal",
        preferred: Optional[str] = None,
    ) -> str:
        """
        Return ARIA's current form of address.

        All user-facing titles must pass through AddressingEngine.
        The user's personal name is never used.
        """
        try:
            return self.addressing.get_address(
                context=context,
                preferred=preferred,
            )
        except Exception:
            logger.exception(
                "[Personality] Addressing engine failed."
            )
            return "Sir"

    def _format_error(self, error_msg: str) -> str:
        error_msg = str(error_msg or "").strip()
        lowered = error_msg.lower()

        title = self._address("warning")

        if "no profile" in lowered or "no relevant" in lowered:
            return (
                f"I couldn't find anything matching that request, "
                f"{title}."
            )

        if (
            "429" in lowered
            or "too many requests" in lowered
            or "rate limit" in lowered
            or "quota" in lowered
            or "all configured llm providers failed" in lowered
        ):
            return (
                f"My AI services are temporarily rate-limited, "
                f"{title}. Try again shortly."
            )

        if not error_msg:
            return (
                f"I couldn't complete that request just now, "
                f"{title}. Try again shortly."
            )

        logger.error(
            "[Personality] Internal operation error: %s",
            error_msg
        )

        return f"I couldn't complete that operation, {title}."

    def _format_greeting(self, user_text: str) -> str:
        query = user_text.lower()
        title = self._address("greeting")

        if "how are you" in query:
            return (
                f"All systems operational and fully optimized, "
                f"{title}. How may I assist you today?"
            )

        if "morning" in query:
            return (
                f"Good morning, {title}. "
                "All operational parameters are nominal."
            )

        if "evening" in query:
            return (
                f"Good evening, {title}. "
                "Ready for your instructions."
            )

        responses = [
            f"Greetings, {title}. ARIA operational and ready.",
            f"Good to see you again, {title}.",
            f"At your service, {title}.",
            f"Systems online. How may I assist, {self._address('technical')}?",
            f"Ready whenever you are, {title}.",
        ]

        return random.choice(responses)

    def _format_memory(self, data: Any) -> str:
        """
        Converts retrieved memory records into a natural ARIA response.

        MemoryEngine is responsible for retrieval.
        PersonalityEngine is responsible for presentation.
        """

        data_dict = data if isinstance(data, dict) else {}

        # If MemoryConversationManager already produced a natural response,
        # preserve it.
        message = data_dict.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

        memories = data_dict.get("memories", [])

        if not memories:
            return (
                f"I don't have any relevant memories about you yet, "
                f"{self._address('normal')}."
            )

        # ---------------------------------------------------------
        # Extract and normalize memories
        # ---------------------------------------------------------

        normalized = {}

        for memory in memories:
            if not isinstance(memory, dict):
                continue

            key = str(
                memory.get("key")
                or memory.get("field")
                or memory.get("category")
                or ""
            ).strip()

            value = (
                memory.get("value")
                or memory.get("content")
                or memory.get("text")
                or memory.get("summary")
            )

            if not key or value is None:
                continue

            value = str(value).strip()

            if not value:
                continue

            # Prevent duplicate semantic fields.
            normalized[key] = value

        if not normalized:
            return (
                f"I don't have any relevant memories about you yet, "
                f"{self._address('normal')}."
            )

        # ---------------------------------------------------------
        # Important memories first
        # ---------------------------------------------------------

        priority = [
            "name",
            "current_degree",
            "current_education_level",
            "future_education_plan",
            "planned_postgraduate_degree",
            "planned_postgraduate_location",
            "study_destination",
            "intended_degree",
            "backup_plan_country",
            "alternative_country",
            "favorite_color",
            "favorite_language",
            "favorite_superhero",
            "favorite_movie",
            "favorite_food",
            "favorite_car",
            "favorite_animal",
            "favorite_planet",
            "favorite_dinosaur",
            "project_name",
            "project_type",
            "project",
            "exam_preparation",
        ]

        ordered_keys = []

        for key in priority:
            if key in normalized and key not in ordered_keys:
                ordered_keys.append(key)

        # Add any remaining useful memories.
        for key in normalized:
            if key not in ordered_keys:
                ordered_keys.append(key)

        # ---------------------------------------------------------
        # Human-friendly labels
        # ---------------------------------------------------------

        labels = {
            "name": "Name",
            "current_degree": "Current degree",
            "current_education_level": "Current education",
            "future_education_plan": "Future education plan",
            "planned_postgraduate_degree": "Planned postgraduate degree",
            "planned_postgraduate_location": "Planned postgraduate location",
            "study_destination": "Study destination",
            "intended_degree": "Intended degree",
            "backup_plan_country": "Backup country",
            "alternative_country": "Alternative country",
            "favorite_color": "Favorite color",
            "favorite_colour": "Favorite color",
            "favorite_test_color": "Favorite test color",
            "favorite_language": "Favorite programming language",
            "favorite_superhero": "Favorite superhero",
            "favorite_movie": "Favorite movie",
            "favorite_food": "Favorite food",
            "favorite_car": "Favorite car",
            "favorite_animal": "Favorite animal",
            "favorite_planet": "Favorite planet",
            "favorite_dinosaur": "Favorite dinosaur",
            "project_name": "Project",
            "project_type": "Project type",
            "project": "Other project",
            "exam_preparation": "Exam preparation",
            "education_preference": "Education preference",
            "education_priority": "Education priority",
            "preferred_education_region": "Preferred education region",
            "preferred_watch_material": "Preferred watch material",
            "watch_budget": "Watch budget",
            "favorite_shopping_platform": "Favorite shopping platform",
            "intended_purchase": "Intended purchase",
            "preferred_name": "Preferred form of address",
        }

        # ---------------------------------------------------------
        # Ignore low-quality/internal memories
        # ---------------------------------------------------------

        ignored_keys = {
            "user_likes",
            "phase_3_test_animal",
            "favorite_test_color",
        }

        lines = []

        for key in ordered_keys:
            if key in ignored_keys:
                continue

            value = normalized[key]
            label = labels.get(
                key,
                key.replace("_", " ").capitalize()
            )

            lines.append(f"• {label}: {value}")

        if not lines:
            return (
                f"I don't have any relevant memories about you yet, "
                f"{self._address('normal')}."
            )

        return (
            f"Here's what I remember about you, "
            f"{self._address('normal')}:\n\n"
            + "\n".join(lines)
        )

    def _format_planner(self, data: Any) -> str:
        if not isinstance(data, dict):
            return (
                f"Task executed successfully, "
                f"{self._address('normal')}."
            )

        # ---------------------------------------------------------
        # 1. USER-FACING FINAL RESPONSE
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

        return (
            f"Task executed successfully, "
            f"{self._address('normal')}."
        )

    def _format_action(self, data: Any) -> str:
        if not isinstance(data, dict):
            return f"Action completed successfully, {self._address('normal')}."

        action_name = data.get("action_name")
        result = data.get("result", {})

        if action_name == "notification_action":
            if isinstance(result, dict):
                message = result.get("message")

                if message:
                    return f"Notification dispatched: {message}, {self._address('normal')}."

            return f"Notification dispatched successfully, {self._address('normal')}."

        # File actions
        if action_name == "file_action":
            if isinstance(result, dict):

                # READ
                if "content" in result:
                    content = str(result["content"])

                    if content:
                        return content

                    return f"The file is empty, {self._address('warning')}."

                # WRITE
                if result.get("status") == "written successfully":
                    return f"File written successfully, {self._address('normal')}."

            return f"File operation completed successfully, {self._address('normal')}."

        # Generic formatting for future actions
        if isinstance(result, dict):
            if "message" in result:
                return str(result["message"])

            if "response" in result:
                return str(result["response"])

        return f"Action completed successfully, {self._address('normal')}."

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

        messages = [
            {
                "role": "system",
                "content": GLOBAL_ARIA_STYLE,
            },
            {
                "role": "user",
                "content": (
                    f"USER MESSAGE:\n{user_text}\n\n"
                    f"DRAFT RESPONSE:\n{reply}\n\n"
                    "Rewrite the draft appropriately for the user's request."
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

    def _addressing_context(self, source: str) -> str:
        """
        Determine the appropriate addressing style from the response source.
        """

        if source in {
            ResponseSource.TIME,
            ResponseSource.DATE,
            ResponseSource.CALCULATOR,
        }:
            return "technical"

        if source in {
            ResponseSource.SEARCH,
            ResponseSource.WEATHER,
        }:
            return "normal"

        if source in {
            ResponseSource.MEMORY,
            ResponseSource.PROFILE,
            ResponseSource.MEMORY_CONVERSATION,
        }:
            return "conversation"

        if source in {
            ResponseSource.GREETING,
            ResponseSource.PLANNER_CONVERSATIONAL,
        }:
            return "greeting"

        if source in {
            ResponseSource.PLANNER,
            "action_manager",
            "agent",
            "execution_router",
        }:
            return "technical"

        return "normal"

    def _apply_addressing(
        self,
        reply: str,
        context: str = "normal",
    ) -> str:
        """
        Apply ARIA's centralized form of address.

        The addressing engine decides the title.
        Personal names are never used.
        """

        reply = str(reply or "").strip()

        if not reply:
            return reply

        title = self.addressing.get_address(context=context)

        # Remove an existing ARIA title only when it is being used
        # as a direct form of address.
        reply = re.sub(
            r",\s*(Sir|Master|Commander|Chief|Boss)(?=[.!?]|$)",
            "",
            reply,
            flags=re.IGNORECASE,
        )

        # For short conversational responses, place the title naturally.
        if "\n" not in reply:
            if reply.endswith((".", "!", "?")):
                reply = reply[:-1].rstrip()

            return f"{reply}, {title}."

        # For structured/multi-line responses, preserve the structure
        # and add the address only at the end.
        return f"{reply}\n\n{title}."

    def _post_process(self, reply: str) -> str:
        """
        Final presentation cleanup for all ARIA responses.

        Keeps useful structure and code intact while removing
        necessary Markdown noise commonly produced by LLMs.
        """

        if reply is None:
            return f"I couldn't generate a response, {self._address('warning')}."

        reply = str(reply).strip()

        if not reply:
            return f"I couldn't generate a response, {self._address('warning')}."

        # -----------------------------------------------------
        # Protect fenced code blocks
        # -----------------------------------------------------

        code_blocks = []

        def protect_code(match):
            code_blocks.append(match.group(0))
            return f"ARIA_CODE_BLOCK_PLACEHOLDER_{len(code_blocks) - 1}"

        reply = re.sub(
            r"```[\s\S]*?```",
            protect_code,
            reply
        )

        # -----------------------------------------------------
        # Clean Markdown headings
        # -----------------------------------------------------

        reply = re.sub(
            r"(?m)^\s{0,3}#{1,6}\s+",
            "",
            reply
        )

        # -----------------------------------------------------
        # Remove Markdown bold/italic markers
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
                f"ARIA_CODE_BLOCK_PLACEHOLDER_{index}",
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
