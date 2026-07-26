from groq import Groq
from personality import SYSTEM_PROMPT

async def reason(user_message: str, context: str, groq_client: Groq, temporal_ctx: str) -> str:
    if not groq_client:
        return "Neural systems offline, Sir."

    full_system = f"{SYSTEM_PROMPT}\n{temporal_ctx}\n\n[COLLECTED CONTEXT]:\n{context}"

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": full_system},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2,
            max_tokens=350
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Reasoning engine error: {str(e)}"

async def evaluate_confidence(answer: str, groq_client: Groq) -> int:
    """Self-check confidence evaluation (0-100 score)."""
    if not groq_client: return 100
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
