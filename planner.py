import json
import re
from groq import Groq

async def planner(user_message: str, groq_client: Groq) -> dict:
    prompt = f"""
You are an AI task planner for ARIA, a J.A.R.V.I.S.-style assistant.

Available tools:
- memory (for past personal facts, preferences, user statements)
- documents (for searching uploaded PDFs, resumes, certificates, notes)
- web (for live internet intelligence, news, current facts, weather)
- vision (for inspecting images or screenshots)
- calendar (for schedules or reminders)

Analyze the user's message and return ONLY a valid JSON object specifying which tools to trigger:
{{
  "tools": ["memory", "documents", "web", "vision", "calendar"]
}}

If no special tools are required, return:
{{
  "tools": []
}}

User Message:
"{user_message}"
"""
    if not groq_client:
        return {"tools": []}

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=100
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'```json\s*|\s*```', '', raw)
        return json.loads(raw)
    except Exception as e:
        print(f"[Planner Error]: {e}")
        return {"tools": []}
