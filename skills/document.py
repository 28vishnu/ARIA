from skills.base import BaseSkill, SkillResponse

class DocumentSkill(BaseSkill):
    name = "document"
    description = "Retrieves semantic passages and summaries from indexed documents."
    version = "1.0.0"
    priority = 50
    requires_llm = True

    async def can_run(self, query: str, context: dict) -> float:
        lower = query.lower().strip()

        # Strong explicit document references
        document_terms = [
            "pdf",
            "document",
            "file",
            "resume",
            "cv"
        ]

        if any(term in lower for term in document_terms):
            return 0.95

        # Document operations should only count when a document is active/uploaded
        app_state = context.get("app_state")
        has_active_document = False

        if app_state:
            has_active_document = bool(
                getattr(app_state, "active_document", False)
                or getattr(app_state, "document_uploaded", False)
                or getattr(app_state, "current_document", None)
            )

        if has_active_document:
            document_actions = [
                "summarize",
                "summarise",
                "explain this",
                "what does it say",
                "according to this",
                "in this"
            ]

            if any(term in lower for term in document_actions):
                return 0.90

        return 0.0

    async def execute(self, query: str, context: dict) -> SkillResponse:
        app_state = context.get("app_state")
        doc_intel = getattr(app_state, "doc_intelligence", None) if app_state else None
        if doc_intel is not None:
            res = await doc_intel.query_document(query)
            if res.success and res.document:
                summary = await doc_intel.summarize_document(res.document, query)
                return SkillResponse(success=True, confidence=res.document.confidence, source=self.name, data={"document": res.document, "summary": summary})
        return SkillResponse(success=False, confidence=0.92, source=self.name, error="Document intelligence offline or no matches found.")
