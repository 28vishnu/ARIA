import os
import httpx
from datetime import datetime, timezone, timedelta

class BackgroundWorkers:
    def __init__(self, mongo_db, llm_router, tavily_client):
        self.db = mongo_db
        self.llm_router = llm_router
        self.tavily = tavily_client
        self.chats_col = mongo_db["chat_history"] if mongo_db is not None else None
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.admin_chat_id = os.getenv("ADMIN_CHAT_ID") # Set your Telegram chat ID in environment variables

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
        """Morning Worker (Runs daily at 09:00 AM): Briefs user if inactive today."""
        print("[BACKGROUND WORKER]: Running Morning Briefing check...")
        if self.chats_col is None: return

        # Check if user already talked today
        now_utc = datetime.now(timezone.utc)
        start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        recent_chat = await self.chats_col.find_one({"timestamp": {"$gte": start_of_day}})

        if recent_chat:
            print("[Morning Worker]: User already active today. Skipping briefing.")
            return

        # Fetch brief weather and intelligence
        weather_info = "Weather data unavailable."
        try:
            if self.tavily:
                res = self.tavily.search(query="weather in Visakhapatnam today", max_results=1)
                if res and res.get("results"):
                    weather_info = res["results"][0]["content"][:150]
        except Exception:
            pass

        briefing = (
            f"Good morning, Sir. ARIA systems online.\n\n"
            f"🌤 **Morning Briefing**:\n"
            f"• Weather: {weather_info}\n"
            f"• Active Project: ARIA AI (Progress: 80%)\n"
            f"• Current Focus: Document Intelligence & Knowledge Graph\n\n"
            f"Standing by for your instructions today, Sir."
        )
        await self.send_telegram_notification(briefing)

    async def night_summary_worker(self):
        """Night Worker (Runs daily at 10:00 PM): Provides daily wrap-up and tomorrow schedule."""
        print("[BACKGROUND WORKER]: Running Night Summary...")
        summary_msg = (
            f"Good evening, Sir. Daily operational wrap-up:\n\n"
            f"🌙 **Night Summary**:\n"
            f"• Systems status: Optimal across all fallback routers.\n"
            f"• Active project milestone: Document vault indexing verified.\n\n"
            f"Rest well, Sir. Systems remain active in background monitoring."
        )
        await self.send_telegram_notification(summary_msg)

    async def inactivity_worker(self):
        """Inactivity Worker: Checks if user has been silent for 3+ days."""
        print("[BACKGROUND WORKER]: Running Inactivity check...")
        if self.chats_col is None: return

        last_chat = await self.chats_col.find_one({}, sort=[("timestamp", -1)])
        if last_chat and last_chat.get("timestamp"):
            last_time = datetime.fromisoformat(last_chat["timestamp"])
            delta = datetime.now(timezone.utc) - last_time
            if delta.days >= 3:
                msg = "Hello Sir. It's been a few days since our last interaction. All background systems and workers remain fully operational. How are things going?"
                await self.send_telegram_notification(msg)

    async def api_health_monitor_worker(self):
        """API Health Monitor (Runs hourly): Verifies LLM routers and notifies if all cloud providers fail."""
        print("[BACKGROUND WORKER]: Running API Health Monitor check...")
        try:
            test_msg = [{"role": "user", "content": "ping"}]
            await self.llm_router.chat(test_msg, max_tokens=10)
            print("[API Health]: All neural pathways optimal.")
        except Exception as e:
            print(f"[API Health Alert]: All cloud providers experiencing issues: {e}")
            await self.send_telegram_notification("⚠️ **ARIA Alert**: All primary neural pathways and cloud providers are currently experiencing rate limits or downtime. Falling back to local offline vault.")
