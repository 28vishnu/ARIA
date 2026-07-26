import pytest
from tool_manager import ToolManager

@pytest.mark.asyncio
async def test_schedule_offline_fallback():
    tm = ToolManager(None, None, None, None, None, None)
    res = await tm._handle_schedule("What is today's schedule?")
    assert res["success"] is False
    assert "offline" in res["content"]
