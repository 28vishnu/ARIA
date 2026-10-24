import asyncio
import time

import pytest

from autonomy.proactive_agent import ProactiveTaskStore, ProactiveAgent


def test_one_shot_task_persists_and_completes(tmp_path):
    db = tmp_path / "tasks.sqlite3"
    store = ProactiveTaskStore(db)
    task_id = store.schedule_once("reminder", time.time() - 1, {"x": 1})
    # Reopen to prove the task isn't only in process memory.
    store = ProactiveTaskStore(db)
    seen = []

    async def handler(task):
        seen.append(task["payload"]["x"])
        return "reminded"

    async def notifier(message, task):
        seen.append(message)

    result = asyncio.run(store.run_due(handler, notifier))
    item = next(t for t in store.list_tasks(include_disabled=True) if t["id"] == task_id)
    assert result == {"claimed": 1, "succeeded": 1, "failed": 0}
    assert seen == [1, "reminded"]
    assert item["status"] == "completed"
    assert item["enabled"] is False


def test_failed_one_shot_records_failure_and_does_not_claim_delivery(tmp_path):
    store = ProactiveTaskStore(tmp_path / "tasks.sqlite3")
    task_id = store.schedule_once("fails", time.time() - 1)

    async def handler(task):
        raise RuntimeError("test failure")

    result = asyncio.run(store.run_due(handler))
    item = next(t for t in store.list_tasks(include_disabled=True) if t["id"] == task_id)
    assert result["failed"] == 1
    assert item["status"] == "failed"
    assert item["failure_count"] == 1
    assert "test failure" in item["last_error"]


def test_interval_schedule_validation(tmp_path):
    store = ProactiveTaskStore(tmp_path / "tasks.sqlite3")
    with pytest.raises(ValueError):
        store.schedule_interval("too fast", time.time(), 10)


def test_cancel_disables_task(tmp_path):
    store = ProactiveTaskStore(tmp_path / "tasks.sqlite3")
    task_id = store.schedule_once("cancel me", time.time() + 3600)
    assert store.cancel(task_id) is True
    assert store.cancel(task_id) is False
    item = next(t for t in store.list_tasks(include_disabled=True) if t["id"] == task_id)
    assert item["status"] == "cancelled"
    assert not item["enabled"]


def test_interval_task_is_rescheduled_without_catchup_burst(tmp_path):
    store = ProactiveTaskStore(tmp_path / "tasks.sqlite3")
    task_id = store.schedule_interval("poll", 100, 60)

    async def handler(task):
        return None

    result = asyncio.run(store.run_due(handler, now=1000))
    item = next(t for t in store.list_tasks(include_disabled=True) if t["id"] == task_id)
    assert result["succeeded"] == 1
    assert item["status"] == "scheduled"
    assert item["due_at"] >= 1060
    assert item["enabled"]


def test_invalid_payload_rejected(tmp_path):
    store = ProactiveTaskStore(tmp_path / "tasks.sqlite3")
    with pytest.raises(ValueError):
        store.schedule_once("bad", time.time(), {"bad": object()})


def test_agent_stops_cleanly(tmp_path):
    store = ProactiveTaskStore(tmp_path / "tasks.sqlite3")

    async def handler(task):
        return None

    async def scenario():
        agent = ProactiveAgent(store, handler, poll_interval_seconds=1)
        task = asyncio.create_task(agent.run())
        await asyncio.sleep(0.02)
        agent.stop()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())


def test_stale_running_task_is_recovered_after_worker_crash(tmp_path):
    db = tmp_path / "tasks.sqlite3"
    store = ProactiveTaskStore(db, task_lease_seconds=60)
    task_id = store.schedule_once("recover me", 100, {"value": "ok"})
    with store._connect() as conn:
        conn.execute(
            "UPDATE proactive_tasks SET status='running', updated_at=? WHERE id=?",
            (100, task_id),
        )

    seen = []

    async def handler(task):
        seen.append(task["payload"]["value"])
        return "recovered"

    result = asyncio.run(store.run_due(handler, now=200))
    item = next(t for t in store.list_tasks(include_disabled=True) if t["id"] == task_id)
    assert result == {"claimed": 1, "succeeded": 1, "failed": 0}
    assert seen == ["ok"]
    assert item["status"] == "completed"


def test_cancellation_during_execution_is_not_overwritten_by_completion(tmp_path):
    store = ProactiveTaskStore(tmp_path / "tasks.sqlite3")
    task_id = store.schedule_once("cancel during run", time.time() - 1)

    async def handler(task):
        assert store.cancel(task["id"]) is True
        return "handler completed"

    result = asyncio.run(store.run_due(handler))
    item = next(t for t in store.list_tasks(include_disabled=True) if t["id"] == task_id)
    assert result == {"claimed": 1, "succeeded": 1, "failed": 0}
    assert item["status"] == "cancelled"
    assert item["enabled"] is False


def test_task_lease_must_be_positive(tmp_path):
    with pytest.raises(ValueError, match="task_lease_seconds"):
        ProactiveTaskStore(tmp_path / "tasks.sqlite3", task_lease_seconds=0)



def test_error_messages_redact_common_credentials():
    from autonomy.proactive_agent import _safe_error_message

    message = _safe_error_message(RuntimeError(
        "token=abc123 password:secret123 "
        "mongodb://admin:supersecret@host/db "
        "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef "
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    ))
    assert "abc123" not in message
    assert "secret123" not in message
    assert "supersecret" not in message
    assert "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef" not in message
    assert "ghp_abcdefghijklmnopqrstuvwxyz1234567890" not in message
    assert "[REDACTED]" in message
