from datetime import datetime, timezone

class ConversationManager:
    def __init__(self, chats_collection):
        self.chats_col = chats_collection
        # In-memory session tracking for active context and last referenced documents
        self.active_sessions = {}

    async def build_session_context(self, session_id: str) -> dict:
        """Builds conversation history and metadata context for a given session."""
        if session_id not in self.active_sessions:
            self.active_sessions[session_id] = {
                "history": [],
                "last_referenced_document": None
            }
        
        session = self.active_sessions[session_id]
        if self.chats_col is not None and not session["history"]:
            try:
                cursor = self.chats_col.find({"session_id": session_id}).sort("_id", -1).limit(5)
                docs = await cursor.to_list(length=5)
                docs.reverse()
                session["history"] = [{"role": "user", "content": d.get("user_msg")} for d in docs]
            except Exception:
                pass
                
        return session

    def set_last_document(self, session_id: str, doc_name: str):
        """Tracks the last document referenced in conversation for zero-latency follow-ups."""
        if session_id not in self.active_sessions:
            self.active_sessions[session_id] = {"history": [], "last_referenced_document": None}
        self.active_sessions[session_id]["last_referenced_document"] = doc_name
