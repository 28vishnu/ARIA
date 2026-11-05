from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("aria")


@dataclass
class AgentResponse:
    """
    Standard response returned by every ARIA Agent.

    ``success`` must remain False whenever the agent produced no usable
    output. The base class enforces this so callers never receive a
    successful response with an empty answer.
    """

    success: bool
    confidence: float
    agent: str
    data: Dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def output_text(self) -> str:
        """Return the first non-empty user-facing output."""
        if isinstance(self.data, dict):
            for key in (
                "response",
                "message",
                "answer",
                "content",
                "output",
                "result",
                "summary",
            ):
                value = self.data.get(key)
                if value is None:
                    continue
                if isinstance(value, (dict, list, tuple)):
                    continue
                text = str(value).strip()
                if text:
                    return text
        return ""

    def has_output(self) -> bool:
        return bool(self.output_text())

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": bool(self.success),
            "confidence": float(self.confidence or 0.0),
            "agent": str(self.agent or ""),
            "result": self.output_text(),
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseAgent(ABC):
    """
    Base class for every ARIA Agent.

    The concrete agent implements ``can_handle`` and ``execute``. The
    inherited ``run`` method adds input validation, bounded timeout/retry, and
    output validation. Managers should call ``run`` rather than ``execute`` so
    every specialist gets the same reliability contract.
    """

    name = "base"
    description = "Base Agent"
    version = "1.1.0"
    priority = 0

    # Optional additional names accepted by AgentManager.
    aliases: tuple[str, ...] = ()

    # Bounded execution controls (overridable per agent).
    timeout_seconds: float = 45.0
    max_retries: int = 1
    retry_backoff_seconds: float = 0.15
    max_query_chars: int = 30_000

    @abstractmethod
    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:
        """
        Returns a confidence score (0.0 - 1.0)
        indicating whether this agent should handle the request.
        """

    @abstractmethod
    async def execute(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """
        Executes the request and returns an AgentResponse.
        """

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_input(
        self,
        query: Any,
        context: Any,
    ) -> Tuple[bool, Optional[str]]:
        if context is None:
            context = {}
        if not isinstance(context, dict):
            return False, "Agent context must be a dictionary."
        text = str(query or "").strip()
        if not text:
            return False, "The agent request is empty."
        if len(text) > self.max_query_chars:
            return False, (
                f"The agent request exceeds {self.max_query_chars} characters."
            )
        return True, None

    def validate_output(
        self,
        response: Any,
    ) -> Tuple[bool, Optional[str]]:
        if response is None:
            return False, "The agent returned no response."
        if not isinstance(response, AgentResponse):
            return False, "The agent returned an invalid response type."
        if response.success and not response.has_output():
            return False, "The agent reported success without usable output."
        return True, None

    # ------------------------------------------------------------------
    # Shared LLM helper
    # ------------------------------------------------------------------

    @staticmethod
    def _registry(context: Dict[str, Any]):
        app_state = (
            context.get("app_state")
            if isinstance(context, dict)
            else None
        )
        return getattr(app_state, "registry", None)

    async def complete_with_llm(
        self,
        context: Dict[str, Any],
        system_prompt: str,
        query: str,
        *,
        temperature: float | None = None,
    ) -> Optional[str]:
        """Return a non-empty LLM answer, or None when unavailable."""

        registry = self._registry(context)
        llm_router = None
        if registry is not None:
            try:
                llm_router = registry.get("llm_router")
            except Exception:
                llm_router = None
        if llm_router is None or not hasattr(llm_router, "chat"):
            return None

        messages = [
            {"role": "system", "content": str(system_prompt)},
            {"role": "user", "content": str(query)},
        ]

        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            answer = await llm_router.chat(messages, **kwargs)
        except TypeError:
            # Older routers do not accept optional kwargs.
            try:
                answer = await llm_router.chat(messages)
            except Exception:
                logger.exception(
                    "[%s] LLM completion failed.", self.name
                )
                return None
        except Exception:
            logger.exception(
                "[%s] LLM completion failed.", self.name
            )
            return None

        text = str(answer or "").strip()
        return text or None

    # ------------------------------------------------------------------
    # Reliable execution contract
    # ------------------------------------------------------------------

    async def run(
        self,
        query: str,
        context: Dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> AgentResponse:
        context = context if isinstance(context, dict) else {}

        valid, reason = self.validate_input(query, context)
        if not valid:
            return AgentResponse(
                success=False,
                confidence=0.0,
                agent=self.name,
                data={},
                error=reason,
            )

        attempts = max(1, int(self.max_retries or 0) + 1)
        effective_timeout = max(
            1.0,
            float(
                timeout
                if timeout is not None
                else self.timeout_seconds
            ),
        )
        last_error = "Agent execution failed."

        for attempt in range(1, attempts + 1):
            try:
                response = await asyncio.wait_for(
                    self.execute(query=query, context=context),
                    timeout=effective_timeout,
                )
                response = self._coerce_response(response)
                valid_output, output_reason = self.validate_output(response)
                if not valid_output:
                    last_error = output_reason or "Invalid agent output."
                    if attempt < attempts:
                        await asyncio.sleep(
                            max(0.0, self.retry_backoff_seconds) * attempt
                        )
                        continue
                    return AgentResponse(
                        success=False,
                        confidence=0.0,
                        agent=self.name,
                        data=response.data if isinstance(response, AgentResponse) else {},
                        error=last_error,
                    )

                if response.success:
                    return response

                last_error = response.error or "The agent could not complete the request."
                if attempt < attempts:
                    await asyncio.sleep(
                        max(0.0, self.retry_backoff_seconds) * attempt
                    )
                    continue
                return response

            except asyncio.TimeoutError:
                last_error = (
                    f"The {self.name} agent timed out after "
                    f"{effective_timeout:.1f} seconds."
                )
                logger.warning("[%s] %s", self.name, last_error)
                if attempt < attempts:
                    continue

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.exception(
                    "[%s] Agent execution failed on attempt %d/%d.",
                    self.name,
                    attempt,
                    attempts,
                )
                if attempt < attempts:
                    await asyncio.sleep(
                        max(0.0, self.retry_backoff_seconds) * attempt
                    )
                    continue

        return AgentResponse(
            success=False,
            confidence=0.0,
            agent=self.name,
            data={},
            error=last_error,
        )

    def _coerce_response(self, response: Any) -> AgentResponse:
        if isinstance(response, AgentResponse):
            return response

        if isinstance(response, dict):
            data = response.get("data")
            if not isinstance(data, dict):
                data = {
                    key: value
                    for key, value in response.items()
                    if key not in {"success", "confidence", "agent", "error"}
                }
            return AgentResponse(
                success=bool(response.get("success", False)),
                confidence=float(response.get("confidence", 0.0) or 0.0),
                agent=str(response.get("agent") or self.name),
                data=data,
                error=response.get("error"),
                metadata=response.get("metadata", {}),
            )

        text = str(response or "").strip()
        return AgentResponse(
            success=bool(text),
            confidence=0.5 if text else 0.0,
            agent=self.name,
            data={"response": text} if text else {},
            error=None if text else "The agent returned no response.",
        )
