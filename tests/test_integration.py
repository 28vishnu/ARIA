import pytest
from unittest.mock import MagicMock
from brain.brain import AriaBrain
from brain.models.request import BrainRequest

@pytest.mark.asyncio
async def test_kernel_facade_integration():
    mock_chroma = MagicMock()
    mock_mongo = MagicMock()
    
    brain = AriaBrain(mock_chroma, mock_mongo)
    req = BrainRequest(query="Test query", intent="general")
    
    # Verify kernel dispatches correctly without raising unhandled exceptions
    res = await brain.search(req)
    assert isinstance(res, dict)
