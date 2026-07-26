import json
import re
from groq import Groq

async def iterative_planner(user_message: str, tool_descriptions: dict, executed_tools: list, groq_client: Groq) -> dict:
    """Iterative planner that evaluates if more tools are needed based on execution history."""
    if not groq_client:
        return {"goal": "default", "reason": "No client", "tools": []}

    tools_json = json.dumps(tool_descriptions, indent=2)
    already_run = json.dumps(executed_tools)

    prompt = f"""
You are an iterative AI task planner for ARIA. Your job is to select the next required tool or conclude planning.

Available Registered Tools & Capabilities:
{tools_json}

Tools already executed in previous steps:
{already_run}

User Request: "{user_message}"

Analyze if additional tools are required to fully answer the user. Return ONLY a valid JSON object:
{{
  "goal": "short description of current objective",
  "reason": "why this tool is needed or why no more tools are needed",
  "tools": ["tool_name_1"]
}}

If no further tools are needed, return an empty list for tools:
{{
  "goal": "complete",
  "reason": "all required data gathered",
  "tools": []
}}
"""
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=150
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'```json\s*|\s*```', '', raw)
        return json.loads(raw)
    except Exception as e:
        print(f"[Iterative Planner Error]: {e}")
        return {"goal": "error", "reason": str(e), "tools": []}
