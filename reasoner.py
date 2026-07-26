from groq import Groq
from personality import assemble_system_prompt

async def reason(user_message: str, structured_context: dict, groq_client: Groq, temporal_ctx: str, tools_desc: dict) -> str:
    if not groq_client:
        return "Neural systems offline, Sir."

    system_prompt = assemble_system_prompt(temporal_ctx, structured_context, str(tools_desc))

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2,
            max_tokens=350
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Reasoning engine error: {str(e)}"

async def evaluate_confidence(answer: str, groq_client: Groq) -> int:
    if not groq_client: return 90
    prompt = f"Rate the completeness and accuracy of this response on a scale of 0 to 100. Return only the integer score: '{answer}'"
    try:
        res = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1, max_tokens=10
        )
        import re
        match = re.search(r'\d+', res.choices[0].message.content)
        return int(match.group()) if match else 85
    except Exception:
        return 85
