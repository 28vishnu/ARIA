"""
ARIA Final JARVIS Integration
=============================

Final coordination layer for the JARVIS-style request lifecycle.

This module does not replace CognitiveCore.

It prepares and enriches the request before CognitiveCore's normal
conversation/reasoning pipeline continues.

Canonical flow:

    Master Request
          |
          v
    LargeRequestContext
          |
          v
    EngineeringExecutionMode
          |
          v
    Unified Memory
          |
          v
    Repository Intelligence
          |
          v
    Capability Selection
          |
          v
    Multimodal Gateway
          |
          v
    Engineering / Answer / Research / Tool path
          |
          v
    CognitiveCore
          |
          v
    Memory + Experience persistence

Safety:

    - No direct GitHub push.
    - No direct deployment.
    - No direct rollback.
    - No direct repository mutation.
    - No autonomous delivery authorization.
    - Plan-only and read-only requests never enter implementation.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from typing import Any, Dict, Mapping, Optional


logger = logging.getLogger("aria.jarvis_final_integration")


class JarvisFinalIntegration:
    """
    Final JARVIS integration coordinator.

    All dependencies are injected by bootstrap.

    The class is deliberately tolerant of older ARIA interfaces so that
    existing services remain owners of their respective responsibilities.
    """

    VERSION = "ARIA-JARVIS-FINAL-INTEGRATION-20261006"

    def __init__(
        self,
        *,
        memory=None,
        jarvis_memory=None,
        jarvis_memory_system=None,
        execution_mode=None,
        engineering_execution_mode=None,
        autonomous_engineering=None,
        autonomous_engineering_lifecycle=None,
        delivery_authorization=None,
        master_delivery_authorization=None,
        multimodal=None,
        multimodal_gateway=None,
        repository_intelligence=None,
        repository_engine=None,
        readiness_gateway=None,
        capability_selector=None,
        unified_capability_selector=None,
        large_request_context=None,
        large_request=None,
        planner=None,
        phase1_runtime=None,
        cognitive_core=None,
        conversation_manager=None,
        knowledge_manager=None,
        knowledge_engine=None,
        **kwargs,
    ) -> None:
        self.memory = (
            jarvis_memory_system
            or jarvis_memory
            or memory
        )

        self.execution_mode = (
            engineering_execution_mode
            or execution_mode
        )

        self.autonomous_engineering = (
            autonomous_engineering_lifecycle
            or autonomous_engineering
        )

        self.delivery_authorization = (
            master_delivery_authorization
            or delivery_authorization
        )

        self.multimodal = (
            multimodal_gateway
            or multimodal
        )

        self.repository_intelligence = (
            repository_intelligence
            or repository_engine
        )

        self.readiness_gateway = readiness_gateway

        self.capability_selector = (
            unified_capability_selector
            or capability_selector
        )

        self.large_request_context = (
            large_request_context
            or large_request
        )

        self.planner = planner
        self.phase1_runtime = phase1_runtime
        self.cognitive_core = cognitive_core
        self.conversation_manager = conversation_manager
        self.knowledge_manager = knowledge_manager
        self.knowledge_engine = knowledge_engine

        # Preserve optional injected components for compatibility.
        self.extra_components = dict(kwargs)

        logger.info(
            "[JarvisFinal] Initialized | "
            "memory=%s | execution_mode=%s | engineering=%s | "
            "delivery=%s | multimodal=%s | repository=%s | "
            "capabilities=%s",
            bool(self.memory),
            bool(self.execution_mode),
            bool(self.autonomous_engineering),
            bool(self.delivery_authorization),
            bool(self.multimodal),
            bool(self.repository_intelligence),
            bool(self.capability_selector),
        )

    # ==================================================================
    # MAIN PREPARATION
    # ==================================================================

    async def prepare(
        self,
        query: Any,
        *,
        session_id: str = "",
        user_id: str = "",
        context: Optional[Mapping[str, Any]] = None,
        request_id: str = "",
        attachments: Optional[Any] = None,
        multimodal_input: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Prepare one complete JARVIS request.

        No engineering mutation is performed here.

        The returned context is intended to be merged into CognitiveCore's
        existing context before the normal answer/reasoning pipeline runs.
        """

        request_text = self._request_text(query)

        execution_id = (
            request_id
            or self._create_request_id()
        )

        base_context = dict(
            context or {}
        )

        base_context.update(
            {
                "query": request_text,
                "original_query": request_text,
                "session_id": session_id,
                "user_id": user_id,
                "execution_id": execution_id,
                "jarvis_final_integration": True,
                "jarvis_integration_version": self.VERSION,
            }
        )

        # --------------------------------------------------------------
        # 1. LOSSLESS LARGE-REQUEST UNDERSTANDING
        # --------------------------------------------------------------

        request_packet = await self._build_large_request_packet(
            request_text,
            request_id=execution_id,
            context=base_context,
        )

        if request_packet is not None:
            base_context["large_request"] = self._to_dict(
                request_packet
            )

            base_context["large_request_complete"] = True

            base_context["request_parts"] = (
                self._extract_request_parts(
                    request_packet
                )
            )

        # --------------------------------------------------------------
        # 2. EXECUTION MODE
        # --------------------------------------------------------------

        execution_decision = self._resolve_execution_mode(
            request_text,
            context=base_context,
        )

        if execution_decision is not None:
            base_context[
                "engineering_execution_mode"
            ] = self._to_dict(
                execution_decision
            )

            base_context[
                "execution_allowed"
            ] = self._value(
                execution_decision,
                "execution_allowed",
                False,
            )

            base_context[
                "read_only"
            ] = bool(
                self._value(
                    execution_decision,
                    "read_only",
                    False,
                )
            )

            base_context[
                "plan_only"
            ] = bool(
                self._value(
                    execution_decision,
                    "plan_only",
                    False,
                )
            )

        # --------------------------------------------------------------
        # 3. MEMORY RECALL
        # --------------------------------------------------------------

        try:
            memory_context = await self._recall_memory(
                request_text,
                session_id=session_id,
                user_id=user_id,
                context=base_context,
            )

            if memory_context is not None:
                base_context[
                    "jarvis_memory"
                ] = memory_context

        except Exception as exc:
            logger.warning(
                "[JarvisFinal] Memory recall failed: %s",
                exc,
            )

        # --------------------------------------------------------------
        # 4. REPOSITORY INTELLIGENCE
        # --------------------------------------------------------------

        if self._repository_context_required(
            request_text,
            base_context,
        ):
            try:
                repository_context = (
                    await self._inspect_repository(
                        request_text,
                        context=base_context,
                    )
                )

                if repository_context is not None:
                    base_context[
                        "repository_intelligence"
                    ] = repository_context

                    base_context[
                        "repository_context_available"
                    ] = True

            except Exception as exc:
                logger.warning(
                    "[JarvisFinal] Repository intelligence inspection "
                    "failed: %s",
                    exc,
                )

                base_context[
                    "repository_context_available"
                ] = False

        # --------------------------------------------------------------
        # 5. CAPABILITY SELECTION
        # --------------------------------------------------------------

        try:
            selection = self._select_capability(
                request_text,
                context=base_context,
            )

            if selection is not None:
                base_context[
                    "capability_selection"
                ] = self._to_dict(
                    selection
                )

        except Exception as exc:
            logger.warning(
                "[JarvisFinal] Capability selection failed: %s",
                exc,
            )

        # --------------------------------------------------------------
        # 6. MULTIMODAL INPUT
        # --------------------------------------------------------------

        multimodal_value = (
            multimodal_input
            if multimodal_input is not None
            else attachments
        )

        if multimodal_value is not None:
            try:
                multimodal_result = (
                    await self._route_multimodal(
                        multimodal_value,
                        request_text,
                        context=base_context,
                    )
                )

                if multimodal_result is not None:
                    base_context[
                        "multimodal_result"
                    ] = multimodal_result

            except Exception as exc:
                logger.warning(
                    "[JarvisFinal] Multimodal routing failed: %s",
                    exc,
                )

        # --------------------------------------------------------------
        # 7. FINAL SAFETY CONTRACT
        # --------------------------------------------------------------

        base_context[
            "github_push_requires_authorization"
        ] = True

        base_context[
            "deployment_requires_authorization"
        ] = True

        base_context[
            "rollback_requires_authorization"
        ] = True

        base_context[
            "production_direct_write"
        ] = False

        base_context[
            "automatic_delivery"
        ] = False

        if base_context.get(
            "read_only"
        ) or base_context.get(
            "plan_only"
        ):
            base_context[
                "mutation_allowed"
            ] = False

            base_context[
                "commit_allowed"
            ] = False

            base_context[
                "github_push_allowed"
            ] = False

            base_context[
                "deployment_allowed"
            ] = False

            base_context[
                "rollback_allowed"
            ] = False

            base_context[
                "execution_allowed"
            ] = False

        return {
            "success": True,
            "request_id": execution_id,
            "request": request_text,
            "context": base_context,
            "large_request": (
                self._to_dict(request_packet)
                if request_packet is not None
                else None
            ),
            "execution_mode": (
                self._to_dict(execution_decision)
                if execution_decision is not None
                else None
            ),
            "repository_inspected": bool(
                base_context.get(
                    "repository_context_available",
                    False,
                )
            ),
            "canonical": True,
            "version": self.VERSION,
        }

    # ==================================================================
    # ENGINEERING READ-ONLY / PLAN-ONLY
    # ==================================================================

    async def maybe_handle_engineering_read_only(
        self,
        query: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
        session_id: str = "",
        user_id: str = "",
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Safely handle engineering requests that must not execute.

        Returns None when the request is not a read-only/plan-only
        engineering request.

        This method NEVER calls autonomous engineering execution.
        """

        request = self._request_text(
            query
        )

        ctx = dict(
            context or {}
        )

        execution_decision = self._resolve_execution_mode(
            request,
            context=ctx,
        )

        read_only = bool(
            self._value(
                execution_decision,
                "read_only",
                False,
            )
        )

        plan_only = bool(
            self._value(
                execution_decision,
                "plan_only",
                False,
            )
        )

        if not (
            read_only
            or plan_only
        ):
            return None

        # --------------------------------------------------------------
        # READ-ONLY
        # --------------------------------------------------------------

        if read_only:
            if self.readiness_gateway is None:
                return {
                    "success": False,
                    "handled": True,
                    "blocked": True,
                    "execution_blocked": True,
                    "route": "phase1_readiness_gateway",
                    "message": (
                        "This request is read-only, but the canonical "
                        "readiness gateway is unavailable. No changes "
                        "were attempted."
                    ),
                    "version": self.VERSION,
                }

            try:
                result = await self._invoke_readiness(
                    request,
                    context=ctx,
                    session_id=session_id,
                    user_id=user_id,
                    **kwargs,
                )

                return {
                    "success": True,
                    "handled": True,
                    "blocked": False,
                    "execution_blocked": True,
                    "route": "phase1_readiness_gateway",
                    "result": result,
                    "message": self._message_from(
                        result,
                        fallback=(
                            "Read-only engineering inspection "
                            "completed. No changes were made."
                        ),
                    ),
                    "version": self.VERSION,
                }

            except Exception as exc:
                logger.exception(
                    "[JarvisFinal] Read-only readiness inspection failed."
                )

                return {
                    "success": False,
                    "handled": True,
                    "blocked": True,
                    "execution_blocked": True,
                    "route": "phase1_readiness_gateway",
                    "message": (
                        "Read-only engineering inspection failed. "
                        "No changes were attempted."
                    ),
                    "error": str(exc),
                    "version": self.VERSION,
                }

        # --------------------------------------------------------------
        # PLAN ONLY
        # --------------------------------------------------------------

        if plan_only:
            planner = self.planner

            if planner is None:
                planner = self._runtime_component(
                    "planner"
                )

            plan_context = dict(
                ctx
            )

            plan_context.update(
                {
                    "plan_only": True,
                    "read_only": True,
                    "execution_allowed": False,
                    "mutation_allowed": False,
                    "commit_allowed": False,
                    "github_push_allowed": False,
                    "deployment_allowed": False,
                    "rollback_allowed": False,
                }
            )

            if planner is not None:
                try:
                    result = await self._invoke_planner(
                        planner,
                        request,
                        context=plan_context,
                        session_id=session_id,
                        user_id=user_id,
                        **kwargs,
                    )

                    return {
                        "success": True,
                        "handled": True,
                        "blocked": False,
                        "execution_blocked": True,
                        "plan_only": True,
                        "route": "planner",
                        "result": result,
                        "message": self._message_from(
                            result,
                            fallback=(
                                "Implementation plan prepared. "
                                "No files were modified and no code "
                                "was executed."
                            ),
                        ),
                        "version": self.VERSION,
                    }

                except Exception as exc:
                    logger.warning(
                        "[JarvisFinal] Planner failed in plan-only mode: %s",
                        exc,
                    )

            return {
                "success": True,
                "handled": True,
                "blocked": False,
                "execution_blocked": True,
                "plan_only": True,
                "route": "plan_only",
                "message": (
                    "Plan-only mode is active. No files were modified, "
                    "no code was executed, no commit was created, "
                    "nothing was pushed, and nothing was deployed."
                ),
                "version": self.VERSION,
            }

        return None

    # ==================================================================
    # FINALIZE / MEMORY / EXPERIENCE
    # ==================================================================

    async def finalize(
        self,
        query: Any,
        result: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
        session_id: str = "",
        user_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Persist the final conversational/engineering experience.

        Persistence failures do not rewrite the primary result into success
        or failure.
        """

        request = self._request_text(
            query
        )

        ctx = dict(
            context or {}
        )

        normalized_result = self._normalize_result(
            result
        )

        persisted = {
            "conversation": False,
            "memory": False,
            "experience": False,
        }

        # --------------------------------------------------------------
        # Conversation persistence
        # --------------------------------------------------------------

        if self.conversation_manager is not None:
            try:
                persisted[
                    "conversation"
                ] = await self._persist_conversation(
                    request,
                    normalized_result,
                    session_id=session_id,
                    user_id=user_id,
                    context=ctx,
                )
            except Exception as exc:
                logger.warning(
                    "[JarvisFinal] Conversation persistence failed: %s",
                    exc,
                )

        # --------------------------------------------------------------
        # JARVIS memory persistence
        # --------------------------------------------------------------

        if self.memory is not None:
            try:
                persisted[
                    "memory"
                ] = await self._persist_memory(
                    request,
                    normalized_result,
                    session_id=session_id,
                    user_id=user_id,
                    context=ctx,
                )
            except Exception as exc:
                logger.warning(
                    "[JarvisFinal] Memory persistence failed: %s",
                    exc,
                )

        # --------------------------------------------------------------
        # Experience / learning persistence
        # --------------------------------------------------------------

        if self.memory is not None:
            try:
                persisted[
                    "experience"
                ] = await self._persist_experience(
                    request,
                    normalized_result,
                    session_id=session_id,
                    user_id=user_id,
                    context=ctx,
                )
            except Exception as exc:
                logger.warning(
                    "[JarvisFinal] Experience persistence failed: %s",
                    exc,
                )

        return {
            "success": True,
            "request": request,
            "result": normalized_result,
            "persistence": persisted,
            "canonical": True,
            "version": self.VERSION,
        }

    # ==================================================================
    # MEMORY
    # ==================================================================

    async def _recall_memory(
        self,
        request: str,
        *,
        session_id: str,
        user_id: str,
        context: Mapping[str, Any],
    ) -> Any:
        memory = self.memory

        if memory is None:
            return None

        for method_name in (
            "recall",
            "retrieve",
            "remembered_context",
            "get_context",
            "search",
        ):
            method = getattr(
                memory,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                return await self._call_compatible(
                    method,
                    query=request,
                    request=request,
                    session_id=session_id,
                    user_id=user_id,
                    context=dict(
                        context
                    ),
                )

            except Exception:
                continue

        return None

    async def _persist_memory(
        self,
        request: str,
        result: Mapping[str, Any],
        *,
        session_id: str,
        user_id: str,
        context: Mapping[str, Any],
    ) -> bool:
        memory = self.memory

        if memory is None:
            return False

        candidates = (
            "store_conversation",
            "store_interaction",
            "remember",
            "store",
            "save",
        )

        for method_name in candidates:
            method = getattr(
                memory,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                value = await self._call_compatible(
                    method,
                    query=request,
                    request=request,
                    result=dict(result),
                    response=dict(result),
                    session_id=session_id,
                    user_id=user_id,
                    context=dict(
                        context
                    ),
                )

                # Some ARIA memory APIs intentionally return None on
                # successful writes.
                if value is None:
                    return True

                return bool(
                    value
                    if not isinstance(
                        value,
                        Mapping,
                    )
                    else value.get(
                        "success",
                        True,
                    )
                )

            except Exception:
                continue

        return False

    async def _persist_experience(
        self,
        request: str,
        result: Mapping[str, Any],
        *,
        session_id: str,
        user_id: str,
        context: Mapping[str, Any],
    ) -> bool:
        memory = self.memory

        if memory is None:
            return False

        experience_payload = {
            "request": request,
            "result": dict(
                result
            ),
            "success": bool(
                result.get(
                    "success",
                    True,
                )
            ),
            "session_id": session_id,
            "user_id": user_id,
            "context": dict(
                context
            ),
        }

        for method_name in (
            "record_experience",
            "store_experience",
            "learn",
            "record_learning",
        ):
            method = getattr(
                memory,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                value = await self._call_compatible(
                    method,
                    experience=experience_payload,
                    request=request,
                    result=dict(
                        result
                    ),
                    success=experience_payload[
                        "success"
                    ],
                    context=dict(
                        context
                    ),
                )

                if value is None:
                    return True

                return bool(
                    value
                    if not isinstance(
                        value,
                        Mapping,
                    )
                    else value.get(
                        "success",
                        True,
                    )
                )

            except Exception:
                continue

        return False

    # ==================================================================
    # REPOSITORY INTELLIGENCE
    # ==================================================================

    def _repository_context_required(
        self,
        request: str,
        context: Mapping[str, Any],
    ) -> bool:
        text = request.lower()

        engineering_markers = (
            "implement",
            "modify",
            "change",
            "edit",
            "create a file",
            "create files",
            "fix the code",
            "fix this bug",
            "build",
            "develop",
            "engineering",
            "software",
            "codebase",
            "repository",
            "repo",
            "architecture",
            "dependencies",
            "existing code",
            "current implementation",
            "project structure",
            "project files",
            "plan how",
            "implementation plan",
        )

        if any(
            marker in text
            for marker in engineering_markers
        ):
            return True

        return bool(
            context.get(
                "engineering_request",
                False,
            )
        )

    async def _inspect_repository(
        self,
        request: str,
        *,
        context: Mapping[str, Any],
    ) -> Any:
        service = self.repository_intelligence

        if service is None:
            return None

        for method_name in (
            "inspect",
            "analyze",
            "analyze_repository",
            "get_snapshot",
            "snapshot",
            "understand",
        ):
            method = getattr(
                service,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                return await self._call_compatible(
                    method,
                    request=request,
                    query=request,
                    context=dict(
                        context
                    ),
                )

            except Exception:
                continue

        return None

    # ==================================================================
    # CAPABILITY SELECTION
    # ==================================================================

    def _select_capability(
        self,
        request: str,
        *,
        context: Mapping[str, Any],
    ) -> Any:
        selector = self.capability_selector

        if selector is None:
            return None

        for method_name in (
            "select_capability",
            "select",
            "resolve",
        ):
            method = getattr(
                selector,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                return method(
                    request,
                    context=dict(
                        context
                    ),
                )

            except TypeError:
                try:
                    return method(
                        request
                    )
                except Exception:
                    continue

            except Exception:
                continue

        return None

    # ==================================================================
    # MULTIMODAL
    # ==================================================================

    async def _route_multimodal(
        self,
        value: Any,
        request: str,
        *,
        context: Mapping[str, Any],
    ) -> Any:
        gateway = self.multimodal

        if gateway is None:
            return None

        route_method = getattr(
            gateway,
            "route",
            None,
        )

        if callable(
            route_method
        ):
            return await self._call_compatible(
                route_method,
                input=value,
                data=value,
                request=request,
                query=request,
                context=dict(
                    context
                ),
            )

        # Compatibility with individual multimodal methods.
        if isinstance(
            value,
            Mapping,
        ):
            if value.get(
                "image"
            ) is not None:
                method = getattr(
                    gateway,
                    "analyze_image",
                    None,
                )

                if callable(
                    method
                ):
                    return await self._call_compatible(
                        method,
                        image=value.get(
                            "image"
                        ),
                        request=request,
                        context=dict(
                            context
                        ),
                    )

            if value.get(
                "document"
            ) is not None:
                method = getattr(
                    gateway,
                    "process_document",
                    None,
                )

                if callable(
                    method
                ):
                    return await self._call_compatible(
                        method,
                        document=value.get(
                            "document"
                        ),
                        request=request,
                        context=dict(
                            context
                        ),
                    )

        return None

    # ==================================================================
    # LARGE REQUEST
    # ==================================================================

    async def _build_large_request_packet(
        self,
        request: str,
        *,
        request_id: str,
        context: Mapping[str, Any],
    ) -> Any:
        builder = self.large_request_context

        if builder is None:
            return None

        # Static/class factory style.
        factory = getattr(
            builder,
            "from_text",
            None,
        )

        if callable(
            factory
        ):
            try:
                return factory(
                    request,
                    request_id=request_id,
                    metadata=dict(
                        context
                    ),
                )
            except TypeError:
                try:
                    return factory(
                        request,
                        request_id=request_id,
                    )
                except TypeError:
                    return factory(
                        request
                    )

        # Instance-style builder.
        build = getattr(
            builder,
            "build",
            None
        )

        if callable(
            build
        ):
            result = build(
                request,
                request_id=request_id,
                context=dict(
                    context
                ),
            )

            if inspect.isawaitable(
                result
            ):
                result = await result

            return result

        return None

    # ==================================================================
    # READINESS / PLANNING
    # ==================================================================

    async def _invoke_readiness(
        self,
        request: str,
        *,
        context: Mapping[str, Any],
        session_id: str,
        user_id: str,
        **kwargs: Any,
    ) -> Any:
        gateway = self.readiness_gateway

        for method_name in (
            "inspect",
            "check",
            "readiness",
            "assess",
            "validate",
        ):
            method = getattr(
                gateway,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                return await self._call_compatible(
                    method,
                    request=request,
                    query=request,
                    context=dict(
                        context
                    ),
                    session_id=session_id,
                    user_id=user_id,
                    **kwargs,
                )
            except Exception:
                continue

        raise RuntimeError(
            "Readiness gateway has no supported inspection method."
        )

    async def _invoke_planner(
        self,
        planner: Any,
        request: str,
        *,
        context: Mapping[str, Any],
        session_id: str,
        user_id: str,
        **kwargs: Any,
    ) -> Any:
        for method_name in (
            "plan",
            "create_plan",
            "build_plan",
            "generate_plan",
        ):
            method = getattr(
                planner,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            return await self._call_compatible(
                method,
                request=request,
                query=request,
                context=dict(
                    context
                ),
                session_id=session_id,
                user_id=user_id,
                **kwargs,
            )

        raise RuntimeError(
            "Planner has no supported planning method."
        )

    # ==================================================================
    # EXECUTION MODE
    # ==================================================================

    def _resolve_execution_mode(
        self,
        request: str,
        *,
        context: Mapping[str, Any],
    ) -> Any:
        selector = self.execution_mode

        if selector is None:
            return None

        for method_name in (
            "determine",
            "select",
            "decide",
            "resolve",
        ):
            method = getattr(
                selector,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                return method(
                    request,
                    context=dict(
                        context
                    ),
                )

            except TypeError:
                try:
                    return method(
                        request
                    )
                except Exception:
                    continue

            except Exception as exc:
                logger.warning(
                    "[JarvisFinal] Execution mode resolution failed: %s",
                    exc,
                )
                return None

        return None

    # ==================================================================
    # REQUEST / RESULT HELPERS
    # ==================================================================

    @staticmethod
    def _request_text(
        request: Any,
    ) -> str:
        if isinstance(
            request,
            str,
        ):
            return request.strip()

        if isinstance(
            request,
            Mapping,
        ):
            for key in (
                "query",
                "request",
                "text",
                "message",
                "content",
                "original_request",
            ):
                value = request.get(
                    key
                )

                if value is not None:
                    return str(
                        value
                    ).strip()

            return str(
                request
            ).strip()

        for attribute in (
            "query",
            "request",
            "text",
            "message",
            "content",
            "original_request",
        ):
            value = getattr(
                request,
                attribute,
                None,
            )

            if value is not None:
                return str(
                    value
                ).strip()

        return str(
            request or ""
        ).strip()

    @staticmethod
    def _create_request_id() -> str:
        return (
            "jarvis_"
            + uuid.uuid4().hex
        )

    @staticmethod
    def _value(
        value: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        if value is None:
            return default

        if isinstance(
            value,
            Mapping,
        ):
            return value.get(
                key,
                default,
            )

        return getattr(
            value,
            key,
            default,
        )

    @staticmethod
    def _to_dict(
        value: Any,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            Mapping,
        ):
            return dict(
                value
            )

        method = getattr(
            value,
            "to_dict",
            None,
        )

        if callable(
            method
        ):
            try:
                result = method()

                if isinstance(
                    result,
                    Mapping,
                ):
                    return dict(
                        result
                    )

                return result
            except Exception:
                pass

        if hasattr(
            value,
            "__dict__",
        ):
            try:
                return {
                    key: val
                    for key, val in vars(
                        value
                    ).items()
                    if not key.startswith("_")
                }
            except Exception:
                pass

        return value

    @classmethod
    def _extract_request_parts(
        cls,
        packet: Any,
    ) -> list:
        if packet is None:
            return []

        parts = getattr(
            packet,
            "parts",
            None,
        )

        if parts is None and isinstance(
            packet,
            Mapping,
        ):
            parts = packet.get(
                "parts",
                [],
            )

        if not parts:
            return []

        output = []

        for part in parts:
            if isinstance(
                part,
                Mapping,
            ):
                output.append(
                    dict(
                        part
                    )
                )
            else:
                converted = cls._to_dict(
                    part
                )

                output.append(
                    converted
                )

        return output

    @staticmethod
    def _normalize_result(
        result: Any,
    ) -> Dict[str, Any]:
        if isinstance(
            result,
            Mapping,
        ):
            return dict(
                result
            )

        method = getattr(
            result,
            "to_dict",
            None
        )

        if callable(
            method
        ):
            try:
                converted = method()

                if isinstance(
                    converted,
                    Mapping,
                ):
                    return dict(
                        converted
                    )
            except Exception:
                pass

        return {
            "result": result,
            "success": True,
        }

    @staticmethod
    def _message_from(
        result: Any,
        *,
        fallback: str,
    ) -> str:
        if isinstance(
            result,
            Mapping,
        ):
            for key in (
                "message",
                "response",
                "summary",
                "answer",
                "content",
            ):
                value = result.get(
                    key
                )

                if isinstance(
                    value,
                    str,
                ) and value.strip():
                    return value.strip()

        return fallback

    # ==================================================================
    # GENERIC COMPATIBILITY CALL
    # ==================================================================

    async def _call_compatible(
        self,
        method: Any,
        **kwargs: Any,
    ) -> Any:
        if not callable(
            method
        ):
            raise TypeError(
                "Target is not callable."
            )

        try:
            signature = inspect.signature(
                method
            )
        except (
            TypeError,
            ValueError,
        ):
            result = method()

            if inspect.isawaitable(
                result
            ):
                return await result

            return result

        parameters = signature.parameters

        accepts_kwargs = any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        if accepts_kwargs:
            selected = dict(
                kwargs
            )
        else:
            selected = {
                key: value
                for key, value in kwargs.items()
                if key in parameters
            }

        positional_request = None

        for name in (
            "request",
            "query",
            "instruction",
            "goal",
            "text",
        ):
            if (
                name in selected
                and name in parameters
            ):
                positional_request = selected.pop(
                    name
                )
                break

        if positional_request is not None:
            result = method(
                positional_request,
                **selected,
            )
        else:
            result = method(
                **selected
            )

        if inspect.isawaitable(
            result
        ):
            return await result

        return result

    # ==================================================================
    # RUNTIME COMPONENT ACCESS
    # ==================================================================

    def _runtime_component(
        self,
        name: str,
    ) -> Any:
        runtime = self.phase1_runtime

        if runtime is None:
            return None

        getter = getattr(
            runtime,
            "get",
            None,
        )

        if callable(
            getter
        ):
            try:
                value = getter(
                    name
                )

                if value is not None:
                    return value
            except Exception:
                pass

        if isinstance(
            runtime,
            Mapping,
        ):
            return runtime.get(
                name
            )

        return getattr(
            runtime,
            name,
            None,
        )

    # ==================================================================
    # CONVERSATION PERSISTENCE
    # ==================================================================

    async def _persist_conversation(
        self,
        request: str,
        result: Mapping[str, Any],
        *,
        session_id: str,
        user_id: str,
        context: Mapping[str, Any],
    ) -> bool:
        manager = self.conversation_manager

        if manager is None:
            return False

        for method_name in (
            "add_message",
            "record",
            "store",
            "save",
            "append",
        ):
            method = getattr(
                manager,
                method_name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:
                value = await self._call_compatible(
                    method,
                    query=request,
                    request=request,
                    result=dict(
                        result
                    ),
                    response=dict(
                        result
                    ),
                    session_id=session_id,
                    user_id=user_id,
                    context=dict(
                        context
                    ),
                )

                if value is None:
                    return True

                return bool(
                    value
                    if not isinstance(
                        value,
                        Mapping,
                    )
                    else value.get(
                        "success",
                        True,
                    )
                )

            except Exception:
                continue

        return False

    # ==================================================================
    # HEALTH
    # ==================================================================

    def health(
        self,
    ) -> Dict[str, Any]:
        """
        Structural health only.

        This method never executes engineering.
        """

        return {
            "healthy": True,
            "version": self.VERSION,
            "canonical": True,
            "memory": self.memory is not None,
            "execution_mode": self.execution_mode is not None,
            "autonomous_engineering": (
                self.autonomous_engineering is not None
            ),
            "delivery_authorization": (
                self.delivery_authorization is not None
            ),
            "multimodal": self.multimodal is not None,
            "repository_intelligence": (
                self.repository_intelligence is not None
            ),
            "readiness_gateway": (
                self.readiness_gateway is not None
            ),
            "capability_selector": (
                self.capability_selector is not None
            ),
            "large_request_context": (
                self.large_request_context is not None
            ),
            "planner": self.planner is not None,
            "github_push_requires_authorization": True,
            "deployment_requires_authorization": True,
            "rollback_requires_authorization": True,
            "production_direct_write": False,
            "automatic_delivery": False,
        }

    def capabilities(
        self,
    ) -> Dict[str, Any]:
        return {
            "large_request_understanding": True,
            "lossless_request_context": True,
            "execution_mode": True,
            "memory_recall": True,
            "memory_persistence": True,
            "experience_persistence": True,
            "repository_intelligence": True,
            "capability_selection": True,
            "multimodal": True,
            "readiness": True,
            "plan_only": True,
            "engineering_execution": True,
            "github_push_authorization": True,
            "deployment_authorization": True,
            "rollback_authorization": True,
            "direct_delivery": False,
            "direct_repository_mutation": False,
        }


__all__ = [
    "JarvisFinalIntegration",
]