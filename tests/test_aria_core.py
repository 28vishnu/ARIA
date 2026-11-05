import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from brain.models.request import BrainRequest
from brain.retrieval import RetrievalEngine

# -------------------------------------------------------------
# PHASE 1 REGRESSION TEST SUITE
# -------------------------------------------------------------

@pytest.mark.asyncio
async def test_router_greetings():
    """Test Step 1: Fast router handles greetings instantly without tracebacks."""
    from main import GreetingHandler
    handler = GreetingHandler()
    assert handler.can_handle("Hi") is True
    assert handler.can_handle("Hello ARIA") is True

@pytest.mark.asyncio
async def test_profile_lookup():
    """Test Step 1 & 6: Profile requests resolve correctly from RAM / Mongo."""
    mock_mongo = MagicMock()
    mock_mongo.profile.find_one = AsyncMock(return_value={"name": "Saketh", "college": "GVP"})
    
    profile = await mock_mongo.profile.find_one({"_id": "master_profile"})
    assert profile["name"] == "Saketh"

@pytest.mark.asyncio
async def test_retrieval_partial_failure():
    """Test Step 3: Retrieval handles component failure gracefully without crashing."""
    chroma_repo = MagicMock()
    chroma_repo.docs = None # Simulated offline Chroma
    mongo_repo = MagicMock()
    mongo_repo.profile.find_one = AsyncMock(side_effect=Exception("Mongo Timeout"))
    mongo_repo.graph = None

    cache_mgr = MagicMock()
    cache_mgr.get.return_value = None

    engine = RetrievalEngine(chroma_repo, mongo_repo, cache_mgr)
    req = BrainRequest(query="Where is my Italy plan?", intent="general")
    
    # Should complete without throwing an unhandled exception
    res = await engine.parallel_search(req)
    assert res["has_results"] is False
    assert "timings" in res

@pytest.mark.asyncio
async def test_query_normalization():
    """Test Step 4: Query normalization for cache hits."""
    engine = RetrievalEngine(None, None, None)
    assert engine._normalize_query("  Italy   Plan! ") == "italy plan"

@pytest.mark.asyncio
async def test_schedule_collection_is_none_check():
    """Test Step 5: Explicit is None checks on MongoDB collections."""
    from tool_manager import ToolManager
    tm = ToolManager(None, None, None, None, None, None)
    # schedule_col is explicitly None, should return graceful error dict instead of throwing
    res = await tm._handle_schedule("What is today's schedule?")
    assert res["success"] is False
    assert "offline" in res["content"]
  
