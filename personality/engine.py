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
ADDRESSING:
- Never call the user by their personal name unless explicitly requested.
- Do not randomly call the user Sir, Master, Chief, Boss, Commander, or similar titles.
- Never append a title to the end of a normal response.
- Speak naturally without a forced form of address.
- Only use a specific form of address when the user explicitly requests it.
NATURAL CONVERSATION:
- Behave like a long-term personal AI assistant, not a scripted chatbot.
- Match the user's tone and situation.
- Light humor is allowed when it naturally fits the conversation.
- Natural expressions such as "haha", "lol", "yeah", "fair enough", or "exactly" may occasionally be used when appropriate.
- Do not force jokes into serious, technical, educational, security, financial, medical, or important responses.
- Use emojis rarely and only when they genuinely fit the situation.
- Never add emojis just to decorate a response.
- Do not repeatedly use the same joke, expression, emoji, or conversational phrase.
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
- Preserve useful Markdown structure when it improves readability.
- Use **bold** for important terms, answers, keywords, and key points.
- Use headings for major sections when they improve readability.
- Use bullets for ordinary lists.
IMPORTANT POINTS / QUOTES:
- When the response contains an important conclusion, definition,
  warning, recommendation, exam point, or key takeaway, highlight it
  with a short Markdown blockquote beginning with `>`.
- Prefer 1–3 meaningful blockquotes in a detailed educational response.
- Do NOT quote every sentence.
- The blockquote must contain only the important point itself.
- Keep the quote concise and directly supported by the answer.
COMPARISON QUESTIONS:
- If the user asks for differences, comparison, compare, pros/cons,
  feature comparison, or "X vs Y", ALWAYS use a Markdown table.
- The table MUST use this exact standard structure:

| Feature | X | Y |
| :--- | :--- | :--- |
| Feature 1 | ... | ... |

- Do NOT use spaces/aligned plain-text columns.
- Do NOT replace the table with bullets unless the user explicitly
  asks for a non-table format.
