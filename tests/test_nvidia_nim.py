
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from integrations import nvidia_nim


def test_strict_no_llm_overrides_cloud_opt_in():
    assert not nvidia_nim.cloud_inference_allowed({
        "ARIA_STRICT_NO_LLM": "1",
        "ARIA_ALLOW_CLOUD_LLM": "true",
    })


def test_cloud_inference_requires_explicit_opt_in():
    assert not nvidia_nim.cloud_inference_allowed({
        "ARIA_STRICT_NO_LLM": "0",
    })

    assert nvidia_nim.cloud_inference_allowed({
        "ARIA_STRICT_NO_LLM": "0",
        "ARIA_ALLOW_CLOUD_LLM": "true",
    })


def test_status_does_not_expose_secrets():
    result = nvidia_nim.provider_status({
        "NVIDIA_API_KEY": "test-secret-key",
        "NVIDIA_MODEL": "private-test-model",
        "NVIDIA_BASE_URL": nvidia_nim.DEFAULT_BASE_URL,
        "ARIA_STRICT_NO_LLM": "0",
        "ARIA_ALLOW_CLOUD_LLM": "true",
    })

    rendered = repr(result)

    assert result["configured"] is True
    assert "test-secret-key" not in rendered
    assert "private-test-model" not in rendered


def test_rejects_missing_owner():
    request = SimpleNamespace(state=SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        nvidia_nim._owner_required(request)

    assert exc.value.status_code == 401


def test_rejects_invalid_message_role():
    with pytest.raises(Exception):
        nvidia_nim.NvidiaChatRequest(
            messages=[{
                "role": "tool",
                "content": "not allowed",
            }]
        )


def test_rejects_empty_message_list():
    with pytest.raises(Exception):
        nvidia_nim.NvidiaChatRequest(messages=[])


def test_rejects_invalid_base_url():
    result = nvidia_nim.provider_status({
        "NVIDIA_API_KEY": "test-key",
        "NVIDIA_MODEL": "test-model",
        "NVIDIA_BASE_URL": "http://example.com/v1",
        "ARIA_STRICT_NO_LLM": "0",
        "ARIA_ALLOW_CLOUD_LLM": "true",
    })

    assert result["configured"] is False
    assert result["base_url_valid"] is False


@pytest.mark.asyncio
async def test_nvidia_chat_calls_compatible_endpoint(
    monkeypatch,
):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "id": "test-request-1",
                "choices": [{
                    "message": {
                        "content": "Hello from NVIDIA"
                    }
                }],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "total_tokens": 8,
                },
            }

    class FakeClient:
        def __init__(self, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers, json):
            captured.update(
                url=url,
                headers=headers,
                json=json,
            )
            return FakeResponse()

    monkeypatch.setattr(
        nvidia_nim.httpx,
        "AsyncClient",
        FakeClient,
    )
    monkeypatch.setattr(
        nvidia_nim,
        "cloud_inference_allowed",
        lambda env=None: True,
    )
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-do-not-return")
    monkeypatch.setenv("NVIDIA_MODEL", "test/model")
    monkeypatch.setenv(
        "NVIDIA_BASE_URL",
        nvidia_nim.DEFAULT_BASE_URL,
    )

    request = SimpleNamespace(
        state=SimpleNamespace(aria_owner="test-owner")
    )
    payload = nvidia_nim.NvidiaChatRequest(
        messages=[{"role": "user", "content": "Hello"}]
    )

    result = await nvidia_nim.nvidia_chat(payload, request)

    assert captured["url"] == (
        "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    assert captured["headers"]["Authorization"] == (
        "Bearer test-key-do-not-return"
    )
    assert captured["json"]["model"] == "test/model"
    assert result["response"] == "Hello from NVIDIA"
    assert result["tool_execution"] == "disabled"
    assert "test-key-do-not-return" not in repr(result)


def test_main_registers_nvidia_routes():
    import main

    paths = {
        getattr(route, "path", "")
        for route in main.app.routes
    }

    assert "/ai/providers/status" in paths
    assert "/ai/providers/nvidia/chat" in paths
