import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("aria")


class AutomationWatchers:
    """
    Real-world monitoring utilities for ARIA.

    Watchers are intentionally read-only. They collect external state,
    normalize it, and optionally notify the configured Telegram user.
    """

    def __init__(
        self,
        tavily_client=None,
        telegram_token: Optional[str] = None,
        admin_chat_id: Optional[str] = None,
        search_tool=None,
        http_timeout: float = 15.0,
    ):
        self.tavily = tavily_client
        self.search_tool = search_tool
        self.token = telegram_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.admin_chat_id = admin_chat_id or os.getenv("ADMIN_CHAT_ID")
        self.http_timeout = max(3.0, float(http_timeout))

    async def notify_user(self, message: str) -> bool:
        """Send a Telegram notification and return whether it succeeded."""
        if not self.token or not self.admin_chat_id:
            logger.warning(
                "[AutomationWatchers] Telegram notification is not configured."
            )
            return False

        message = str(message or "").strip()
        if not message:
            return False

        try:
            async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={
                        "chat_id": self.admin_chat_id,
                        "text": message[:4096],
                    },
                )
                response.raise_for_status()

            return True

        except Exception:
            logger.exception(
                "[AutomationWatchers] Telegram notification failed."
            )
            return False

    async def check_github_activity(
        self,
        repo_owner: str,
        repo_name: str,
        max_commits: int = 5,
    ) -> Optional[Dict[str, Any]]:
        """
        Check recent GitHub commits.

        Returns structured data so schedulers/watchers can compare the
        latest state instead of relying on formatted text.
        """
        owner = str(repo_owner or "").strip()
        name = str(repo_name or "").strip()

        if not owner or not name:
            return None

        max_commits = max(1, min(int(max_commits), 10))
        url = f"https://api.github.com/repos/{owner}/{name}/commits"

        try:
            async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                response = await client.get(
                    url,
                    params={"per_page": max_commits},
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "ARIA-AI",
                    },
                )

                if response.status_code != 200:
                    logger.warning(
                        "[GitHub Watcher] HTTP %s for %s/%s",
                        response.status_code,
                        owner,
                        name,
                    )
                    return None

                payload = response.json()

            if not isinstance(payload, list) or not payload:
                return {
                    "success": True,
                    "source": "github",
                    "repository": f"{owner}/{name}",
                    "commits": [],
                    "latest": None,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }

            commits = []

            for item in payload:
                if not isinstance(item, dict):
                    continue

                commit = item.get("commit") or {}
                author = commit.get("author") or {}

                commits.append(
                    {
                        "sha": item.get("sha"),
                        "message": str(
                            commit.get("message") or ""
                        ).strip(),
                        "author": str(
                            author.get("name") or ""
                        ).strip(),
                        "timestamp": author.get("date"),
                        "url": item.get("html_url"),
                    }
                )

            latest = commits[0] if commits else None

            return {
                "success": True,
                "source": "github",
                "repository": f"{owner}/{name}",
                "commits": commits,
                "latest": latest,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception:
            logger.exception(
                "[GitHub Watcher] Check failed for %s/%s",
                owner,
                name,
            )
            return None

    async def watch_tech_news(
        self,
        query: str = "latest breakthroughs in artificial intelligence",
        max_results: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch current technology news through the shared SearchTool when
        available, with compatibility support for an older Tavily client.
        """
        query = str(query or "").strip()
        if not query:
            return None

        max_results = max(1, min(int(max_results), 10))

        try:
            if self.search_tool is not None:
                result = await self.search_tool.execute(
                    query=query,
                    context={"search_depth": "advanced"},
                )

                if not result.get("success"):
                    logger.warning(
                        "[News Watcher] SearchTool failed: %s",
                        result.get("error"),
                    )
                    return None

                return {
                    "success": True,
                    "source": "web_search",
                    "query": query,
                    "results": result.get("results", [])[:max_results],
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }

            if self.tavily:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.tavily.search,
                        query=query,
                        max_results=max_results,
                    ),
                    timeout=self.http_timeout,
                )

                raw_results = (
                    response.get("results", [])
                    if isinstance(response, dict)
                    else []
                )

                results = [
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get(
                            "content",
                            item.get("snippet", ""),
                        ),
                        "score": item.get("score"),
                    }
                    for item in raw_results
                    if isinstance(item, dict)
                ]

                return {
                    "success": True,
                    "source": "tavily",
                    "query": query,
                    "results": results,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }

            logger.warning(
                "[News Watcher] No web-search provider is configured."
            )
            return None

        except asyncio.TimeoutError:
            logger.warning("[News Watcher] Search timed out.")
            return None

        except Exception:
            logger.exception("[News Watcher] News check failed.")
            return None

    async def get_news_summary(
        self,
        query: str = "latest artificial intelligence technology news",
        max_results: int = 3,
    ) -> Optional[str]:
        """Return a compact human-readable news notification."""
        result = await self.watch_tech_news(
            query=query,
            max_results=max_results,
        )

        if not result or not result.get("success"):
            return None

        results = result.get("results", [])
        if not results:
            return None

        lines = ["📰 ARIA Tech Intelligence Update"]

        for index, item in enumerate(results, start=1):
            title = str(item.get("title") or "Untitled").strip()
            snippet = str(
                item.get("snippet")
                or item.get("content")
                or ""
            ).strip()

            if len(snippet) > 300:
                snippet = snippet[:300].rstrip() + "..."

            lines.append(f"\n{index}. {title}")

            if snippet:
                lines.append(snippet)

            url = str(item.get("url") or "").strip()
            if url:
                lines.append(url)

        return "\n".join(lines)

    async def notify_news(
        self,
        query: str = "latest artificial intelligence technology news",
        max_results: int = 3,
    ) -> bool:
        """Check news and notify the configured Telegram user."""
        summary = await self.get_news_summary(
            query=query,
            max_results=max_results,
        )

        if not summary:
            return False

        return await self.notify_user(summary)
