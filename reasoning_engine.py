class CrossDocumentReasoner:
    def __init__(self, llm_router):
        self.llm_router = llm_router

    async def compare_documents(self, documents: list[dict], objective: str = "Compare these documents for consistencies, differences, and contradictions.") -> str:
        """Scalable multi-document reasoning engine supporting an arbitrary list of documents."""
        if not documents:
            return "No documents provided for cross-document analysis, Sir."

        docs_combined = ""
        for idx, doc in enumerate(documents):
            title = doc.get("title", f"Document {idx+1}")
            content = doc.get("content", "")[:1500]
            docs_combined += f"\n\n--- SOURCE [{title}] ---\n{content}"

        prompt = f"""
You are ARIA's advanced cross-document reasoning core. Analyze the following {len(documents)} source documents and fulfill the objective.

Objective: {objective}

Source Documents:
{docs_combined}

Provide a structured, rigorous analytical synthesis and comparison across all provided sources, Sir.
"""
        messages = [
            {"role": "system", "content": "You are a precise multi-document analytical reasoning engine."},
            {"role": "user", "content": prompt}
        ]
        try:
            return await self.llm_router.chat(messages, temperature=0.1, max_tokens=650)
        except Exception as e:
            return f"Cross-document reasoning failed: {e}"
