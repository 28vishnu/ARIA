import asyncio
from unittest.mock import patch

from brain.tools.search_tool import SearchTool


def test_wikipedia_fallback_works_without_tavily(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("ARIA_DISABLE_WIKIPEDIA_FALLBACK", raising=False)
    tool = SearchTool()
    payload = {"results": [{"title": "Photosynthesis", "url": "https://en.wikipedia.org/wiki/Photosynthesis", "snippet": "Plants make food."}]}
    with patch.object(tool, "_wikipedia_search", return_value=payload):
        result = asyncio.run(tool.execute("photosynthesis"))
    assert result["success"] is True
    assert result["provider"] == "wikipedia"
    assert result["count"] == 1
    assert result["results"][0]["url"].startswith("https://")
    assert "not a dedicated live-news source" in result["warning"]


def test_empty_query_does_not_call_provider():
    tool = SearchTool()
    result = asyncio.run(tool.execute("  "))
    assert result["success"] is False
    assert result["error"] == "Search query is empty."


def test_results_are_deduplicated_and_bounded():
    tool = SearchTool(max_results=2)
    normalized = tool._normalize_results({"results": [
        {"title": "A", "url": "https://example.com/a", "snippet": "first"},
        {"title": "A duplicate", "url": "https://example.com/a", "snippet": "duplicate"},
        {"title": "B", "url": "https://example.com/b", "snippet": "second"},
        {"title": "C", "url": "https://example.com/c", "snippet": "third"},
    ]})
    assert len(normalized) == 2
    assert [item["title"] for item in normalized] == ["A", "B"]


def test_wikipedia_snippet_html_is_removed():
    assert SearchTool._strip_html("plant <span class='searchmatch'>growth</span> &amp; energy") == "plant growth & energy"
