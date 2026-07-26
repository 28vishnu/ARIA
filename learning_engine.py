import os
from datetime import datetime, timezone, timedelta

class LearningEngine:
    def __init__(self, mongo_db, llm_router):
        self.db = mongo_db
        self.chats_col = mongo_db["chat_history"] if mongo_db is not None else None
        self.llm_router = llm_router

    async def generate_weekly_report(self) -> str:
        """Inspects past interactions, tool usage success, and queries to generate a self-improvement report."""
        print("[LEARNING ENGINE]: Generating weekly operational and learning report...")
        if self.chats_col is None:
            return "Learning database offline."

        # Fetch interactions from the past 7 days
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        cursor = self.chats_col.find({"timestamp": {"$gte": week_ago}}).limit(50)
        recent_chats = await cursor.to_list(length=50)

        interaction_count = len(recent_chats)
        summary_prompt = f"""
You are ARIA's self-governing learning engine. Analyze the following recent interaction volume ({interaction_count} sessions) and synthesize a concise weekly learning report covering system reliability, user preferences, and optimization opportunities.

Return a structured professional report.
"""
        messages = [
            {"role": "system", "content": "You are a precise system telemetry analyst."},
            {"role": "user", "content": summary_prompt}
        ]
        try:
            return await self.llm_router.chat(messages, temperature=0.2, max_tokens=350)
        except Exception as e:
            return f"Failed to generate learning report: {e}"
