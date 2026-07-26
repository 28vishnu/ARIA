class CrossDocumentReasoner:
    def __init__(self, llm_router):
        self.llm_router = llm_router

    async def compare_documents(self, doc_text_a: str, doc_text_b: str, objective: str = "Compare these documents for consistencies and differences.") -> str:
        """Performs cross-document reasoning and comparative analysis across multiple files."""
        prompt = f"""
You are ARIA's cross-document reasoning engine. Analyze the following two source texts and fulfill the objective.

Objective: {objective}

Source Document A:
{doc_text_a[:2000]}

Source Document B:
{doc_text_b[:2000]}

Provide a structured, precise analytical comparison, Sir.
"""
        messages = [
            {"role": "system", "content": "You are a rigorous analytical reasoning core."},
            {"role": "user", "content": prompt}
        ]
        try:
            return await self.llm_router.chat(messages, temperature=0.1, max_tokens=500)
        except Exception as e:
            return f"Cross-document reasoning failed: {e}"
