"""Offline tests for Telegram background processing and answer delivery.

All outbound HTTP calls and cognitive processing are mocked; no Telegram API
requests, live database writes, or real ARIA background jobs are performed.
"""
from types import SimpleNamespace

import pytest

import main


class FakeRegistry:
    def __init__(self, items):
        self.items = items

    def get(self, key, default=None):
        return self.items.get(key, default)

    def has(self, key):
        return key in self.items and self.items[key] is not None


class FakeHTTPClient:
    def __init__(self, *, fail_send=False):
        self.calls = []
        self.fail_send = fail_send

    async def post(self, url, *, json=None, **kwargs):
        self.calls.append((url, json or {}))
        if self.fail_send:
            raise RuntimeError("simulated Telegram API failure")
        return SimpleNamespace(is_success=True, text="ok")


class FakeStatus:
    def __init__(self, **kwargs):
        self.events = []

    async def start(self, message):
        self.events.append(("start", message))

    async def update(self, message):
        self.events.append(("update", message))


class FakeStateManager:
    def __init__(self):
        self.updates = []
        self.turns = []

    def update_state(self, session_id, **kwargs):
        self.updates.append((session_id, kwargs))

    def add_conversation_turn(self, **kwargs):
        self.turns.append(kwargs)


def _request(registry):
    app = SimpleNamespace(state=SimpleNamespace(registry=registry))
    return SimpleNamespace(app=app)


def _message(text="What is Python?"):
    return {
        "update_id": 990001,
        "message": {
            "chat": {"id": 424242},
            "from": {"id": 424242},
            "text": text,
        },
    }


def _common_patches(monkeypatch):
    monkeypatch.setattr(main, "_begin_knowledge_activity", lambda _request_id: None)
    monkeypatch.setattr(main, "_end_knowledge_activity", lambda _request_id: None)
    monkeypatch.setattr(main, "_handle_master_approval_command", _async_none)
    monkeypatch.setattr(main, "_handle_master_architecture_command", _async_none)
    monkeypatch.setattr(main, "_handle_master_requirement_command", _async_none)
    monkeypatch.setattr(main, "_handle_master_development_command", _async_none)
    monkeypatch.setattr(main, "safe_delete_status", _async_none)
    monkeypatch.setattr(main, "TelegramStatus", FakeStatus)
    monkeypatch.setattr(main, "pending_document_actions", {})


async def _async_none(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_background_pipeline_sends_answer_and_saves_turn(monkeypatch):
    _common_patches(monkeypatch)
    http = FakeHTTPClient()
    state = FakeStateManager()
    registry = FakeRegistry({
        "config": SimpleNamespace(telegram_token="test-token"),
        "http_client": http,
        "state_manager": state,
    })

    async def fake_process_task(text, session_id, request_id, app_state):
        assert text == "What is Python?"
        assert session_id == "424242"
        return "Python is a programming language."

    monkeypatch.setattr(main, "process_task", fake_process_task)
    monkeypatch.setattr(main, "format_telegram_response", lambda text, include_sources=False: text)

    result = await main.process_telegram_update(
        _request(registry), _message(), "req-step16-ok"
    )

    assert result == {"status": "ok"}
    sent = [payload for url, payload in http.calls if url.endswith("/sendMessage")]
    assert any(payload.get("text") == "Python is a programming language." for payload in sent)
    assert state.updates and state.updates[-1][1]["last_assistant_response"] == "Python is a programming language."
    assert state.turns and state.turns[-1]["user_message"] == "What is Python?"


@pytest.mark.asyncio
async def test_background_pipeline_reports_cognitive_failure(monkeypatch):
    _common_patches(monkeypatch)
    http = FakeHTTPClient()
    registry = FakeRegistry({
        "config": SimpleNamespace(telegram_token="test-token"),
        "http_client": http,
    })

    async def failing_process_task(*args, **kwargs):
        raise RuntimeError("simulated cognitive failure")

    monkeypatch.setattr(main, "process_task", failing_process_task)

    result = await main.process_telegram_update(
        _request(registry), _message(), "req-step16-failure"
    )

    assert result == {"status": "processing_failed", "request_id": "req-step16-failure"}
    assert any(
        "internal problem" in payload.get("text", "")
        for url, payload in http.calls if url.endswith("/sendMessage")
    )


@pytest.mark.asyncio
async def test_missing_telegram_token_stops_before_http_calls(monkeypatch):
    _common_patches(monkeypatch)
    http = FakeHTTPClient()
    registry = FakeRegistry({
        "config": SimpleNamespace(telegram_token=""),
        "http_client": http,
    })

    result = await main.process_telegram_update(
        _request(registry), _message(), "req-step16-no-token"
    )

    assert result is None
    assert http.calls == []
