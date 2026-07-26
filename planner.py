import json
import re

async def action_planner(user_text: str, session_context: str, available_tools: dict, executed_tools: list, llm_router) -> dict:
    """Robust action planner with automatic Markdown fence stripping and JSON parsing fallback."""
    
    prompt = f"""
You are ARIA's action planning engine. Given the user request, choose which tools to execute from the available options.
Available Tools: {available_tools}
Executed Tools So Far: {executed_tools}
User Request: "{user_text}"

Respond STRICTLY in valid JSON format with no extra commentary:
{{
    "action": "retrieve",
    "tools": ["tool_name_1"]
}
}
"""
    messages = [
        {"role": "system", "content": "You are a precise JSON-only decision planner."},
        {"role": "user", "content": prompt}
    ]

    default_plan = {"action": "retrieve", "tools": []}

    try:
        response = await llm_router.chat(messages, temperature=0.1, max_tokens=150)
        
        # Strip markdown fences if present
        cleaned_res = re.sub(r'```(?:json)?\s*', '', response)
        cleaned_res = re.sub(r'\s*```', '', cleaned_res).strip()
        
        # Isolate the JSON object bounds
        match = re.search(r'(\{.*\})', cleaned_res, re.DOTALL)
        if match:
            json_str = match.group(1)
            return json.loads(json_str)
        
        return json.loads(cleaned_res)
    except Exception as e:
        print(f"[Action Planner Parsing Warning]: {e} | Raw Response: {locals().get('response', 'None')}")
        return default_plan
