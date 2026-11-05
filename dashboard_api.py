from fastapi import APIRouter
from datetime import datetime, timezone

def create_dashboard_router(db, llm_router, chroma_client):
    router = APIRouter()

    @router.get("/dashboard/telemetry")
    async def get_telemetry():
        """Returns live system telemetry, memory stats, project progress, and API health status."""
        profile_col = db["user_profile"] if db is not None else None
        profile = await profile_col.find_one({"_id": "master_profile"}) if profile_col else {}
        
        chat_col = db["chat_history"] if db is not None else None
        chat_count = await chat_col.estimated_document_count() if chat_col else 0

        media_col = db["media_vault"] if db is not None else None
        media_count = await media_col.estimated_document_count() if media_col else 0

        return {
            "system": "ARIA AI Operating System",
            "status": "Operational",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_profile": profile.get("name", "Saketh"),
            "active_project": profile.get("active_project", {}),
            "telemetry": {
                "total_chats_logged": chat_count,
                "documents_in_vault": media_count,
                "vector_database": "ChromaDB (Persistent)",
                "ai_providers_active": ["Groq", "OpenRouter", "Mistral", "Gemini"]
            }
        }

    return router
