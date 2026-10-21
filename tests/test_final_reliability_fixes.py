from __future__ import annotations

import asyncio
from types import SimpleNamespace

from planner import action_planner, _normalise_plan
from skills.weather import WeatherSkill


def test_weather_skill_does_not_report_pending_integration_as_success():
    result = asyncio.run(WeatherSkill().execute("weather today", {}))
    assert result.success is False
    assert result.data["status"] == "unavailable"


def test_weather_skill_delegates_only_when_action_and_location_are_available():
    class Manager:
        def has_action(self, name):
            return name == "weather_action"

        async def execute_action(self, name, params, confirmed=False):
            assert name == "weather_action"
            assert params == {"location": "Visakhapatnam"}
            assert confirmed is False
            return SimpleNamespace(success=True, data={"temperature": 28}, error=None)

    result = asyncio.run(WeatherSkill().execute(
        "weather today", {"action_manager": Manager(), "weather_location": "Visakhapatnam"}
    ))
    assert result.success is True
    assert result.data == {"temperature": 28}


def test_planner_discards_unknown_tools_and_clarifies_empty_execute_plan():
    assert _normalise_plan({"action": "execute", "tools": ["evil", "search"]}, {"search": {}}) == {
        "action": "execute", "tools": ["search"]
    }
    assert _normalise_plan({"action": "execute", "tools": ["evil"]}, {"search": {}})["action"] == "clarify"


def test_planner_rejects_invalid_schema_and_uses_safe_fallback():
    assert _normalise_plan({"action": "delete_everything", "tools": []}, {}) is None

    class BrokenRouter:
        async def chat(self, *args, **kwargs):
            raise RuntimeError("simulated provider failure")

    result = asyncio.run(action_planner("find a fact", "", {"search": {}}, [], BrokenRouter()))
    assert result == {"action": "retrieve", "tools": []}


def test_planner_validates_model_output_and_does_not_execute_tools():
    class Router:
        async def chat(self, *args, **kwargs):
            return '```json\n{"action":"execute","tools":["search","unknown"]}\n```'

    result = asyncio.run(action_planner("search", "", {"search": {}}, [], Router()))
    assert result == {"action": "execute", "tools": ["search"]}
