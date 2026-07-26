import httpx
import asyncio

class APIHealthMonitor:
    def __init__(self, llm_router, telegram_token, admin_chat_id):
        self.router = llm_router
        self.token = telegram_token
        self.admin_chat_id = admin_chat_id

    async def notify(self, msg: str):
        if not self.token or not self.admin_chat_id: return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.admin_chat_id, "text": msg}
                )
        except Exception as e:
            print(f"[Health Monitor Notification Error]: {e}")

    async def audit_all_pathways(self):
        """Pings all underlying providers in the fallback chain and records failure metrics."""
        print("[API HEALTH MONITOR]: Auditing all cloud neural pathways...")
        test_messages = [{"role": "user", "content": "ping test"}]
        
        for idx, provider in enumerate(self.router.providers):
            provider_name = provider.__class__.__name__
            try:
                await provider.chat(test_messages, max_tokens=5)
                print(f"[Health Monitor]: Provider {provider_name} is HEALTHY.")
            except Exception as e:
                print(f"[Health Monitor WARNING]: Provider {provider_name} failed check: {e}")
