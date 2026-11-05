"""Offline tests for the authorized Telegram webhook handoff.

These tests do not contact Telegram, initialize the production registry,
or execute background message processing.
"""

from fastapi.testclient import TestClient

import main


def _payload(update_id: int, user_id: int = 424242) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": user_id},
            "from": {"id": user_id},
            "text": "What is Python?",
        },
    }


def _reset_update_cache(monkeypatch, update_id: int) -> None:
    # The production cache is process-global; remove only this test's key.
    monkeypatch.setitem(main._telegram_update_cache, update_id, -1e12)


def test_authorized_webhook_acknowledges_and_schedules_once(monkeypatch):
    update_id = 987650001
    _reset_update_cache(monkeypatch, update_id)
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_ID", "424242")
    monkeypatch.setattr(main, "_mark_knowledge_activity", lambda: None)

    scheduled = []

    def capture_schedule(coro):
        scheduled.append(coro)
        # Do not execute processing in this offline webhook test.
        coro.close()
        return object()

    monkeypatch.setattr(main.background_manager, "schedule", capture_schedule)

    response = TestClient(main.app).post(
        "/telegram-webhook", json=_payload(update_id)
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "update_id": update_id}
    assert len(scheduled) == 1


def test_duplicate_authorized_update_is_not_scheduled_twice(monkeypatch):
    update_id = 987650002
    _reset_update_cache(monkeypatch, update_id)
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_ID", "424242")
    monkeypatch.setattr(main, "_mark_knowledge_activity", lambda: None)

    scheduled = []

    def capture_schedule(coro):
        scheduled.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr(main.background_manager, "schedule", capture_schedule)
    client = TestClient(main.app)

    first = client.post("/telegram-webhook", json=_payload(update_id))
    second = client.post("/telegram-webhook", json=_payload(update_id))

    assert first.json() == {"status": "accepted", "update_id": update_id}
    assert second.json() == {
        "status": "duplicate_ignored",
        "update_id": update_id,
    }
    assert len(scheduled) == 1


def test_unauthorized_user_never_schedules_processing(monkeypatch):
    update_id = 987650003
    _reset_update_cache(monkeypatch, update_id)
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_ID", "424242")
    scheduled = []
    monkeypatch.setattr(
        main.background_manager,
        "schedule",
        lambda coro: (scheduled.append(coro), coro.close()),
    )

    response = TestClient(main.app).post(
        "/telegram-webhook", json=_payload(update_id, user_id=777777)
    )

    assert response.status_code == 200
    assert response.json() == {"status": "unauthorized"}
    assert scheduled == []
