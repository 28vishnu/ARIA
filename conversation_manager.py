from datetime import datetime, timezone

class ConversationManager:
    def __init__(self, mongo_chats_col):
        self.chats_col = mongo_chats_col

    async def get_session_history(self, session_id: str, limit: int = 15) -> list[dict]:
        if not self.chats_col: return []
        try:
            cursor = self.chats_col.find({"session_id": session_id}).sort("_id", -1).limit(limit)
            docs = await cursor.to_list(length=limit)
            return list(reversed(docs))
        except Exception:
            return []

    async def build_session_context(self, session_id: str) -> str:
        history = await self.get_session_history(session_id, limit=12)
        if not history: return "No prior session history."
        
        lines = []
        for h in history:
            lines.append(f"User: {h.get('user_msg')}\nARIA: {h.get('aria_reply')}")
        return "\n--- RECENT CONVERSATION CONTEXT ---\n" + "\n".join(lines) + "\n------------------------------------"
