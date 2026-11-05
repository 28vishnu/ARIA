from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse

import main


class FakeRegistry:
    def __init__(self, queue):
        self.queue = queue

    def has(self, name):
        return name == "durable_job_queue"

    def get(self, name):
        if name != "durable_job_queue":
            raise KeyError(name)
        return self.queue


class FakeDurableQueue:
    available = True

    def __init__(self, fail=False, duplicate=False):
        self.calls = []
        self.fail = fail
        self.duplicate = duplicate
        self.collection = self

    async def enqueue(self, handler, payload, *, job_id=None):
        self.calls.append((handler, payload, job_id))
        if self.fail:
            raise RuntimeError("simulated storage outage")

    async def find_one(self, query):
        return {"_id": query["_id"]} if self.duplicate else None


class FakeRequest:
    headers = {}

    def __init__(self, registry, data):
        self.app = SimpleNamespace(state=SimpleNamespace(registry=registry))
        self._data = data

    async def json(self):
        return self._data


def _update():
    return {
        "update_id": 7654321,
        "message": {
            "chat": {"id": 12345},
            "from": {"id": 12345},
            "text": "hello ARIA",
        },
    }


@pytest.mark.asyncio
async def test_authorized_telegram_update_is_persisted_before_ack(monkeypatch):
    queue = FakeDurableQueue()
    monkeypatch.setattr(main, "claim_telegram_update", lambda _update_id: _return_true())
    monkeypatch.setattr(main, "_mark_knowledge_activity", lambda: None)
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_ID", "12345")

    result = await main.telegram_webhook(FakeRequest(FakeRegistry(queue), _update()))

    assert result == {"status": "accepted", "update_id": 7654321}
    assert len(queue.calls) == 1
    handler, payload, job_id = queue.calls[0]
    assert handler == "telegram_update"
    assert payload["data"]["update_id"] == 7654321
    assert job_id == "telegram-update-7654321"


async def _return_true():
    return True


@pytest.mark.asyncio
async def test_storage_outage_returns_retryable_503(monkeypatch):
    queue = FakeDurableQueue(fail=True)
    monkeypatch.setattr(main, "claim_telegram_update", lambda _update_id: _return_true())
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_ID", "12345")

    result = await main.telegram_webhook(FakeRequest(FakeRegistry(queue), _update()))

    assert isinstance(result, JSONResponse)
    assert result.status_code == 503


@pytest.mark.asyncio
async def test_duplicate_persisted_telegram_update_is_acknowledged_without_requeue(monkeypatch):
    queue = FakeDurableQueue(fail=True, duplicate=True)
    monkeypatch.setattr(main, "claim_telegram_update", lambda _update_id: _return_true())
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_ID", "12345")

    result = await main.telegram_webhook(FakeRequest(FakeRegistry(queue), _update()))

    assert result == {"status": "duplicate_ignored", "update_id": 7654321}
