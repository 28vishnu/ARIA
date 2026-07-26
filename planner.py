import json
import re

async def action_planner(user_message: str, session_context: str, tool_descriptions: dict, executed_tools: list, llm_router) -> dict:
    if len(executed_tools) >= 3:
        print("[Planner Safeguard]: Maximum tool iterations reached. Stopping loop.")
        return {"goal": "complete", "action": "retrieve", "tools": []}

    tools_json = json.dumps(tool_descriptions, indent=2)
    already_run = json.dumps(executed_tools)

    prompt = f"""
You are an advanced reflective action planner for ARIA, an autonomous AI operating system.

Available Registered Tools & Specialist Agents:
{tools_json}

Tools already executed in previous steps:
{already_run}

Recent Session Context:
{session_context}

User Request: "{user_message}"

Reflect on the user request, evaluate if previous tools yielded enough information, and determine the next optimal action and required tools/agents.
Action types allowed: retrieve, save, delete, dispatch, analyze, schedule, search.

Return ONLY a valid JSON object:
{{
  "reflection": "brief analysis of current state and missing data",
  "goal": "short description of objective",
  "action": "retrieve|save|delete|dispatch|analyze|schedule|search",
  "tools": ["memory", "documents", "web", "media", "schedule"]
}}

If no further tools are needed, return an empty list for tools:
{{
  "reflection": "All required data acquired.",
  "goal": "complete",
  "action": "retrieve",
  "tools": []
}}
"""
    messages = [
        {"role": "system", "content": "You are a precise reflective JSON task planner. Output valid JSON only."},
        {"role": "user", "content": prompt}
    ]
    try:
        raw = await llm_router.chat(messages, temperature=0.1, max_tokens=250)
        cleaned_raw = re.sub(r'```(?:json)?\s*|\s*```', '', raw).strip()
        
        if not cleaned_raw.startswith("{"):
            print(f"[Planner Warning]: Non-JSON response received: {cleaned_raw[:50]}")
            return {"goal": "fallback", "action": "retrieve", "tools": []}

        return json.loads(cleaned_raw)
    except Exception as e:
        print(f"[Action Planner Error]: {e}")
        return {"goal": "error", "action": "retrieve", "tools": []}
