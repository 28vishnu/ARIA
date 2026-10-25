
"""Owner-authenticated NVIDIA NIM chat adapter for ARIA.

Cloud inference is disabled by default. ARIA_STRICT_NO_LLM takes precedence.
This adapter does not execute model-generated tool calls.
"""
from __future__ import annotations

import os
import time
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["ARIA AI providers"])

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_TIMEOUT_SECONDS = 45.0
MAX_TOTAL_CHARS = 24_000


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1, max_length=12_000)


class NvidiaChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=40)
    max_tokens: int = Field(default=1024, ge=1, le=4096)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def cloud_inference_allowed(
    env: dict[str, str] | None = None,
) -> bool:
    """Fail closed: strict no-LLM mode overrides cloud opt-in."""
    values = env if env is not None else os.environ

    if _truthy(values.get("ARIA_STRICT_NO_LLM", "1")):
        return False

    return _truthy(values.get("ARIA_ALLOW_CLOUD_LLM"))


def provider_status(
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return safe configuration metadata without exposing secrets."""
    values = env if env is not None else os.environ

    key_present = bool(
        (values.get("NVIDIA_API_KEY") or "").strip()
    )
    model_configured = bool(
        (values.get("NVIDIA_MODEL") or "").strip()
    )
    base_url = (
        values.get("NVIDIA_BASE_URL") or DEFAULT_BASE_URL
    ).strip().rstrip("/")

    parsed = urlparse(base_url)
    base_url_valid = (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )

    return {
        "provider": "nvidia_nim",
        "configured": (
            key_present and model_configured and base_url_valid
        ),
        "api_key_present": key_present,
        "model_configured": model_configured,
        "base_url_valid": base_url_valid,
        "cloud_inference_allowed": cloud_inference_allowed(values),
        "strict_no_llm": _truthy(
            values.get("ARIA_STRICT_NO_LLM", "1")
        ),
        "notes": [
            "Configuration only; no NVIDIA API request was made.",
            "API keys and model names are not returned.",
        ],
    }


def _owner_required(request: Request) -> None:
    if not getattr(request.state, "aria_owner", None):
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Sign in to ARIA.",
        )


@router.get("/ai/providers/status")
async def ai_provider_status(request: Request) -> dict[str, Any]:
    _owner_required(request)
    return {"providers": {"nvidia_nim": provider_status()}}


@router.post("/ai/providers/nvidia/chat")
async def nvidia_chat(
    payload: NvidiaChatRequest,
    request: Request,
) -> dict[str, Any]:
    _owner_required(request)

    env = os.environ

    if not cloud_inference_allowed(env):
        raise HTTPException(
            status_code=403,
            detail=(
                "Cloud inference is disabled. Strict no-LLM mode "
                "takes precedence. To enable NVIDIA deliberately, "
                "set ARIA_STRICT_NO_LLM=0 and "
                "ARIA_ALLOW_CLOUD_LLM=true."
            ),
        )

    api_key = (env.get("NVIDIA_API_KEY") or "").strip()
    model = (env.get("NVIDIA_MODEL") or "").strip()
    base_url = (
        env.get("NVIDIA_BASE_URL") or DEFAULT_BASE_URL
    ).strip().rstrip("/")

    parsed = urlparse(base_url)
    safe_base_url = (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )

    if not api_key or not model or not safe_base_url:
        raise HTTPException(
            status_code=503,
            detail=(
                "NVIDIA NIM is not configured. Set "
                "NVIDIA_API_KEY and NVIDIA_MODEL. If overriding "
                "NVIDIA_BASE_URL, use a valid HTTPS base URL."
            ),
        )

    messages = [
        {"role": item.role, "content": item.content}
        for item in payload.messages
    ]

    if sum(len(item["content"]) for item in messages) > MAX_TOTAL_CHARS:
        raise HTTPException(
            status_code=413,
            detail="Combined message content exceeds the ARIA limit.",
        )

    body = {
        "model": model,
        "messages": messages,
        "max_tokens": payload.max_tokens,
        "temperature": payload.temperature,
        "stream": False,
    }

    started = time.monotonic()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                DEFAULT_TIMEOUT_SECONDS,
                connect=10.0,
            )
        ) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="NVIDIA inference timed out. Retry later.",
        ) from None
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to NVIDIA inference service.",
        ) from None

    if response.status_code in (401, 403):
        raise HTTPException(
            status_code=502,
            detail=(
                "NVIDIA rejected the configured credentials "
                "or model access."
            ),
        )

    if response.status_code == 429:
        raise HTTPException(
            status_code=503,
            detail="NVIDIA rate limit reached. Retry later.",
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=(
                "NVIDIA inference failed with upstream HTTP "
                f"{response.status_code}."
            ),
        )

    try:
        result = response.json()
        choices = result.get("choices") or []
        answer = (
            choices[0]["message"]["content"] if choices else None
        )

        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Empty completion")
    except (ValueError, TypeError, KeyError, IndexError):
        raise HTTPException(
            status_code=502,
            detail="NVIDIA returned an unexpected response format.",
        ) from None

    usage = (
        result.get("usage")
        if isinstance(result.get("usage"), dict)
        else {}
    )

    return {
        "provider": "nvidia_nim",
        "model": model,
        "response": answer,
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
        "latency_ms": round(
            (time.monotonic() - started) * 1000
        ),
        "request_id": result.get("id"),
        "tool_execution": "disabled",
    }
