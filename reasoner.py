from personality import assemble_system_prompt

async def reason(user_message: str, structured_results: dict, llm_router, temporal_ctx: str, tools_desc: dict, session_context: str) -> str:
    print("[STAGE 3 - REASONER] Assembling context and invoking LLM reasoner...")
    
    context_blocks = []
    for source_name, res in structured_results.items():
        if res is not None and res.get("success") and res.get("content"):
            conf = res.get("confidence", 0.0)
            context_blocks.append(f"[{source_name.upper()} SOURCE | Confidence: {conf}]:\n{res['content']}")

    compiled_context = "\n\n".join(context_blocks) if context_blocks else "No external context retrieved."
    system_prompt = assemble_system_prompt(temporal_ctx, compiled_context, str(tools_desc), session_context)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    try:
        response = await llm_router.chat(messages, temperature=0.2, max_tokens=350)
        print(f"[STAGE 3 - REASONER] Successfully generated response: {response[:100]}...")
        return response
    except Exception as e:
        print(f"[STAGE 3 - REASONER EXCEPTION]: {e}")
        return f"Reasoning engine error: {str(e)}"
