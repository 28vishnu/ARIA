import asyncio
from unittest.mock import patch

from brain.tools.search_tool import SearchTool


def test_time_sensitive_queries_use_shorter_cache_ttl(monkeypatch):
    monkeypatch.setenv("ARIA_SEARCH_CACHE_TTL", "120")
    monkeypatch.setenv("ARIA_CURRENT_SEARCH_CACHE_TTL", "0")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("ARIA_DISABLE_WIKIPEDIA_FALLBACK", raising=False)
    tool = SearchTool()
    payload = {"results": [{"title": "News", "url": "https://example.org/news", "snippet": "A current news result."}]}
    with patch.object(tool, "_wikipedia_search", return_value=payload) as search:
        asyncio.run(tool.execute("latest news"))
        asyncio.run(tool.execute("latest news"))
    assert search.call_count == 2


def test_general_queries_keep_normal_cache(monkeypatch):
    monkeypatch.setenv("ARIA_SEARCH_CACHE_TTL", "120")
    monkeypatch.setenv("ARIA_CURRENT_SEARCH_CACHE_TTL", "10")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("ARIA_DISABLE_WIKIPEDIA_FALLBACK", raising=False)
    tool = SearchTool()
    payload = {"results": [{"title": "Photosynthesis", "url": "https://example.org/plant", "snippet": "Plants use light to make food."}]}
    with patch.object(tool, "_wikipedia_search", return_value=payload) as search:
        asyncio.run(tool.execute("photosynthesis"))
        second = asyncio.run(tool.execute("photosynthesis"))
    assert second.get("cached") is True
    assert search.call_count == 1


def test_normalization_preserves_publication_date():
    tool = SearchTool()
    results = tool._normalize_results({"results": [{
        "title": "Release", "url": "https://example.org/release", "content": "Release details", "published_date": "2026-10-21"
    }]})
    assert results[0]["published_date"] == "2026-10-21"


def test_tavily_rate_limit_falls_back(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.delenv("ARIA_DISABLE_WIKIPEDIA_FALLBACK", raising=False)
    tool = SearchTool()
    class FakeClient:
        def search(self, **kwargs):
            raise RuntimeError("HTTP 429 rate limit exceeded")
    tool._client = FakeClient()
    payload = {"results": [{"title": "Topic", "url": "https://en.wikipedia.org/wiki/Topic", "snippet": "Background information."}]}
    with patch.object(tool, "_wikipedia_search", return_value=payload):
        result = asyncio.run(tool.execute("topic"))
    assert result["success"] is True
    assert result["provider"] == "wikipedia"
    assert "warning" in result


def test_success_has_search_timestamp():
    tool = SearchTool()
    result = tool._success("query", [{"title": "A", "url": "https://example.org", "snippet": "text"}], "test", 0.0)
    assert result["searched_at"].endswith("+00:00")
