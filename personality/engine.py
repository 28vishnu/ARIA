import logging
from typing import Dict, Any
from personality.response import SystemResponse

logger = logging.getLogger("aria")

class PersonalityEngine:
    def __init__(self, llm_router=None):
        self.llm_router = llm_router

    def apply_personality(self, session_id: str, user_text: str, response: SystemResponse) -> str:
        """Transforms structured SystemResponse payloads into natural, contextual language."""
        try:
            # 1. Handle failures gracefully with a professional tone
            if not response.success:
                error_msg = response.error or "An unexpected issue occurred while processing your request, Sir."
                return f"I encountered a slight complication: {error_msg}"

            data = response.data or {}
            source = response.source

            # 2. Handle greetings or conversational intents naturally
            if source in ["greeting_fast_path", "planner_conversational"] or data.get("intent") in ["greeting", "conversational"]:
                query = data.get("query", user_text).lower()
                if "how are you" in query:
                    return "All systems operational and fully optimized, Sir. How may I assist you today?"
                elif "morning" in query:
                    return "Good morning, Sir. All operational parameters are nominal."
                elif "evening" in query:
                    return "Good evening, Sir. Ready for your instructions."
                return "Greetings, Sir. ARIA operational and ready."

            # 3. Handle Profile Skill payloads
            if source == "profile":
                if isinstance(data, dict) and data:
                    name = data.get("name", "Vishnu")
                    role = data.get("role", "Developer & Student")
                    institution = data.get("institution", "")
                    return f"Profile data retrieved for {name}. You are currently pursuing studies as a {role} at {institution}."
                return "No active profile records were located, Sir."

            # 4. Handle Memory Skill payloads
            if source == "memory":
                memories = data.get("memories", [])
                if memories:
                    # If memories is a list of dicts or strings
                    snippets = []
                    for m in memories:
                        if isinstance(m, dict):
                            snippets.append(m.get("fact") or m.get("content") or str(m))
                        else:
                            snippets.append(str(m))
                    joined = "; ".join(snippets[:3])
                    return f"Recalled data, Sir: {joined}"
                return data.get("message", "No relevant long-term memories found matching your query, Sir.")

            # 5. Handle Planner / Executor multi-task orchestration results
            if source == "planner_executor":
                if isinstance(data, dict) and data:
                    summaries = []
                    for task_id, output in data.items():
                        if isinstance(output, dict):
                            # extract sensible message or content if present
                            msg = output.get("message") or output.get("status") or str(output)
                            summaries.append(f"Task {task_id}: {msg}")
                        else:
                            summaries.append(f"Task {task_id}: {output}")
                    return "Execution completed successfully, Sir. " + " | ".join(summaries)

            # 6. Fallback string representation if data is a raw dict/string
            if isinstance(data, dict):
                if "message" in data:
                    return str(data["message"])
                if data:
                    # Return formatted key-value pairs instead of raw JSON/{}
                    formatted_pairs = [f"{k}: {v}" for k, v in data.items() if v]
                    if formatted_pairs:
                        return "Here is the information retrieved, Sir:\n" + "\n".join(formatted_pairs)

            if isinstance(data, str) and data.strip():
                return data

            return "Task executed successfully, Sir."

        except Exception as e:
            logger.exception("[PersonalityEngine ERROR] Failed to format response: %s", e)
            return "Operation completed, though a formatting error occurred, Sir."
