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
            # 1. Handle failures/missing records gracefully without implying system malfunctions
            if not response.success:
                error_msg = response.error or ""
                if "no profile" in error_msg.lower() or "no relevant" in error_msg.lower():
                    return "I couldn't find any stored records matching that request, Sir."
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
                    name = data.get("name", "the user")
                    role = data.get("role", "Developer & Student")
                    institution = data.get("institution", "")
                    inst_str = f" at {institution}" if institution else ""
                    return f"Profile records retrieved for {name}. Current role: {role}{inst_str}."
                return "No active profile records were located, Sir."

            # 4. Handle Memory Skill payloads (MongoDB schema alignment: key/value)
            if source == "memory":
                memories = data.get("memories", [])
                if memories:
                    snippets = []
                    for m in memories:
                        if isinstance(m, dict):
                            key = m.get("key", "memory")
                            value = m.get("value", "")
                            if value:
                                snippets.append(f"{key}: {value}")
                            else:
                                snippets.append(str(m))
                        else:
                            snippets.append(str(m))
                    if snippets:
                        joined = "; ".join(snippets[:4])
                        return f"Recalled data, Sir: {joined}"
                return data.get("message", "No relevant long-term memories found matching your query, Sir.")

            # 5. Handle Planner / Executor multi-task orchestration results
            if source == "planner_executor":
                if isinstance(data, dict) and data:
                    summaries = []
                    for task_id, output in data.items():
                        if isinstance(output, dict):
                            msg = output.get("message") or output.get("status") or str(output)
                            summaries.append(f"Task {task_id}: {msg}")
                        else:
                            summaries.append(f"Task {task_id}: {output}")
                    return "Execution completed successfully, Sir. " + " | ".join(summaries)

            # 6. Fallback formatting for general data
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

        except Exception as e:
            logger.exception("[PersonalityEngine ERROR] Failed to format response: %s", e)
            return "Operation completed, though a formatting error occurred, Sir."
