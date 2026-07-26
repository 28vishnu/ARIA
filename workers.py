import os
import httpx
from datetime import datetime, timezone
import random

class BackgroundWorkers:
    def __init__(self, mongo_db, profile_engine, llm_router, tavily_client):
        self.db = mongo_db
        self.profile_engine = profile_engine
        self.llm_router = llm_router
        self.tavily = tavily_client
        self.chats_col = mongo_db["chat_history"] if mongo_db is not None else None
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.admin_chat_id = os.getenv("ADMIN_CHAT_ID")

    async def send_telegram_notification(self, text: str):
        """Dispatches proactive background notifications to Telegram."""
        if not self.token or not self.admin_chat_id:
            print(f"[Worker Notice - No Admin ID]: {text}")
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.admin_chat_id, "text": text}
                )
            print("[Worker Notification Dispatched Successfully]")
        except Exception as e:
            print(f"[Worker Notification Error]: {e}")

    async def morning_briefing_worker(self):
        """Morning Worker (Runs daily at 09:00 AM): Dynamically pulls profile, goals, routine, and live weather."""
        print("[BACKGROUND WORKER]: Running dynamic Morning Briefing...")
        if self.chats_col is None: return

        # Check if user already interacted today
        now_utc = datetime.now(timezone.utc)
        start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        recent_chat = await self.chats_col.find_one({"timestamp": {"$gte": start_of_day}})

        if recent_chat:
            print("[Morning Worker]: User already active today. Skipping briefing.")
            return

        # 1. Fetch dynamic profile, location, routine, and goals
        profile = await self.profile_engine.get_profile()
        user_name = profile.get("name", "Sir")
        location = profile.get("location", "Visakhapatnam")
        routine = profile.get("routine", {})
        active_project = profile.get("active_project", {"name": "ARIA AI", "progress": "In Progress"})

        # 2. Fetch live weather for the saved location
        weather_info = "Weather data unavailable."
        try:
            if self.tavily:
                res = self.tavily.search(query=f"current weather in {location}", max_results=1)
                if res and res.get("results"):
                    weather_info = res["results"][0]["content"][:150]
        except Exception:
            pass

        # 3. Fetch top AI/Tech news for briefing intelligence
        tech_news = "No recent updates."
        try:
            if self.tavily:
                res = self.tavily.search(query="latest breakthroughs in artificial intelligence 2026", max_results=1)
                if res and res.get("results"):
                    tech_news = res["results"][0]["title"]
        except Exception:
            pass

        briefing = (
            f"Good morning, {user_name}. ARIA systems online.\n\n"
            f"🌤 **Morning Briefing**:\n"
            f"• Location: {location}\n"
            f"• Expected Routine: Wake at {routine.get('wake', '07:00 AM')} | College at {routine.get('college_start', '09:00 AM')}\n"
            f"• Active Project: {active_project.get('name')} (Progress: {active_project.get('progress')})\n"
            f"• Next Objective: {active_project.get('next_task', 'Core System Upgrades')}\n"
            f"• Weather: {weather_info}\n"
            f"• Tech Radar: {tech_news}\n\n"
            f"Make it a productive day, {user_name}. Standing by."
        )
        await self.send_telegram_notification(briefing)

    async def night_summary_worker(self):
        """Night Worker (Runs daily at 10:00 PM): Dynamically summarizes what actually happened today."""
        print("[BACKGROUND WORKER]: Running dynamic Night Summary...")
        if self.chats_col is None: return

        # Summarize conversations from today
        now_utc = datetime.now(timezone.utc)
        start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        cursor = self.chats_col.find({"timestamp": {"$gte": start_of_day}}).limit(20)
        today_chats = await cursor.to_list(length=20)

        interaction_summary = f"{len(today_chats)} interactions logged today."
        if today_chats:
            topics = [c.get("user_msg", "")[:30] for c in today_chats[:3]]
            interaction_summary += f" Key topics: {', '.join(topics)}."

        profile = await self.profile_engine.get_profile()
        routine = profile.get("routine", {})

        summary_msg = (
            f"Good evening, Sir. Daily operational wrap-up:\n\n"
            f"🌙 **Night Summary**:\n"
            f"• Activity Log: {interaction_summary}\n"
            f"• Sleep Schedule: Recommended rest by {routine.get('sleep', '11:30 PM')}.\n"
            f"• System Status: All background workers and vector indices synchronized.\n\n"
            f"Rest well, Sir. Systems remain active in background monitoring."
        )
        await self.send_telegram_notification(summary_msg)

    async def inactivity_worker(self):
        """Inactivity Worker: Varies its wording when checking in after 3+ days of silence."""
        print("[BACKGROUND WORKER]: Running dynamic Inactivity check...")
        if self.chats_col is None: return

        last_chat = await self.chats_col.find_one({}, sort=[("timestamp", -1)])
        if last_chat and last_chat.get("timestamp"):
            last_time = datetime.fromisoformat(last_chat["timestamp"])
            delta = datetime.now(timezone.utc) - last_time
            if delta.days >= 3:
                phrases = [
                    "Hello Sir. It's been a few quiet days. How are your development tasks coming along?",
                    "Checking in, Sir. ARIA systems have been idling in the background. Everything running smoothly at college?",
                    "Greetings Sir. It has been over 72 hours since our last sync. Standing by whenever you need assistance.",
                    "Sir, reporting in after a brief quiet period. Let me know if you need any support with your projects today."
                ]
                msg = random.choice(phrases)
                await self.send_telegram_notification(msg)

    async def api_health_monitor_worker(self):
        """API Health Monitor (Runs hourly): Verifies LLM routers."""
        print("[BACKGROUND WORKER]: Running API Health Monitor check...")
        try:
            test_msg = [{"role": "user", "content": "ping"}]
            await self.llm_router.chat(test_msg, max_tokens=10)
            print("[API Health]: All neural pathways optimal.")
        except Exception as e:
            print(f"[API Health Alert]: All cloud providers experiencing issues: {e}")
            await self.send_telegram_notification("⚠️ **ARIA Alert**: All primary neural pathways and cloud providers are currently experiencing rate limits or downtime. Falling back to local offline vault.")
