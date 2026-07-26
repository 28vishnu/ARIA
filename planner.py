import json
import re
from groq import Groq

async def action_planner(user_message: str, session_context: str, tool_descriptions: dict, executed_tools: list, groq_client: Groq) -> dict:
    """Action-based iterative planner that determines goal, action type, and required tools."""
    if not groq_client:
        return {"goal": "default", "action": "retrieve", "tools": []}

    tools_json = json.dumps(tool_descriptions, indent=2)
    already_run = json.dumps(executed_tools)

    prompt = f"""
You are an autonomous action planner for ARIA, a J.A.R.V.I.S.-style assistant.

Available Registered Tools & Capabilities:
{tools_json}

Tools already executed in previous steps:
{already_run}

Recent Session Context:
{session_context}

User Request: "{user_message}"

Analyze the user request and determine the primary action and required tools. 
Action types allowed: retrieve, save, delete, dispatch, analyze, schedule, search.

Return ONLY a valid JSON object:
{{
  "goal": "short description of objective",
  "action": "retrieve|save|delete|dispatch|analyze|schedule|search",
  "tools": ["memory", "documents", "web"]
}}

If no further tools are needed, return an empty list for tools:
{{
  "goal": "complete",
  "action": "retrieve",
  "tools": []
}}
"""
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'```json\s*|\s*```', '', raw)
        return json.loads(raw)
    except Exception as e:
        print(f"[Action Planner Error]: {e}")
        return {"goal": "error", "action": "retrieve", "tools": []}