- Keep table cells concise so they remain readable on mobile/Telegram.
- Do not put extremely long paragraphs inside table cells.
TELEGRAM READABILITY:
- The final response may be converted to Telegram HTML.
- Keep Markdown structures clean and valid.
- Use **bold** for important terms.
- Use `>` for important quoted/key statements.
- Keep comparison tables compact and structurally valid.
- Never create decorative formatting that can break Telegram rendering.
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
            "tone": "natural_assistant",
            "verbosity": "balanced",
            "humor": True,
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
                reply = f"The current time is {data['time']}."
            elif source == ResponseSource.DATE and "date" in data:
                reply = f"Today is {data['date']}."
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
                reply = f"The answer is {data['result']}."
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
                "memory",
                ResponseSource.PROFILE,
                ResponseSource.MEMORY_CONVERSATION,
                "conversation_memory",
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
            return "Operation completed, though a formatting error occurred."
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
        if "no profile" in lowered or "no relevant" in lowered:
            return "I couldn't find anything matching that request."
        if (
            "429" in lowered
            or "too many requests" in lowered
            or "rate limit" in lowered
            or "quota" in lowered
            or "all configured llm providers failed" in lowered
        ):
            return "My AI services are temporarily rate-limited. Try again shortly."
        if not error_msg:
            return "I couldn't complete that request just now. Try again shortly."
        logger.error(
            "[Personality] Internal operation error: %s",
            error_msg,
        )
        return "I couldn't complete that operation."
    def _format_greeting(self, user_text: str) -> str:
        query = user_text.lower().strip()
        if "how are you" in query:
            return "All systems are running smoothly. How can I help?"
        if "morning" in query:
            return "Good morning. What are we working on today?"
        if "evening" in query:
            return "Good evening. What can I help you with?"
        responses = [
            "Hello. How can I help?",
            "Hey. What are we working on?",
            "Hello. I'm ready.",
            "Good to see you. What's up?",
            "I'm here. What do you need?",
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
            return "I don't have any relevant memories about you yet."
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
            return "I don't have any relevant memories about you yet."
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
            return "I don't have any relevant memories about you yet."
        return (
            "Here's what I remember about you:\n\n"
            + "\n".join(lines)
        )
    def _format_planner(self, data: Any) -> str:
        if not isinstance(data, dict):
            return "Task executed successfully."
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
        return "Task executed successfully."
    def _format_action(self, data: Any) -> str:
        if not isinstance(data, dict):
            return "Action completed successfully."
        action_name = data.get("action_name")
        result = data.get("result", {})
        if action_name == "notification_action":
            if isinstance(result, dict):
                message = result.get("message")
                if message:
                    return f"Notification dispatched: {message}."
            return "Notification dispatched successfully."
        # File actions
        if action_name == "file_action":
            if isinstance(result, dict):
                # READ
                if "content" in result:
                    content = str(result["content"])
                    if content:
                        return content
                    return "The file is empty."
                # WRITE
                if result.get("status") == "written successfully":
                    return "File written successfully."
            return "File operation completed successfully."
        # Generic formatting for future actions
        if isinstance(result, dict):
            if "message" in result:
                return str(result["message"])
            if "response" in result:
                return str(result["response"])
        return "Action completed successfully."
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
                    "Rewrite the draft appropriately for the user's request.\n\n"
                    "FORMATTING REQUIREMENTS:\n"
                    "- If this is a comparison/difference question, preserve or create "
                    "a valid Markdown comparison table.\n"
                    "- If the answer contains important conclusions, definitions, "
                    "warnings, recommendations, or key takeaways, use 1–3 concise "
                    "Markdown blockquotes beginning with `>`.\n"
                    "- Preserve **bold**, Markdown tables, `>` blockquotes, and fenced "
                    "code blocks.\n"
                    "- Do not convert a comparison table into plain-text columns.\n"
                    "- Do not add formatting that is not useful.\n"
                    "- Keep the response natural and readable on Telegram."
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
        Apply addressing only when it is genuinely appropriate.
        ARIA must NOT randomly append titles such as:
        Sir, Master, Chief, Boss, Commander.
        Personal names are never used automatically.
        """
        reply = str(reply or "").strip()
        if not reply:
            return reply
        # Normal responses should contain NO forced title.
        #
        # Addressing is intentionally disabled here.
        # Specific future situations can explicitly request
        # an address when it is actually useful.
        return reply
    def _post_process(self, reply: str) -> str:
        """
        Final presentation cleanup for ARIA responses.
        Preserves useful Markdown formatting while normalizing it
        for Telegram presentation.
        """
        if reply is None:
            return "I couldn't generate a response."
        reply = str(reply).strip()
        if not reply:
            return "I couldn't generate a response."
        # ---------------------------------------------------------
        # PRESERVE TELEGRAM MARKDOWN STRUCTURES
        # ---------------------------------------------------------
        # ARIA may generate:
        #   > important point
        #   | Feature | TCP | UDP |
        #
        # These structures must survive the final cleanup stage.
        # Normalize blockquotes without removing them.
        reply = re.sub(
            r"(?m)^\s*>\s?",
            "> ",
            reply,
        )
        # Preserve Markdown table separator spacing.
        reply = re.sub(
            r"(?m)^\s*\|(.+)\|\s*$",
            lambda m: "|" + m.group(1).strip() + "|",
            reply,
        )
        # ---------------------------------------------------------
        # Protect fenced code blocks
        # ---------------------------------------------------------
        code_blocks = []
        def protect_code(match):
            code_blocks.append(match.group(0))
            return f"ARIA_CODE_BLOCK_PLACEHOLDER_{len(code_blocks) - 1}"
        reply = re.sub(
            r"```[\s\S]*?```",
            protect_code,
            reply,
        )
        # ---------------------------------------------------------
        # Preserve useful headings
        #
        # Telegram can display these naturally after the later
        # Telegram formatting layer is applied.
        # ---------------------------------------------------------
        reply = re.sub(
            r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$",
            r"\1",
            reply,
        )
        # ---------------------------------------------------------
        # Preserve bold / important formatting
        # ---------------------------------------------------------
        # Keep **bold** exactly as generated.
        # Do NOT remove it.
        # Convert Markdown italic to plain text for now.
        # This avoids accidental formatting conflicts.
        reply = re.sub(
            r"(?<!\*)\*([^*\n]+)\*(?!\*)",
            r"\1",
            reply,
        )
        reply = re.sub(
            r"(?<!_)_([^_\n]+)_(?!_)",
            r"\1",
            reply,
        )
        # ---------------------------------------------------------
        # Remove unnecessary horizontal separators
        # ---------------------------------------------------------
        reply = re.sub(
            r"(?m)^\s*(?:---+|___+)\s*$",
            "",
            reply,
        )
        # ---------------------------------------------------------
        # Normalize ordinary bullets only
        # ---------------------------------------------------------
        reply = re.sub(
            r"(?m)^(?!\s*[>|])\s*[-*+]\s+",
            "• ",
            reply,
        )
        # ---------------------------------------------------------
        # Clean excessive blank lines
        # ---------------------------------------------------------
        reply = re.sub(
            r"\n[ \t]+\n",
            "\n\n",
            reply,
        )
        reply = re.sub(
            r"\n{3,}",
            "\n\n",
            reply,
        )
        # ---------------------------------------------------------
        # Remove trailing spaces
        # ---------------------------------------------------------
        reply = "\n".join(
            line.rstrip()
            for line in reply.splitlines()
        )
        # ---------------------------------------------------------
        # Restore code blocks
        # ---------------------------------------------------------
        for index, block in enumerate(code_blocks):
            reply = reply.replace(
                f"ARIA_CODE_BLOCK_PLACEHOLDER_{index}",
                block,
            )
        reply = reply.strip()
        # ---------------------------------------------------------
        # Simple one-line punctuation
        # ---------------------------------------------------------
        if reply and "\n" not in reply:
            if reply[-1] not in ".!?":
                reply += "."
        return reply