"""Regression tests for bounded hosted-model provider usage."""
from types import SimpleNamespace
import asyncio

from brain.llm.llm_router import LLMRouter


def make_router(monkeypatch, cap="2", strict="0"):
    monkeypatch.setenv("ARIA_STRICT_NO_LLM", strict)
    monkeypatch.setenv("ARIA_LLM_MAX_PROVIDERS_PER_REQUEST", cap)
    monkeypatch.setenv("ARIA_LLM_CACHE_TTL_SECONDS", "300")
    config = SimpleNamespace(
        groq_api_key="groq-test",
        gemini_api_key="gemini-test",
        openrouter_api_key="openrouter-test",
        mistral_api_key="mistral-test",
        timeout_seconds=1,
    )
    return LLMRouter(config)


def test_provider_attempt_budget_limits_fanout(monkeypatch):
    router = make_router(monkeypatch, "2")
    calls = []

    async def fail(*args, **kwargs):
        calls.append("called")
        raise RuntimeError("simulated provider failure")

    async def unexpected(*args, **kwargs):
        calls.append("third-provider-called")
        return "should not be reached"

    router._groq_chat = fail
    router._gemini_chat = fail
    router._openrouter_chat = unexpected
    router._mistral_chat = unexpected

    result = asyncio.run(router.chat(
        [{"role": "user", "content": "Help me reason through a complex task."}],
        task="general",
        context={"llm_required": True},
    ))

    assert result is None
    assert len(calls) == 2
    assert "third-provider-called" not in calls


def test_strict_no_llm_still_blocks_all_provider_calls(monkeypatch):
    monkeypatch.setenv("ARIA_STRICT_NO_LLM", "1")
    router = make_router(monkeypatch, "4", strict="1")
    calls = []

    async def unexpected(*args, **kwargs):
        calls.append(True)
        return "should not be reached"

    router._groq_chat = unexpected
    result = asyncio.run(router.chat(
        [{"role": "user", "content": "Hello"}],
        context={"llm_required": True},
    ))

    assert result is None
    assert calls == []


def test_provider_cap_is_clamped(monkeypatch):
    router = make_router(monkeypatch, "99")
    assert router._max_providers_per_request == 4
    router = make_router(monkeypatch, "invalid")
    assert router._max_providers_per_request == 2
