import json
import re

async def action_planner(user_message: str, session_context: str, tool_descriptions: dict, executed_tools: list, llm_router) -> dict:
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
  "tools": ["memory", "documents", "web", "media", "schedule"]
}}

If no further tools are needed, return an empty list for tools:
{{
  "goal": "complete",
  "action": "retrieve",
  "tools": []
}}
"""
    messages = [
        {"role": "system", "content": "You are a precise JSON task planner. Output valid JSON only."},
        {"role": "user", "content": prompt}
    ]
    try:
        raw = await llm_router.chat(messages, temperature=0.1, max_tokens=200)
        
        # Safeguard: if quota error string returned instead of JSON
        if not raw or not raw.strip().startswith("{"):
            print(f"[Planner Warning]: Non-JSON response received: {raw}")
            return {"goal": "fallback", "action": "retrieve", "tools": []}

        cleaned_raw = re.sub(r'```json\s*|\s*```', '', raw)
        return json.loads(cleaned_raw)
    except Exception as e:
        print(f"[Action Planner Error]: {e}")
        return {"goal": "error", "action": "retrieve", "tools": []}
