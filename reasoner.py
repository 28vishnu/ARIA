from groq import Groq
from personality import assemble_system_prompt

async def reason(user_message: str, structured_results: dict, groq_client: Groq, temporal_ctx: str, tools_desc: dict, session_context: str) -> str:
    print("[STAGE 5 - REASONER] Assembling context and invoking LLM reasoner...")
    if groq_client is None:
        print("[STAGE 5 - REASONER] Error: Groq client unconfigured.")
        return "Neural systems offline, Sir."

    context_blocks = []
    for source_name, res in structured_results.items():
        if res is not None and res.get("success") and res.get("content"):
            conf = res.get("confidence", 0.0)
            context_blocks.append(f"[{source_name.upper()} SOURCE | Confidence: {conf}]:\n{res['content']}")

    compiled_context = "\n\n".join(context_blocks) if context_blocks else "No external context retrieved."
    system_prompt = assemble_system_prompt(temporal_ctx, compiled_context, str(tools_desc), session_context)

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
        answer = response.choices[0].message.content.strip()
        print(f"[STAGE 5 - REASONER] Successfully generated response: {answer[:100]}...")
        return answer
    except Exception as e:
        print(f"[STAGE 5 - REASONER EXCEPTION]: {e}")
        return f"Reasoning engine error: {str(e)}"
