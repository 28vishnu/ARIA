import os
import httpx

class AutomationWatchers:
    def __init__(self, tavily_client, telegram_token, admin_chat_id):
        self.tavily = tavily_client
        self.token = telegram_token
        self.admin_chat_id = admin_chat_id

    async def notify_user(self, message: str):
        if not self.token or not self.admin_chat_id: return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.admin_chat_id, "text": message}
                )
        except Exception as e:
            print(f"[Automation Watcher Notification Error]: {e}")

    async def check_github_activity(self, repo_owner: str, repo_name: str):
        """Watches GitHub repositories for recent commits or issues."""
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"https://api.github.com/repos/{repo_owner}/{repo_name}/commits", timeout=10.0)
                if res.status_code == 200:
                    commits = res.json()
                    if commits:
                        latest = commits[0]
                        commit_msg = latest['commit']['message']
                        author = latest['commit']['author']['name']
                        return f"GitHub Update on {repo_name}:\nLatest commit by {author}: '{commit_msg}'"
        except Exception as e:
            print(f"[GitHub Watcher Error]: {e}")
        return None

    async def watch_tech_news(self):
        """Fetches breaking AI and technology updates via Tavily."""
        try:
            if self.tavily:
                res = self.tavily.search(query="latest breakthroughs in artificial intelligence 2026", max_results=1)
                if res and res.get("results"):
                    item = res["results"][0]
                    return f"📰 **Tech Intelligence Update**:\n{item['title']}\n{item['content'][:180]}..."
        except Exception as e:
            print(f"[News Watcher Error]: {e}")
        return None
