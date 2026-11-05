import traceback

async def reason(user_query: str, structured_results: dict, llm_router, temporal_context: str, tool_descriptions: dict, session_context: str) -> str:
    """Synthesizes structured tool outputs, conversational history, and temporal context into a polished assistant response."""
    print("[REASONER]: Synthesizing response from structured tool results...")

    # Flatten structured tool results into text context for the reasoner
    gathered_data = []
    for tool_name, data in structured_results.items():
        if data and data.get("success"):
            content = data.get("content", "")
            gathered_data.append(f"[{tool_name.upper()} DATA]:\n{content}")

    tools_context = "\n\n".join(gathered_data) if gathered_data else "No external tool data retrieved."

    system_prompt = f"""
You are ARIA, an advanced, autonomous AI Operating System built as a personal assistant for Saketh.
You maintain a professional, sharp, and composed JARVIS-style persona. 

{temporal_context}

Recent Session Conversation History:
{session_context}

Retrieved Tool Intelligence:
{tools_context}

User Request: "{user_query}"

Instructions:
1. Synthesize the retrieved tool intelligence and conversation context to directly answer the user request.
2. Never leak raw API JSON, code syntax errors, or internal debugging variables.
3. Maintain a polished, professional tone and conclude appropriately (e.g., addressing the user as Sir when suitable).
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query}
    ]

    try:
        response = await llm_router.chat(messages, temperature=0.2, max_tokens=450)
        return response
    except Exception as e:
        print(f"[Reasoner Error]: {e}")
        traceback.print_exc()
        return "I encountered an error while synthesizing your request, Sir. All systems remain operational."
