"""Final JARVIS integration boundary for ARIA.

This is the single bridge between the accumulated Step 1-9 capabilities and
CognitiveCore. It does not replace the existing specialized engines. It
prepares complete request context, enforces plan/inspection safety, recalls
memory, exposes multimodal input, and records the resulting experience.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, Optional, Sequence

from personality.response import SystemResponse

from brain.core.large_request_context import LargeRequestContext

logger = logging.getLogger("aria")


class JarvisFinalIntegration:
    VERSION = "ARIA-JARVIS-FINAL-INTEGRATION-20261006"

    def __init__(
        self,
        *,
        memory_system=None,
        execution_mode=None,
        autonomous_engineering_lifecycle=None,
        master_delivery_authorization=None,
        multimodal_gateway=None,
        repository_intelligence=None,
        readiness_gateway=None,
    ) -> None:
        self.memory_system = memory_system
        self.execution_mode = execution_mode
        self.autonomous_engineering_lifecycle = (
            autonomous_engineering_lifecycle
        )
        self.master_delivery_authorization = (
            master_delivery_authorization
        )
        self.multimodal_gateway = multimodal_gateway
        self.repository_intelligence = repository_intelligence
        self.readiness_gateway = readiness_gateway

    def health(self) -> Dict[str, Any]:
        return {
            "healthy": True,
            "version": self.VERSION,
            "memory": self.memory_system is not None,
            "execution_mode": self.execution_mode is not None,
            "autonomous_engineering": (
                self.autonomous_engineering_lifecycle is not None
            ),
            "delivery_authorization": (
                self.master_delivery_authorization is not None
            ),
            "multimodal": self.multimodal_gateway is not None,
            "repository_intelligence": (
                self.repository_intelligence is not None
            ),
            "readiness_gateway": self.readiness_gateway is not None,
        }

    async def prepare(
        self,
        query: str,
        *,
        execution_id: str,
        session_id: str = "",
        user_id: str = "",
        base_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build complete, lossless context before CognitiveCore reasons."""

        base = dict(base_context or {})
        request_parts = base.get("request_parts")

        if (
            isinstance(request_parts, Sequence)
            and not isinstance(request_parts, (str, bytes))
        ):
            packet = LargeRequestContext.from_parts(
                [str(part) for part in request_parts],
                request_id=execution_id,
                source="transport_parts",
            )
        else:
            packet = LargeRequestContext.from_text(
                str(query),
                request_id=execution_id,
                source="message",
            )

        decision = None

        if self.execution_mode is not None:
            try:
                decision = self.execution_mode.decide(
                    str(query)
                )
            except Exception:
                logger.exception(
                    "[JarvisFinal] execution-mode decision failed"
                )

        memory_context: Dict[str, Any] = {}

        if self.memory_system is not None:
            try:
                memory_context = (
                    await self.memory_system.build_context(
                        packet.text,
                        limit=10,
                    )
                )
            except Exception:
                logger.exception(
                    "[JarvisFinal] memory recall failed"
                )

        repository_context: Dict[str, Any] = {}

        if (
            self.repository_intelligence is not None
            and decision is not None
        ):
            if decision.mode in {
                "execute",
                "plan_only",
                "inspect_only",
            } or base.get("force_repository_refresh"):
                try:
                    inspector = getattr(
                        self.repository_intelligence,
                        "inspect",
                        None,
                    )

                    if callable(inspector):
                        repository_context = inspector(
                            packet.text
                        )

                        if inspect.isawaitable(
                            repository_context
                        ):
                            repository_context = (
                                await repository_context
                            )

                        if not isinstance(
                            repository_context,
                            dict,
                        ):
                            repository_context = {
                                "success": True,
                                "result": repository_context,
                            }

                except Exception:
                    logger.exception(
                        "[JarvisFinal] repository intelligence "
                        "inspection failed"
                    )

        multimodal_context: Dict[str, Any] = {}

        modality = str(
            base.get("modality", "")
        ).strip().lower()

        payload = base.get(
            "modality_payload"
        )

        if (
            self.multimodal_gateway is not None
            and modality
            and payload is not None
        ):
            try:
                multimodal_context = (
                    await self.multimodal_gateway.route(
                        modality,
                        payload,
                        metadata=(
                            base.get(
                                "modality_metadata"
                            )
                            or {}
                        ),
                    )
                )
            except Exception:
                logger.exception(
                    "[JarvisFinal] multimodal routing failed"
                )

        context = {
            **base,
            "jarvis_final_integration": self.VERSION,
            "request_packet": packet.to_dict(),
            "complete_request_text": packet.text,
            "request_sha256": packet.sha256,
            "request_sections": [
                section.__dict__
                for section in packet.sections
            ],
            "request_constraints": list(
                packet.constraints
            ),
            "request_intent_hints": list(
                packet.intent_hints
            ),
            "request_contains_code": (
                packet.contains_code
            ),
            "request_contains_file_paths": (
                packet.contains_file_paths
            ),
            "request_contains_urls": (
                packet.contains_urls
            ),
            "engineering_execution_decision": (
                decision.to_dict()
                if decision is not None
                else None
            ),
            "memory_context": memory_context,
            "multimodal_context": multimodal_context,
            "repository_intelligence": (
                self.repository_intelligence
            ),
            "repository_context": repository_context,
        }

        return context

    async def maybe_handle_engineering_read_only(
        self,
        query: str,
        *,
        session_id: str,
        user_id: str,
        context: Dict[str, Any],
        engineering_router=None,
        planner=None,
    ) -> Optional[SystemResponse]:
        """Handle explicit planning/inspection requests without mutation."""

        decision = (
            context.get(
                "engineering_execution_decision"
            )
            or {}
        )

        mode = decision.get("mode")

        if mode not in {
            "plan_only",
            "inspect_only",
        }:
            return None

        classification = None

        if engineering_router is not None:
            try:
                classification = (
                    engineering_router.classify(
                        query
                    )
                )
            except Exception:
                logger.exception(
                    "[JarvisFinal] engineering "
                    "classification failed"
                )

        if (
            not classification
            or not classification.is_engineering
        ):
            return None

        if mode == "inspect_only":
            if self.readiness_gateway is None:
                return SystemResponse(
                    success=False,
                    confidence=0.0,
                    source="jarvis_final_integration",
                    data={
                        "message": (
                            "The read-only readiness "
                            "gateway is unavailable."
                        )
                    },
                )

            try:
                report = (
                    self.readiness_gateway.inspect(
                        session_id=session_id
                    )
                )

                message = (
                    report.get("message")
                    or report.get("summary")
                    or "Read-only inspection completed."
                )

                return SystemResponse(
                    success=True,
                    confidence=1.0,
                    source="phase1_readiness_gateway",
                    data={
                        "message": message,
                        "response": message,
                        "read_only": True,
                        "execution_started": False,
                        "report": report,
                    },
                )

            except Exception as exc:
                logger.exception(
                    "[JarvisFinal] readiness inspection failed"
                )

                return SystemResponse(
                    success=False,
                    confidence=0.0,
                    source="jarvis_final_integration",
                    data={
                        "message": str(exc),
                        "read_only": True,
                    },
                    error=str(exc),
                )

        if planner is None:
            return None

        try:
            plan = planner.create_plan(
                query,
                {
                    **context,
                    "planning_only": True,
                    "execution_allowed": False,
                    "mutation_allowed": False,
                },
            )

            if inspect.isawaitable(plan):
                plan = await plan

            plan_data = (
                plan.to_dict()
                if hasattr(plan, "to_dict")
                else plan
            )

            tasks = (
                plan_data.get("tasks", [])
                if isinstance(plan_data, dict)
                else []
            )

            if tasks:
                lines = [
                    "Plan-only mode — no files will be modified.",
                    "",
                ]

                for index, task in enumerate(
                    tasks,
                    1,
                ):
                    if isinstance(task, dict):
                        description = (
                            task.get("description")
                            or task.get("action_name")
                            or task.get("skill")
                            or f"Step {index}"
                        )
                    else:
                        description = str(task)

                    lines.append(
                        f"{index}. {description}"
                    )

                message = "\n".join(lines)

            else:
                message = (
                    "Plan-only mode — no implementation "
                    "was started. The request was analyzed "
                    "and no executable tasks were generated."
                )

            confidence = (
                float(
                    plan_data.get(
                        "confidence",
                        0.9,
                    )
                )
                if isinstance(plan_data, dict)
                else 0.9
            )

            return SystemResponse(
                success=True,
                confidence=confidence,
                source="jarvis_plan_only",
                data={
                    "message": message,
                    "response": message,
                    "plan_only": True,
                    "execution_started": False,
                    "mutation_performed": False,
                    "plan": plan_data,
                },
            )

        except Exception:
            logger.exception(
                "[JarvisFinal] plan-only generation failed"
            )
            return None

    async def finalize(
        self,
        query: str,
        result: Any,
        *,
        session_id: str = "",
        user_id: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist the complete interaction and engineering outcome."""

        if self.memory_system is None:
            return

        payload = self._result_payload(
            result
        )

        outcome = {
            "query": query,
            "session_id": session_id,
            "user_id": user_id,
            "success": payload.get(
                "success"
            ),
            "source": payload.get(
                "source"
            ),
            "response": (
                payload.get("message")
                or payload.get("response")
            ),
            "error": payload.get(
                "error"
            ),
            "request_sha256": (
                (context or {}).get(
                    "request_sha256"
                )
            ),
            "execution_mode": (
                (context or {}).get(
                    "engineering_execution_decision"
                )
            ),
        }

        try:
            await self.memory_system.remember(
                {
                    "key": "conversation_exchange",
                    "value": outcome,
                    "memory_type": "conversation",
                }
            )
        except Exception:
            logger.exception(
                "[JarvisFinal] conversation "
                "persistence failed"
            )

        try:
            if payload.get("success") is True:
                await self.memory_system.learn_success(
                    query,
                    outcome,
                )

            elif payload.get("success") is False:
                await self.memory_system.learn_failure(
                    query,
                    payload.get("error")
                    or "request failed",
                )

        except Exception:
            logger.exception(
                "[JarvisFinal] experience "
                "persistence failed"
            )

    @staticmethod
    def _result_payload(
        result: Any,
    ) -> Dict[str, Any]:
        if isinstance(result, dict):
            return result

        data = getattr(
            result,
            "data",
            None,
        )

        payload = (
            dict(data)
            if isinstance(data, dict)
            else {}
        )

        success = getattr(
            result,
            "success",
            None,
        )

        if success is not None:
            payload.setdefault(
                "success",
                bool(success),
            )

        error = getattr(
            result,
            "error",
            None,
        )

        if error:
            payload.setdefault(
                "error",
                str(error),
            )

        source = getattr(
            result,
            "source",
            None,
        )

        if source:
            payload.setdefault(
                "source",
                str(source),
            )

        return payload


__all__ = [
    "JarvisFinalIntegration",
]