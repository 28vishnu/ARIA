import asyncio
from datetime import datetime, timezone

import pytest

from autonomy.durable_job_queue import DurableJobQueue


class FakeUpdateResult:
    def __init__(self, modified_count=0):
        self.modified_count = modified_count


class FakeCollection:
    """Small async Mongo-like fake that retains documents across queue instances."""
    def __init__(self):
        self.docs = {}

    async def insert_one(self, document):
        if document["_id"] in self.docs:
            raise ValueError("duplicate key")
        self.docs[document["_id"]] = dict(document)
        return type("InsertResult", (), {"inserted_id": document["_id"]})()

    async def find_one(self, query):
        return self.docs.get(query.get("_id"))

    async def find_one_and_update(self, query, update, *, sort=None, return_document=None):
        now = datetime.now(timezone.utc)
        candidates = []
        for doc in self.docs.values():
            if doc.get("attempts", 0) >= query["attempts"]["$lt"]:
                continue
            pending = doc.get("status") == "pending"
            running_expired = doc.get("status") == "running" and doc.get("lease_until") and doc["lease_until"] < now
            if pending or running_expired:
                candidates.append(doc)
        if not candidates:
            return None
        doc = sorted(candidates, key=lambda item: item["created_at"])[0]
        doc.update(update["$set"])
        doc["attempts"] += update["$inc"]["attempts"]
        return dict(doc)

    async def update_one(self, query, update):
        doc = self.docs.get(query["_id"])
        if doc and ("status" not in query or doc.get("status") == query["status"]):
            doc.update(update["$set"])
            return FakeUpdateResult(1)
        return FakeUpdateResult(0)

    async def update_many(self, query, update):
        changed = 0
        for doc in self.docs.values():
            if doc.get("status") == "running" and doc.get("lease_until") and doc["lease_until"] < datetime.now(timezone.utc) and doc.get("attempts", 0) < query["attempts"]["$lt"]:
                doc.update(update["$set"])
                changed += 1
        return FakeUpdateResult(changed)

    async def count_documents(self, query):
        return sum(1 for doc in self.docs.values() if doc.get("status") == query["status"])


@pytest.mark.asyncio
async def test_durable_job_completes_and_survives_queue_recreation():
    collection = FakeCollection()
    first = DurableJobQueue(collection)
    calls = []

    async def handler(payload):
        calls.append(payload["value"])
        return "ok"

    first.register_handler("test_handler", handler)
    job_id = await first.enqueue("test_handler", {"value": 7}, job_id="stable-job")
    assert job_id == "stable-job"

    # A new queue object sees the same persisted job, as it would after restart.
    restarted = DurableJobQueue(collection)
    restarted.register_handler("test_handler", handler)
    result = await restarted.run_one()

    assert result == {"id": "stable-job", "status": "completed"}
    assert calls == [7]
    assert collection.docs[job_id]["status"] == "completed"
    assert await restarted.run_one() is None


@pytest.mark.asyncio
async def test_durable_job_retries_then_marks_exhausted_job_failed():
    collection = FakeCollection()
    queue = DurableJobQueue(collection, max_attempts=2)

    async def broken(_payload):
        raise RuntimeError("controlled failure")

    queue.register_handler("broken", broken)
    await queue.enqueue("broken", {}, job_id="broken-job")

    first = await queue.run_one()
    second = await queue.run_one()

    assert first["status"] == "pending"
    assert second["status"] == "failed"
    assert collection.docs["broken-job"]["attempts"] == 2
    assert "controlled failure" in collection.docs["broken-job"]["last_error"]


@pytest.mark.asyncio
async def test_durable_queue_requires_mongo_storage_and_registered_handler():
    queue = DurableJobQueue()
    assert (await queue.status())["durable"] is False
    with pytest.raises(RuntimeError, match="MongoDB"):
        await queue.enqueue("missing", {})

    queue = DurableJobQueue(FakeCollection())
    with pytest.raises(ValueError, match="No handler"):
        await queue.enqueue("missing", {})
