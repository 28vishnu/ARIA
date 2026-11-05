class ReflectionEngine:
    def __init__(self, chats_col, media_col):
        self.chats_col = chats_col
        self.media_col = media_col

    async def evaluate_feedback(self, user_text: str, session_id: str) -> dict | None:
        """Evaluates corrections and returns a structured directive rather than an immediate string."""
        lower = user_text.lower()
        
        is_negative_correction = any(phrase in lower for phrase in [
            "not my resume", "wrong file", "incorrect", "that's wrong", 
            "not what i asked", "not the right", "wrong document"
        ])

        if is_negative_correction:
            print(f"[REFLECTION ENGINE] Negative correction detected for session {session_id}: '{user_text}'")
            
            if self.chats_col is not None:
                last_chat = await self.chats_col.find_one({"session_id": session_id}, sort=[("_id", -1)])
                if last_chat:
                    print(f"[REFLECTION ENGINE] Previous assistant reply was: {last_chat.get('aria_reply')}")

            return {
                "needs_retry": True,
                "retry_tool": "media",
                "explanation": "Understood, Sir. The previously dispatched file was incorrect. Let me re-examine the vault for your correct document."
            }
        
        return None
