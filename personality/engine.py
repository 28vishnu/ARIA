import logging
import random
import re
from typing import Dict, Any

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

    # ---------------------------------------------------------
    # LOCAL KNOWLEDGE
    # ---------------------------------------------------------

    KNOWLEDGE = "knowledge"
    LOCAL_KNOWLEDGE = "local_knowledge"
    KNOWLEDGE_MANAGER = "knowledge_manager"

    # ---------------------------------------------------------
    # PHASE 1 AUTHORITATIVE ENGINEERING
    # ---------------------------------------------------------

    PHASE1_AUTHORITATIVE_ENGINEERING = (
        "phase1_authoritative_engineering"
    )


GLOBAL_ARIA_STYLE = """
You are ARIA's final communication layer.

Rewrite the supplied answer into the voice of a highly capable,
calm, polished personal AI assistant.

CORE PERSONALITY:
- Be courteous, composed, intelligent, concise, and attentive.
- Sound like you are speaking directly to one person.
- Maintain a subtle sophisticated assistant personality.
- Address the user as "Sir" naturally when appropriate.
- Do not use "Sir" mechanically in every sentence.
- Never sound robotic, cold, academic, or like a generic chatbot.
- Never imitate or quote a specific fictional character.

SHORT ANSWERS:
- Even very short answers should retain ARIA's personality.
- Prefer concise forms such as:
  "Tokyo, Sir."
  "That comes to 143.65, Sir."
  "Certainly, Sir. Here's the key point..."
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

    # =========================================================
    # STYLE
    # =========================================================

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

    # =========================================================
    # LOCAL KNOWLEDGE
    # =========================================================

    @staticmethod
    def _normalize_value(value: Any) -> str:
        return str(value or "").strip().lower()

    @classmethod
    def _local_sources(cls):
        """
        All source identifiers that mean the answer is already owned
        by the local knowledge system.

        IMPORTANT:
        Keep this centralized so every local-knowledge decision uses
        exactly the same source vocabulary.
        """

        return {
            ResponseSource.KNOWLEDGE,
            ResponseSource.LOCAL_KNOWLEDGE,
            ResponseSource.KNOWLEDGE_MANAGER,

            "knowledge",
            "local_knowledge",
            "knowledge_manager",
            "knowledge_database",

            "local_answer",
            "local_knowledge_answer",
            "knowledge_result",

            "local_foundational_knowledge",
            "foundational_knowledge",

            "knowledge_engine",
            "local_knowledge_engine",

            "knowledge_manager_answer",
            "knowledge_database_answer",

            "local_knowledge_database",
            "local_knowledge_manager",
        }

    @classmethod
    def _value_is_local_source(
        cls,
        value: Any,
    ) -> bool:

        normalized = cls._normalize_value(value)

        return normalized in cls._local_sources()

    @classmethod
    def _object_contains_local_metadata(
        cls,
        obj: Any,
        depth: int = 0,
    ) -> bool:
        """
        Recursively inspect an object for explicit local-knowledge
        ownership metadata.

        This function deliberately does NOT treat an ordinary
        "answer" or "response" field as evidence of local knowledge.

        Only explicit routing/ownership metadata can activate the
        local-knowledge gate.
        """

        if obj is None:
            return False

        if depth > 5:
            return False

        if isinstance(obj, str):

            return cls._value_is_local_source(obj)

        local_boolean_keys = {
            "local_knowledge",
            "is_local_knowledge",
            "local_answer",
            "knowledge_manager",
            "knowledge_database",
        }

        if isinstance(obj, dict):

            source_keys = {
                "source",
                "response_source",
                "answer_source",
                "knowledge_source",
                "owner",
                "answer_owner",
                "execution_owner",
                "knowledge_owner",
                "route_owner",
            }

            for key in source_keys:

                if key not in obj:
                    continue

                if cls._value_is_local_source(obj.get(key)):
                    return True

            for key in local_boolean_keys:

                if obj.get(key) is True:
                    return True

            if obj.get("local_answer") is True:
                return True

            if (
                str(
                    obj.get("answer_owner") or ""
                ).strip().lower()
                == "knowledge_manager"
            ):
                return True

            if obj.get("external_llm_synthesis") is False:

                knowledge_markers = {
                    "knowledge",
                    "knowledge_result",
                    "knowledge_source",
                    "local_knowledge",
                    "knowledge_manager",
                    "knowledge_database",
                    "answer_owner",
                    "source",
                }

                if any(
                    key in obj
                    for key in knowledge_markers
                ):
                    return True

            nested_keys = (
                "metadata",
                "meta",
                "routing",
                "routing_metadata",
                "knowledge",
                "knowledge_result",
                "result",
                "answer_metadata",
                "context",
                "response",
                "data",
            )

            for key in nested_keys:

                if key not in obj:
                    continue

                nested_value = obj.get(key)

                if cls._object_contains_local_metadata(
                    nested_value,
                    depth + 1,
                ):
                    return True

            return False

        if isinstance(obj, (list, tuple)):

            for item in obj:

                if cls._object_contains_local_metadata(
                    item,
                    depth + 1,
                ):
                    return True

            return False

        attributes = (
            "source",
            "response_source",
            "answer_source",
            "knowledge_source",
            "owner",
            "answer_owner",
            "execution_owner",
            "knowledge_owner",
            "route_owner",

            "local_knowledge",
            "knowledge_manager",
            "knowledge_database",
            "is_local_knowledge",
            "local_answer",

            "external_llm_synthesis",

            "metadata",
            "meta",
            "routing",
            "routing_metadata",

            "knowledge",
            "knowledge_result",
            "answer_metadata",

            "context",
            "data",
        )

        for attribute in attributes:

            try:

                if not hasattr(obj, attribute):
                    continue

                value = getattr(
                    obj,
                    attribute,
                )

            except Exception:

                continue

            if attribute in local_boolean_keys:

                if value is True:
                    return True

                continue

            if attribute == "external_llm_synthesis":

                if value is False:
                    return True

                continue

            if attribute in {
                "source",
                "response_source",
                "answer_source",
                "knowledge_source",
                "owner",
                "answer_owner",
                "execution_owner",
                "knowledge_owner",
                "route_owner",
            }:

                if cls._value_is_local_source(value):
                    return True

                if (
                    attribute == "answer_owner"
                    and cls._normalize_value(value)
                    == "knowledge_manager"
                ):
                    return True

                continue

            if cls._object_contains_local_metadata(
                value,
                depth + 1,
            ):
                return True

        return False

    @classmethod
    def _is_local_knowledge_response(
        cls,
        source: str,
        data: Any,
        response: Any = None,
    ) -> bool:

        if cls._value_is_local_source(source):
            return True

        if cls._object_contains_local_metadata(data):
            return True

        if response is not None:

            if cls._object_contains_local_metadata(response):
                return True

        return False

    @classmethod
    def _local_knowledge_answer(
        cls,
        data: Any,
        response: Any,
    ) -> str:

        reply = cls._extract_response(data)

        if reply:
            return reply

        reply = cls._extract_response(response)

        if reply:
            return reply

        if isinstance(data, dict):

            for key in (
                "knowledge",
                "knowledge_result",
                "local_answer",
            ):

                nested = data.get(key)

                reply = cls._extract_response(nested)

                if reply:
                    return reply

        return ""

    # =========================================================
    # PHASE 1 AUTHORITATIVE ENGINEERING
    # =========================================================

    @staticmethod
    def _engineering_value(
        value: Any,
        default: Any = None,
    ) -> Any:
        """
        Safely return a value from an authoritative engineering
        diagnostic structure.
        """

        if value is None:
            return default

        return value

    @classmethod
    def _format_phase1_engineering(
        cls,
        data: Any,
    ) -> str:
        """
        Deterministically format the authoritative Phase 1 engineering
        response.

        IMPORTANT:
        This method must never call the LLM.

        The engineering runtime owns the facts. PersonalityEngine only
        presents those facts to the user without semantic rewriting.
        """

        if not isinstance(data, dict):

            return (
                "Phase 1 autonomous-engineering inspection "
                "completed, Sir.\n\n"
                f"Result: {data}"
            )

        engineering_result = data.get(
            "engineering_result"
        )

        if not isinstance(
            engineering_result,
            dict,
        ):

            engineering_result = data

        report = engineering_result

        # ---------------------------------------------------------
        # Top-level status
        # ---------------------------------------------------------

        ready = report.get(
            "ready",
            None,
        )

        status = report.get(
            "status",
            None,
        )

        message = report.get(
            "message",
            None,
        )

        if ready is True:

            heading = (
                "Phase 1 autonomous-engineering lifecycle "
                "is READY for execution, Sir."
            )

        elif ready is False:

            heading = (
                "Phase 1 autonomous-engineering lifecycle "
                "is NOT READY for execution, Sir."
            )

        elif status:

            heading = (
                f"Phase 1 autonomous-engineering status: "
                f"{status}, Sir."
            )

        else:

            heading = (
                "Phase 1 autonomous-engineering inspection "
                "completed, Sir."
            )

        lines = [
            heading,
        ]

        # ---------------------------------------------------------
        # Gateway information
        # ---------------------------------------------------------

        gateway = report.get(
            "gateway"
        )

        if gateway:

            lines.append(
                f"Gateway: {gateway}"
            )

        read_only = report.get(
            "read_only"
        )

        if read_only is not None:

            lines.append(
                f"Read-only inspection: "
                f"{'YES' if read_only else 'NO'}"
            )

        execution_started = report.get(
            "execution_started"
        )

        if execution_started is not None:

            lines.append(
                f"Execution started: "
                f"{'YES' if execution_started else 'NO'}"
            )

        # ---------------------------------------------------------
        # Overall checks
        # ---------------------------------------------------------

        checks = report.get(
            "checks"
        )

        if isinstance(checks, dict):

            lines.append("")
            lines.append("Readiness checks:")

            for key, value in checks.items():

                label = str(
                    key
                ).replace(
                    "_",
                    " ",
                ).capitalize()

                if isinstance(
                    value,
                    bool,
                ):

                    result = (
                        "PASS"
                        if value
                        else "FAIL"
                    )

                else:

                    result = str(value)

                lines.append(
                    f"• {label}: {result}"
                )

        # ---------------------------------------------------------
        # Repository diagnostic
        # ---------------------------------------------------------

        # Read-only RepositoryIntelligence results may arrive either as
        # the canonical `repository` field or as the legacy/nested `result`
        # field. Normalize both forms so a successful inspection cannot be
        # rendered as an empty generic completion message.
        repository = report.get(
            "repository"
        )
        if not isinstance(repository, dict):
            nested_result = report.get("result")
            if isinstance(nested_result, dict) and (
                "repository_root" in nested_result
                or "relevant_files" in nested_result
                or "source_evidence" in nested_result
                or "inventory" in nested_result
            ):
                repository = nested_result

        if isinstance(repository, dict):

            lines.append("")
            lines.append(
                "Repository validation:"
            )

            repository_success = repository.get(
                "success"
            )

            if repository_success is not None:

                lines.append(
                    "• Status: "
                    + (
                        "PASS"
                        if repository_success
                        else "FAIL"
                    )
                )

            repository_status = repository.get(
                "status"
            )

            if repository_status:

                lines.append(
                    f"• Repository status: "
                    f"{repository_status}"
                )

            repository_checks = repository.get(
                "checks"
            )

            if isinstance(
                repository_checks,
                dict,
            ):

                for key, value in repository_checks.items():

                    label = str(
                        key
                    ).replace(
                        "_",
                        " ",
                    ).capitalize()

                    if isinstance(
                        value,
                        bool,
                    ):

                        result = (
                            "PASS"
                            if value
                            else "FAIL"
                        )

                    else:

                        result = str(value)

                    lines.append(
                        f"• {label}: {result}"
                    )

            repository_errors = repository.get(
                "errors"
            )

            if isinstance(
                repository_errors,
                (list, tuple),
            ):

                for error in repository_errors:

                    lines.append(
                        f"• Error: {error}"
                    )

            elif repository_errors:

                lines.append(
                    f"• Error: {repository_errors}"
                )

            relevant_files = repository.get("relevant_files")
            if isinstance(relevant_files, (list, tuple)) and relevant_files:
                lines.append("• Relevant files: " + ", ".join(map(str, relevant_files[:20])))

            source_evidence = repository.get("source_evidence")
            if isinstance(source_evidence, (list, tuple)) and source_evidence:
                lines.append("• Source evidence items: " + str(len(source_evidence)))

            repository_warnings = repository.get(
                "warnings"
            )

            if isinstance(
                repository_warnings,
                (list, tuple),
            ):

                for warning in repository_warnings:

                    lines.append(
                        f"• Warning: {warning}"
                    )

            elif repository_warnings:

                lines.append(
                    f"• Warning: {repository_warnings}"
                )

        # ---------------------------------------------------------
        # Runtime diagnostic
        # ---------------------------------------------------------

        runtime = report.get(
            "runtime"
        )

        if isinstance(runtime, dict):

            lines.append("")
            lines.append(
                "Authoritative runtime:"
            )

            runtime_success = runtime.get(
                "success"
            )

            if runtime_success is not None:

                lines.append(
                    "• Status: "
                    + (
                        "PASS"
                        if runtime_success
                        else "FAIL"
                    )
                )

            runtime_status = runtime.get(
                "status"
            )

            if runtime_status:

                lines.append(
                    f"• Runtime status: "
                    f"{runtime_status}"
                )

            runtime_health = runtime.get(
                "health"
            )

            if isinstance(
                runtime_health,
                dict,
            ):

                healthy = runtime_health.get(
                    "healthy"
                )

                if healthy is not None:

                    lines.append(
                        "• Runtime health: "
                        + (
                            "HEALTHY"
                            if healthy
                            else "UNHEALTHY"
                        )
                    )

            runtime_checks = runtime.get(
                "checks"
            )

            if isinstance(
                runtime_checks,
                dict,
            ):

                for key, value in runtime_checks.items():

                    label = str(
                        key
                    ).replace(
                        "_",
                        " ",
                    ).capitalize()

                    if isinstance(
                        value,
                        bool,
                    ):

                        result = (
                            "PASS"
                            if value
                            else "FAIL"
                        )

                    else:

                        result = str(value)

                    lines.append(
                        f"• {label}: {result}"
                    )

            runtime_errors = runtime.get(
                "errors"
            )

            if isinstance(
                runtime_errors,
                (list, tuple),
            ):

                for error in runtime_errors:

                    lines.append(
                        f"• Error: {error}"
                    )

            elif runtime_errors:

                lines.append(
                    f"• Error: {runtime_errors}"
                )

            runtime_warnings = runtime.get(
                "warnings"
            )

            if isinstance(
                runtime_warnings,
                (list, tuple),
            ):

                for warning in runtime_warnings:

                    lines.append(
                        f"• Warning: {warning}"
                    )

            elif runtime_warnings:

                lines.append(
                    f"• Warning: {runtime_warnings}"
                )

        # ---------------------------------------------------------
        # Safety diagnostic
        # ---------------------------------------------------------

        safety = report.get(
            "safety"
        )

        if isinstance(safety, dict):

            lines.append("")
            lines.append(
                "Safety boundaries:"
            )

            safety_success = safety.get(
                "success"
            )

            if safety_success is not None:

                lines.append(
                    "• Status: "
                    + (
                        "PASS"
                        if safety_success
                        else "FAIL"
                    )
                )

            for key, value in safety.items():

                if key in {
                    "success",
                    "status",
                    "message",
                    "errors",
                    "warnings",
                }:
                    continue

                label = str(
                    key
                ).replace(
                    "_",
                    " ",
                ).capitalize()

                if isinstance(
                    value,
                    bool,
                ):

                    result = (
                        "YES"
                        if value
                        else "NO"
                    )

                else:

                    result = str(value)

                lines.append(
                    f"• {label}: {result}"
                )

            safety_errors = safety.get(
                "errors"
            )

            if isinstance(
                safety_errors,
                (list, tuple),
            ):

                for error in safety_errors:

                    lines.append(
                        f"• Error: {error}"
                    )

            elif safety_errors:

                lines.append(
                    f"• Error: {safety_errors}"
                )

            safety_warnings = safety.get(
                "warnings"
            )

            if isinstance(
                safety_warnings,
                (list, tuple),
            ):

                for warning in safety_warnings:

                    lines.append(
                        f"• Warning: {warning}"
                    )

            elif safety_warnings:

                lines.append(
                    f"• Warning: {safety_warnings}"
                )

        # ---------------------------------------------------------
        # Preserve gateway message as a concise summary.
        # ---------------------------------------------------------

        if message:

            lines.append("")
            lines.append(
                f"Gateway message: {message}"
            )

        # ---------------------------------------------------------
        # If no structured fields were present, preserve the
        # original response rather than inventing diagnostics.
        # ---------------------------------------------------------

        if len(lines) == 1 and message:

            return (
                f"{heading}\n\n"
                f"{message}"
            )

        return "\n".join(lines)

    # =========================================================
    # MAIN PERSONALITY PIPELINE
    # =========================================================

    async def apply_personality(
        self,
        session_id: str,
        user_text: str,
        response: SystemResponse,
    ) -> str:

        try:

            if not response.success:

                return self._format_error(
                    response.error
                )

            data = response.data or {}

            source = response.source

            intent = (
                data.get("intent")
                if isinstance(
                    data,
                    dict,
                )
                else None
            )

            # =====================================================
            # ABSOLUTE LOCAL KNOWLEDGE HARD GATE
            # =====================================================

            is_local_knowledge = (
                self._is_local_knowledge_response(
                    source=source,
                    data=data,
                    response=response,
                )
            )

            if is_local_knowledge:

                logger.info(
                    "[Personality] LOCAL KNOWLEDGE HARD GATE "
                    "ACTIVE | source=%r | "
                    "KnowledgeManager owns response | "
                    "external LLM skipped",
                    source,
                )

                reply = self._local_knowledge_answer(
                    data=data,
                    response=response,
                )

                if not reply:

                    reply = self._format_fallback(
                        data
                    )

                logger.info(
                    "[Personality] LOCAL KNOWLEDGE RETURN "
                    "DIRECT | no LLMRouter call"
                )

                return self._post_process(
                    reply
                )

            # =====================================================
            # PHASE 1 AUTHORITATIVE ENGINEERING HARD GATE
            # =====================================================
            #
            # This response contains operational engineering facts.
            #
            # NEVER send it through:
            #   - ConversationStyle
            #   - follow-up generation
            #   - _apply_aria_voice
            #   - LLMRouter
            #   - external providers
            #
            # The readiness gateway/orchestrator is authoritative.
            # PersonalityEngine only renders its structured result.
            # =====================================================

            if (
                source
                == ResponseSource.PHASE1_AUTHORITATIVE_ENGINEERING
            ):

                logger.info(
                    "[Personality] PHASE 1 ENGINEERING "
                    "HARD GATE ACTIVE | "
                    "deterministic engineering report | "
                    "external LLM skipped"
                )

                reply = self._format_phase1_engineering(
                    data
                )

                logger.info(
                    "[Personality] PHASE 1 ENGINEERING "
                    "RETURN DIRECT | no LLMRouter call"
                )

                return self._post_process(
                    reply
                )

            # =====================================================
            # PRIVATE FORMATTERS
            # =====================================================

            if (
                source == ResponseSource.TIME
                and isinstance(data, dict)
                and "time" in data
            ):

                reply = (
                    f"The current time is "
                    f"{data['time']}, Sir."
                )

            elif (
                source == ResponseSource.DATE
                and isinstance(data, dict)
                and "date" in data
            ):

                reply = (
                    f"Today is "
                    f"{data['date']}, Sir."
                )

            elif (
                source in [
                    ResponseSource.WEATHER,
                    ResponseSource.SEARCH,
                ]
                and isinstance(data, dict)
                and "message" in data
            ):

                reply = str(
                    data["message"]
                )

            elif (
                source == ResponseSource.CHAT
                and isinstance(data, dict)
                and "response" in data
            ):

                reply = str(
                    data["response"]
                )

            elif source == "agent":

                if (
                    isinstance(data, dict)
                    and "response" in data
                ):

                    reply = str(
                        data["response"]
                    )

                elif (
                    isinstance(data, dict)
                    and "message" in data
                ):

                    reply = str(
                        data["message"]
                    )

                else:

                    reply = self._format_fallback(
                        data
                    )

            elif (
                source == ResponseSource.CALCULATOR
                and isinstance(data, dict)
                and "result" in data
            ):

                reply = (
                    f"The answer is "
                    f"{data['result']}, Sir."
                )

            elif (
                source in [
                    ResponseSource.GREETING,
                    ResponseSource.PLANNER_CONVERSATIONAL,
                ]
                or intent in [
                    "greeting",
                    "conversational",
                ]
            ):

                reply = self._format_greeting(
                    user_text
                )

            elif source in [
                ResponseSource.MEMORY,
                ResponseSource.PROFILE,
                ResponseSource.MEMORY_CONVERSATION,
                "memory_profile",
            ]:

                reply = self._format_memory(
                    data
                )

            elif source == "conversation":

                reply = str(
                    data.get("response")
                    or data.get("message")
                    or self._format_fallback(data)
                )

            elif source in [
                "capability",
                "llm_unavailable",
            ]:

                reply = str(
                    data.get("response")
                    or data.get("message")
                    or self._format_fallback(data)
                )

            elif source == ResponseSource.PLANNER:

                reply = self._format_planner(
                    data
                )

            elif source == "action_manager":

                reply = self._format_action(
                    data
                )

            else:

                reply = self._format_fallback(
                    data
                )

            # =====================================================
            # CONVERSATION STYLE
            # =====================================================

            if source not in {
                ResponseSource.MEMORY,
                ResponseSource.PROFILE,
                ResponseSource.MEMORY_CONVERSATION,
                "memory_profile",

                "conversation",
                "capability",
                "llm_unavailable",

                ResponseSource.KNOWLEDGE,
                ResponseSource.LOCAL_KNOWLEDGE,
                ResponseSource.KNOWLEDGE_MANAGER,

                "knowledge_database",
                "local_foundational_knowledge",

                ResponseSource.PHASE1_AUTHORITATIVE_ENGINEERING,
            }:

                reply = ConversationStyle.apply(
                    reply
                )

                reply = ConversationStyle.follow_up(
                    reply,
                    user_text,
                )

            # =====================================================
            # PROTECTED SOURCES
            # =====================================================

            protected_sources = {

                ResponseSource.MEMORY,
                ResponseSource.PROFILE,
                ResponseSource.MEMORY_CONVERSATION,
                "memory_profile",

                "conversation",
                "capability",
                "llm_unavailable",

                ResponseSource.TIME,
                ResponseSource.DATE,
                ResponseSource.WEATHER,
                ResponseSource.SEARCH,
                ResponseSource.CALCULATOR,

                ResponseSource.PLANNER,
                ResponseSource.PLANNER_CONVERSATIONAL,
                ResponseSource.GREETING,

                ResponseSource.KNOWLEDGE,
                ResponseSource.LOCAL_KNOWLEDGE,
                ResponseSource.KNOWLEDGE_MANAGER,

                "knowledge_database",
                "local_foundational_knowledge",

                "fast_router",
                "execution_router",
                "coding_engine",
                "agent",
                "action_manager",

                ResponseSource.PHASE1_AUTHORITATIVE_ENGINEERING,
            }

            if source in protected_sources:

                return self._post_process(
                    reply
                )

            # =====================================================
            # UNIVERSAL ARIA PERSONALITY PASS
            # =====================================================

            reply = await self._apply_aria_voice(
                user_text=user_text,
                reply=reply,
            )

            logger.info(
                "[Personality] Reply before post_process: %r",
                reply,
            )

            return self._post_process(
                reply
            )

        except Exception as e:

            logger.exception(
                "[PersonalityEngine ERROR] "
                "Failed to format response: %s",
                e,
            )

            return (
                "Operation completed, "
                "though a formatting error occurred, Sir."
            )

    # =========================================================
    # RESPONSE EXTRACTION
    # =========================================================

    @staticmethod
    def _extract_response(
        data: Any,
    ) -> str:

        if isinstance(
            data,
            str,
        ):

            return data.strip()

        if isinstance(
            data,
            dict,
        ):

            for key in (
                "response",
                "answer",
                "message",
                "content",
                "text",
                "result",
            ):

                value = data.get(
                    key
                )

                if (
                    isinstance(
                        value,
                        str,
                    )
                    and value.strip()
                ):

                    return value.strip()

            for key in (
                "local_answer",
                "knowledge_result",
                "knowledge",
            ):

                nested = data.get(key)

                if nested is not None:

                    result = PersonalityEngine._extract_response(
                        nested
                    )

                    if result:
                        return result

            return ""

        for key in (
            "response",
            "answer",
            "message",
            "content",
            "text",
            "result",
        ):

            try:

                value = getattr(
                    data,
                    key,
                    None,
                )

            except Exception:

                continue

            if (
                isinstance(
                    value,
                    str,
                )
                and value.strip()
            ):

                return value.strip()

        try:

            nested_data = getattr(
                data,
                "data",
                None
            )

        except Exception:

            nested_data = None

        if nested_data is not None:

            return PersonalityEngine._extract_response(
                nested_data
            )

        return ""

    # =========================================================
    # ERROR FORMAT
    # =========================================================

    def _format_error(
        self,
        error_msg: str,
    ) -> str:

        error_msg = str(
            error_msg or ""
        ).strip()

        lowered = error_msg.lower()

        if (
            "no profile" in lowered
            or "no relevant" in lowered
        ):

            return (
                "I couldn't find anything "
                "matching that request, Sir."
            )

        if (
            "429" in lowered
            or "too many requests" in lowered
            or "rate limit" in lowered
            or "quota" in lowered
            or "all configured llm providers failed"
            in lowered
        ):

            return (
                "My AI services are temporarily "
                "rate-limited, Sir. Try again shortly."
            )

        if not error_msg:

            return (
                "I couldn't complete that request "
                "just now, Sir. Try again shortly."
            )

        logger.error(
            "[Personality] Internal operation error: %s",
            error_msg,
        )

        return (
            "I couldn't complete that operation, Sir."
        )

    # =========================================================
    # GREETING
    # =========================================================

    def _format_greeting(
        self,
        user_text: str,
    ) -> str:

        query = user_text.lower()

        if "how are you" in query:

            return (
                "All systems operational and fully "
                "optimized, Sir. How may I assist "
                "you today?"
            )

        elif "morning" in query:

            return (
                "Good morning, Sir. All operational "
                "parameters are nominal."
            )

        elif "evening" in query:

            return (
                "Good evening, Sir. Ready for your "
                "instructions."
            )

        responses = [
            "Greetings, Sir. ARIA operational and ready.",
            "Good to see you again, Sir.",
            "At your service, Sir.",
            "Systems online. How may I assist?",
            "Ready whenever you are, Sir.",
        ]

        return random.choice(
            responses
        )

    # =========================================================
    # MEMORY
    # =========================================================

    def _format_memory(
        self,
        data: Any,
    ) -> str:

        data_dict = (
            data
            if isinstance(
                data,
                dict,
            )
            else {}
        )

        message = data_dict.get(
            "message"
        )

        if (
            isinstance(
                message,
                str,
            )
            and message.strip()
        ):

            return message.strip()

        memories = data_dict.get(
            "memories",
            [],
        )

        if not isinstance(
            memories,
            list,
        ):

            return (
                "I don't have any relevant "
                "memories about you yet."
            )

        normalized = {}

        for memory in memories:

            if not isinstance(
                memory,
                dict,
            ):

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

            value = str(
                value
            ).strip()

            if not value:

                continue

            if key.lower() in {
                "id",
                "memory_id",
                "record_id",
                "embedding",
                "metadata",
            }:

                continue

            normalized[key] = value

        if not normalized:

            return (
                "I don't have any relevant "
                "memories about you yet."
            )

        labels = {
            "name": "name",
            "current_degree": "current degree",
            "current_education_level": "current education",
            "future_education_plan": "future education plan",
            "planned_postgraduate_degree": "planned postgraduate degree",
            "planned_postgraduate_location": "planned postgraduate location",
            "study_destination": "study destination",
            "intended_degree": "intended degree",
            "backup_plan_country": "backup country",
            "alternative_country": "alternative country",
            "favorite_color": "favorite color",
            "favorite_colour": "favorite color",
            "favorite_language": "favorite programming language",
            "favorite_superhero": "favorite superhero",
            "favorite_movie": "favorite movie",
            "favorite_food": "favorite food",
            "favorite_car": "favorite car",
            "favorite_animal": "favorite animal",
            "favorite_planet": "favorite planet",
            "favorite_dinosaur": "favorite dinosaur",
            "project_name": "project",
            "project_type": "project type",
            "project": "project",
            "exam_preparation": "exam preparation",
            "education_preference": "education preference",
            "education_priority": "education priority",
            "preferred_education_region": "preferred education region",
            "preferred_watch_material": "preferred watch material",
            "watch_budget": "watch budget",
            "favorite_shopping_platform": "favorite shopping platform",
            "intended_purchase": "intended purchase",
            "preferred_name": "preferred form of address",
        }

        ignored_keys = {
            "user_likes",
            "phase_3_test_animal",
            "favorite_test_color",
        }

        filtered = {
            key: value
            for key, value in normalized.items()
            if key not in ignored_keys
        }

        if not filtered:

            return (
                "I don't have any relevant "
                "memories about you yet."
            )

        if len(filtered) == 1:

            key, value = next(
                iter(
                    filtered.items()
                )
            )

            label = labels.get(
                key,
                key.replace(
                    "_",
                    " ",
                ).strip().lower(),
            )

            if key == "name":

                return (
                    f"Your name is {value}."
                )

            return (
                f"Your {label} is {value}."
            )

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

            if (
                key in filtered
                and key not in ordered_keys
            ):

                ordered_keys.append(
                    key
                )

        for key in filtered:

            if key not in ordered_keys:

                ordered_keys.append(
                    key
                )

        lines = []

        for key in ordered_keys:

            value = filtered[key]

            label = labels.get(
                key,
                key.replace(
                    "_",
                    " ",
                ).capitalize(),
            )

            lines.append(
                f"• {label.capitalize()}: {value}"
            )

        if not lines:

            return (
                "I don't have any relevant "
                "memories about you yet."
            )

        return (
            "Here's what I remember about you:\n\n"
            + "\n".join(lines)
        )

    # =========================================================
    # PLANNER
    # =========================================================

    def _format_planner(
        self,
        data: Any,
    ) -> str:

        if not isinstance(
            data,
            dict,
        ):

            return (
                "Task executed successfully, Sir."
            )

        response = data.get(
            "response"
        )

        if (
            isinstance(
                response,
                str,
            )
            and response.strip()
        ):

            return response.strip()

        message = data.get(
            "message"
        )

        if (
            isinstance(
                message,
                str,
            )
            and message.strip()
        ):

            return message.strip()

        chat = data.get(
            "chat"
        )

        if isinstance(
            chat,
            dict,
        ):

            response = chat.get(
                "response"
            )

            if (
                isinstance(
                    response,
                    str,
                )
                and response.strip()
            ):

                return response.strip()

            message = chat.get(
                "message"
            )

            if (
                isinstance(
                    message,
                    str,
                )
                and message.strip()
            ):

                return message.strip()

        task_outputs = data.get(
            "task_outputs",
            {},
        )

        if isinstance(
            task_outputs,
            dict,
        ):

            for output in reversed(
                list(
                    task_outputs.values()
                )
            ):

                if not isinstance(
                    output,
                    dict,
                ):

                    continue

                for field in (
                    "response",
                    "content",
                    "message",
                    "answer",
                    "summary",
                ):

                    value = output.get(
                        field
                    )

                    if (
                        isinstance(
                            value,
                            str,
                        )
                        and value.strip()
                    ):

                        return value.strip()

        for output in data.values():

            if not isinstance(
                output,
                dict,
            ):

                continue

            for field in (
                "response",
                "content",
                "message",
                "answer",
                "summary",
            ):

                value = output.get(
                    field
                )

                if (
                    isinstance(
                        value,
                        str,
                    )
                    and value.strip()
                ):

                    return value.strip()

        return (
            "Execution completed successfully, Sir."
        )

    # =========================================================
    # ACTION
    # =========================================================

    def _format_action(
        self,
        data: Any,
    ) -> str:

        if not isinstance(
            data,
            dict,
        ):

            return (
                "Action completed successfully, Sir."
            )

        action_name = data.get(
            "action_name"
        )

        result = data.get(
            "result",
            {},
        )

        if action_name == "notification_action":

            if isinstance(
                result,
                dict,
            ):

                message = result.get(
                    "message"
                )

                if message:

                    return (
                        f"Notification dispatched: "
                        f"{message}, Sir."
                    )

            return (
                "Notification dispatched successfully, Sir."
            )

        if action_name == "file_action":

            if isinstance(
                result,
                dict,
            ):

                if "content" in result:

                    content = str(
                        result["content"]
                    )

                    if content:

                        return content

                    return (
                        "The file is empty, Sir."
                    )

                if (
                    result.get("status")
                    == "written successfully"
                ):

                    return (
                        "File written successfully, Sir."
                    )

            return (
                "File operation completed successfully, Sir."
            )

        if isinstance(
            result,
            dict,
        ):

            if "message" in result:

                return str(
                    result["message"]
                )

            if "response" in result:

                return str(
                    result["response"]
                )

        return (
            "Action completed successfully, Sir."
        )

    # =========================================================
    # GENERIC FALLBACK
    # =========================================================

    def _format_fallback(
        self,
        data: Any,
    ) -> str:

        if isinstance(
            data,
            dict,
        ):

            if "response" in data:

                return str(
                    data["response"]
                )

            if "message" in data:

                return str(
                    data["message"]
                )

            if "result" in data:

                return str(
                    data["result"]
                )

            if "output" in data:

                return (
                    f"Python Output\n\n"
                    f"{data['output']}"
                )

            return "\n".join(
                str(v)
                for v in data.values()
                if v
            )

        if isinstance(
            data,
            str,
        ):

            return data

        return "Done."

    # =========================================================
    # UNIVERSAL ARIA VOICE
    # =========================================================

    async def _apply_aria_voice(
        self,
        user_text: str,
        reply: str,
    ) -> str:

        reply = str(
            reply or ""
        ).strip()

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

            styled = str(
                styled or ""
            ).strip()

            if styled:

                logger.info(
                    "[Personality] Universal ARIA voice applied."
                )

                return styled

        except Exception:

            logger.exception(
                "[Personality] Universal ARIA voice pass failed. "
                "Using original response."
            )

        return reply

    # =========================================================
    # FINAL POST PROCESSING
    # =========================================================

    def _post_process(
        self,
        reply: str,
    ) -> str:

        if reply is None:

            return (
                "I couldn't generate a response, Sir."
            )

        reply = str(
            reply
        ).strip()

        if not reply:

            return (
                "I couldn't generate a response, Sir."
            )

        # -----------------------------------------------------
        # Protect fenced code blocks
        # -----------------------------------------------------

        code_blocks = []

        def protect_code(match):

            code_blocks.append(
                match.group(0)
            )

            return (
                f"ARIA_CODE_BLOCK_PLACEHOLDER_"
                f"{len(code_blocks) - 1}"
            )

        reply = re.sub(
            r"```[\s\S]*?```",
            protect_code,
            reply,
        )

        # -----------------------------------------------------
        # Clean Markdown headings
        # -----------------------------------------------------

        reply = re.sub(
            r"(?m)^\s{0,3}#{1,6}\s+",
            "",
            reply,
        )

        # -----------------------------------------------------
        # Remove Markdown bold/italic markers
        # -----------------------------------------------------

        reply = re.sub(
            r"\*\*(.*?)\*\*",
            r"\1",
            reply,
        )

        reply = re.sub(
            r"__(.*?)__",
            r"\1",
            reply,
        )

        reply = re.sub(
            r"(?<!\*)\*([^*\n]+)\*(?!\*)",
            r"\1",
            reply,
        )

        # -----------------------------------------------------
        # Remove horizontal separators
        # -----------------------------------------------------

        reply = re.sub(
            r"(?m)^\s*(?:---+|\*\*\*+|___+)\s*$",
            "",
            reply,
        )

        # -----------------------------------------------------
        # Normalize bullets
        # -----------------------------------------------------

        reply = re.sub(
            r"(?m)^\s*[-*+]\s+",
            "• ",
            reply,
        )

        # -----------------------------------------------------
        # Clean excessive blank lines
        # -----------------------------------------------------

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

        # -----------------------------------------------------
        # Remove trailing spaces
        # -----------------------------------------------------

        reply = "\n".join(
            line.rstrip()
            for line in reply.splitlines()
        )

        # -----------------------------------------------------
        # Restore protected code blocks
        # -----------------------------------------------------

        for index, block in enumerate(
            code_blocks
        ):

            reply = reply.replace(
                (
                    f"ARIA_CODE_BLOCK_PLACEHOLDER_"
                    f"{index}"
                ),
                block,
            )

        reply = reply.strip()

        # -----------------------------------------------------
        # Add punctuation only to simple one-line responses
        # -----------------------------------------------------

        if (
            reply
            and "\n" not in reply
            and reply[-1] not in ".!?"
        ):

            reply += "."

        return reply