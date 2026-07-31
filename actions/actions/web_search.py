import os
import logging
from typing import Dict, Any

from tavily import TavilyClient

from actions.base import BaseAction, ActionResult

logger = logging.getLogger("aria")

class WebSearchAction(BaseAction):
    """
    Read-only internet search action for ARIA.

    Uses Tavily to retrieve current web information.  
    This action is considered safe because it does not modify  
    files, databases, accounts, or external systems.  
    """  

    name = "web_search_action"  

    description = (  
        "Searches the live web for current information and returns "  
        "relevant results including titles, URLs, and extracted content."  
    )  

    permission_level = "safe"  

    timeout_seconds = 30  

    async def validate(  
        self,  
        params: Dict[str, Any]  
    ) -> bool:  

        query = str(  
            params.get("query", "")  
        ).strip()  

        if not query:  
            return False  

        if len(query) > 1000:  
            return False  

        max_results = params.get(  
            "max_results",  
            5  
        )  

        try:  
            max_results = int(max_results)  
        except (TypeError, ValueError):  
            return False  

        if max_results < 1 or max_results > 10:  
            return False  

        return True  

    async def execute(  
        self,  
        params: Dict[str, Any]  
    ) -> ActionResult:  

        query = str(  
            params.get("query", "")  
        ).strip()  

        max_results = int(  
            params.get("max_results", 5)  
        )  

        api_key = os.getenv("TAVILY_API_KEY")  

        if not api_key:  
            return ActionResult(  
                success=False,  
                action_name=self.name,  
                error="TAVILY_API_KEY is not configured."  
            )  

        try:  

            client = TavilyClient(  
                api_key=api_key  
            )  

            response = client.search(  
                query=query,  
                search_depth="advanced",  
                max_results=max_results,  
                include_answer=False,  
                include_raw_content=False,  
            )  

            raw_results = response.get(  
                "results",  
                []  
            )  

            results = []  

            for item in raw_results:  

                results.append(  
                    {  
                        "title": item.get(  
                            "title",  
                            ""  
                        ),  
                        "url": item.get(  
                            "url",  
                            ""  
                        ),  
                        "content": item.get(  
                            "content",  
                            ""  
                        ),  
                        "score": item.get(  
                            "score"  
                        ),  
                    }  
                )  

            logger.info(  
                "[WebSearchAction] Search completed. "  
                "query=%r results=%d",  
                query,  
                len(results),  
            )  

            # Build a human/LLM-readable representation of the results.
            content_parts = []

            for index, item in enumerate(results, start=1):
                title = item.get("title", "").strip()
                url = item.get("url", "").strip()
                text = item.get("content", "").strip()

                content_parts.append(
                    f"{index}. {title}\n"
                    f"URL: {url}\n"
                    f"{text}"
                )

            content = "\n\n".join(content_parts)

            return ActionResult(
                success=True,
                action_name=self.name,
                data={
                    # Standardized text output for downstream tasks.
                    "content": content,

                    # Structured output for agents and advanced workflows.
                    "query": query,
                    "results": results,
                    "result_count": len(results),
                }
            )  

        except Exception as exc:  

            logger.exception(  
                "[WebSearchAction] Search failed."  
            )  

            return ActionResult(  
                success=False,  
                action_name=self.name,  
                error=str(exc)  
            )
