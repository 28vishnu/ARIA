import os
from datetime import datetime, timezone, timedelta

class RelationshipEngine:
    def __init__(self, mongo_db):
        self.db = mongo_db
        self.profile_col = mongo_db["user_profile"] if mongo_db is not None else None
        self.chats_col = mongo_db["chat_history"] if mongo_db is not None else None

    async def get_contextual_nudge(self) -> str | None:
        """Evaluates active projects, recent conversation history, and milestones to generate proactive context-aware follow-ups."""
        if not self.profile_col or not self.chats_col:
            return None

        profile = await self.profile_col.find_one({"_id": "master_profile"})
        if not profile:
            return None

        # Fetch last conversation thread to extract recent context
        last_chat = await self.chats_col.find_one({}, sort=[("timestamp", -1)])
        active_project = profile.get("active_project", {})
        proj_name = active_project.get("name", "ARIA")
        next_task = active_project.get("next_task", "development tasks")

        # Dynamic context-aware proactive prompts based on active state
        now_utc = datetime.now(timezone.utc)
        
        # Morning briefing contextual nudge
        if now_utc.hour == 9 and now_utc.minute == 0:
            if last_chat:
                user_msg = last_chat.get("user_msg", "").lower()
                if "planner" in user_msg or "agent" in user_msg or "code" in user_msg:
                    return f"Good morning, Sir. Last week you were heavily focused on {proj_name}'s {next_task}. Shall we pick up right where we left off?"
            return f"Good morning, Sir. Your active project '{proj_name}' is currently at {active_project.get('progress', 'active stage')}. Shall we tackle '{next_task}' today?"

        return None
