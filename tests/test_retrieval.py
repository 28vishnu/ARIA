import pytest
from unittest.mock import AsyncMock, MagicMock
from brain.models.request import BrainRequest
from brain.retrieval import RetrievalEngine

@pytest.mark.asyncio
async def test_query_normalization():
    engine = RetrievalEngine(None, None, None)
    assert engine._normalize_query("  Italy   Plan! ") == "italy plan"

@pytest.mark.asyncio
async def test_retrieval_partial_failure():
    chroma_repo = MagicMock()
    chroma_repo.docs = None
    mongo_repo = MagicMock()
    mongo_repo.profile.find_one = AsyncMock(side_effect=Exception("Mongo Timeout"))
    mongo_repo.graph = None

    cache_mgr = MagicMock()
    cache_mgr.get.return_value = None

    engine = RetrievalEngine(chroma_repo, mongo_repo, cache_mgr)
    req = BrainRequest(query="Where is my Italy plan?", intent="general")
    
    res = await engine.parallel_search(req)
    assert res["has_results"] is False
    assert "timings" in res
