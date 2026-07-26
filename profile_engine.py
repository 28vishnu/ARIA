import os
from datetime import datetime, timezone

class ProfileEngine:
    def __init__(self, db):
        self.profile_col = db["user_profile"] if db is not None else None

    async def get_profile(self) -> dict:
        """Retrieves the structured user profile."""
        if self.profile_col is None:
            return {}
        profile = await self.profile_col.find_one({"_id": "master_profile"})
        if not profile:
            default_profile = {
                "_id": "master_profile",
                "name": "Saketh",
                "location": "Sujathanagar, Visakhapatnam",
                "college": "Gayatri Vidya Parishad College for Degree and PG Courses",
                "course": "B.Tech Computer Science Engineering (Expected 2028)",
                "routine": {"wake": "07:00 AM", "sleep": "11:30 PM", "college_start": "09:00 AM"},
                "active_project": {"name": "ARIA AI", "progress": "85%", "next_task": "Background Workers & Knowledge Graph"},
                "preferences": {"interface": "Telegram", "tone": "JARVIS-style, concise, professional"}
            }
            await self.profile_col.insert_one(default_profile)
            return default_profile
        return profile

    async def update_profile(self, key: str, value: any):
        """Updates a specific field in the user profile."""
        if self.profile_col is not None:
            await self.profile_col.update_one(
                {"_id": "master_profile"},
                {"$set": {key: value, "updated_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True
            )
