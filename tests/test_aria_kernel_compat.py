import pytest
from unittest.mock import AsyncMock, MagicMock

from brain.brain import AriaBrain, CorrectionStore
from brain.models.request import BrainRequest


@pytest.mark.asyncio
async def test_correction_store_normalizes_query_and_returns_correction():
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value={"correction": "Correct answer"})
    db = MagicMock()
    db.__getitem__.return_value = collection

    store = CorrectionStore(db)
    result = await store.check_correction("  TEST   Query ")

    assert result == "Correct answer"
    collection.find_one.assert_awaited_once_with({"query_key": "test query"})


@pytest.mark.asyncio
async def test_correction_store_persists_feedback():
    collection = MagicMock()
    collection.update_one = AsyncMock()
    db = MagicMock()
    db.__getitem__.return_value = collection

    store = CorrectionStore(db)
    result = await store.record_correction("Test query", "wrong", "right")

    assert result["success"] is True
    collection.update_one.assert_awaited_once_with(
        {"query_key": "test query"},
        {"$set": {
            "query_key": "test query",
            "query": "Test query",
            "wrong_answer": "wrong",
            "correction": "right",
        }},
        upsert=True,
    )


@pytest.mark.asyncio
async def test_aria_brain_handles_sync_mock_database_without_constructor_error():
    brain = AriaBrain(MagicMock(), MagicMock())
    brain.learning.check_correction = AsyncMock(return_value=None)
    brain.retrieval.parallel_search = AsyncMock(return_value={"has_results": False})

    result = await brain.search(BrainRequest(query="Test query", intent="general"))
    assert result["confidence"] == 0.0
