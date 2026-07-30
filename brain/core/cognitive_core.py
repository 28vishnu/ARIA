import logging
import asyncio
from typing import Dict, Any, Optional
from personality.response import SystemResponse
from brain.reasoning.reasoning_engine import ReasoningEngine
from brain.response.response_formatter import ResponseFormatter
from brain.agents.response_fusion import ResponseFusion

logger = logging.getLogger("aria")

class CognitiveCore:
    """The central orchestrator of ARIA 2.0, coordinating skills, memory, planning, and execution."""
    def __init__(
        self,
        planner,
        executor,
        skill_manager,
        memory_router=None,
        state_manager=None,
        intent_analyzer=None,
        context_builder=None,
        decision_engine=None,
        memory_conversation_manager=None,
        reasoning_engine=None
    ):
        self.planner = planner
        self.executor = executor
        self.skill_manager = skill_manager
        self.memory_router = memory_router
        self.state_manager = state_manager
        self.intent_analyzer = intent_analyzer
        self.context_builder = context_builder
        self.decision_engine = decision_engine
        self.memory_conversation_manager = memory_conversation_manager
        self.reasoning_engine = reasoning_engine
        self.response_formatter = ResponseFormatter()
        self.response_fusion = ResponseFusion()

    async def process(
        self,
        query: str,
        session_id: str = "",
        user_id: str = "",
        base_context: Optional[Dict[str, Any]] = None
    ) -> SystemResponse:
        """Orchestrates the core request-processing flow using existing skill routing, planning, and execution."""
        try:
            # 1. Get State
            state = {}
            if self.state_manager:
                state = self.state_manager.get_state(session_id)

            # 2. Get relevant existing memories
            memories = []
            if self.memory_router:
                try:
                    memories = await self.memory_router.get_relevant_memories(query)
                except Exception:
                    logger.exception(
                        "[CognitiveCore] Memory retrieval failed."
                    )

            # 2.1 Learn useful long-term information from normal conversation
            if self.memory_router:
                try:
                    memory_result = await self.memory_router.process_and_store(query)

                    if memory_result and memory_result.get("success"):
                        logger.info(
                            "[CognitiveCore] Learned memory: key=%s action=%s",
                            memory_result.get("key"),
                            memory_result.get("action")
                        )

                except Exception:
                    # Memory learning must NEVER break normal conversation.
                    logger.exception(
                        "[CognitiveCore] Automatic memory learning failed."
                    )

            # 3. Build Context (including state and memories)
            ctx = {}
            if self.context_builder:
                ctx = await self.context_builder.build(
                    query=query,
                    session_id=session_id,
                    user_id=user_id,
                    base_context=base_context,
                    memory=memories,
                    state=state
                )
            else:
                ctx = base_context or {}
                ctx["state"] = state
                ctx["memory"] = memories

            document_ai = None

            if base_context:

                app_state = base_context.get("app_state")

                if app_state:

                    document_ai = app_state.registry.get(
                        "document_intelligence"
                    )

            ctx["document_intelligence"] = document_ai

            # Store the current request in the session state
            if self.state_manager:
                self.state_manager.update_state(
                    session_id,
                    last_query=query
                )

            intent = None
            if self.intent_analyzer:
                intent = await self.intent_analyzer.analyze(query)
                ctx["intent"] = intent

            # ---------------------------------------------------------
            # Fast paths
            # ---------------------------------------------------------
            # Deterministic conversational intents should not require
            # an external LLM call.
            if intent:

                # -------------------------------------------------
                # DOCUMENT CATALOGUE FAST PATHS
                # -------------------------------------------------

                if intent.name in (
                    "document_retrieve",
                    "document_list",
                    "document_query",
                    "delete_document",
                    "delete_all_documents",
                ):
                    logger.info(
                        "[CognitiveCore] Document fast-path activated: %s",
                        intent.name
                    )

                    document_repository = None
                    document_ai = ctx.get("document_intelligence")

                    if base_context:
                        app_state = base_context.get("app_state")

                        if (
                            app_state
                            and app_state.registry.has(
                                "document_repository"
                            )
                        ):
                            document_repository = (
                                app_state.registry.get(
                                    "document_repository"
                                )
                            )

                    # ---------------------------------------------
                    # DELETE ALL STORED DOCUMENTS
                    # ---------------------------------------------

                    if intent.name == "delete_all_documents":

                        if not document_repository:
                            return SystemResponse(
                                success=False,
                                confidence=intent.confidence,
                                source="document_repository",
                                error="Document repository is unavailable."
                            )

                        documents = await document_repository.list_documents(
                            user_id=user_id
                        )

                        if not documents:
                            return SystemResponse(
                                success=True,
                                confidence=intent.confidence,
                                source="document_management",
                                data={
                                    "message": "You don't have any stored documents to delete, Sir."
                                }
                            )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            source="document_management",
                            data={
                                "document_action": "confirm_delete_all_documents",
                                "documents": documents
                            }
                        )

                    # ---------------------------------------------
                    # DELETE ONE STORED DOCUMENT
                    # ---------------------------------------------

                    if intent.name == "delete_document":

                        if not document_repository:
                            return SystemResponse(
                                success=False,
                                confidence=intent.confidence,
                                source="document_repository",
                                error="Document repository is unavailable."
                            )

                        documents = await document_repository.search_documents(
                            user_id=user_id,
                            query=query,
                            limit=10
                        )

                        if not documents:
                            documents = await document_repository.list_documents(
                                user_id=user_id,
                                limit=20
                            )

                        if not documents:
                            return SystemResponse(
                                success=True,
                                confidence=intent.confidence,
                                source="document_management",
                                data={
                                    "message": "I couldn't find that document, Sir."
                                }
                            )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            source="document_management",
                            data={
                                "document_action": "confirm_delete_document",
                                "query": query,
                                "documents": documents
                            }
                        )

                    # ---------------------------------------------
                    # LIST STORED DOCUMENTS
                    # ---------------------------------------------

                    if intent.name == "document_list":

                        if not document_repository:
                            return SystemResponse(
                                success=False,
                                confidence=intent.confidence,
                                source="document_repository",
                                error="Document repository is unavailable."
                            )

                        documents = await document_repository.list_documents(
                            user_id=user_id
                        )

                        if not documents:
                            return SystemResponse(
                                success=True,
                                confidence=intent.confidence,
                                source="document_repository",
                                data={
                                    "message": (
                                        "You don't have any stored "
                                        "documents yet, Sir."
                                    )
                                }
                            )

                        filenames = [
                            doc.get("filename", "Unnamed document")
                            for doc in documents
                        ]

                        message = (
                            "I currently have these documents, Sir:\n\n"
                            + "\n".join(
                                f"• {name}"
                                for name in filenames
                            )
                        )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            source="document_repository",
                            data={
                                "message": message
                            }
                        )

                    # ---------------------------------------------
                    # RETRIEVE ORIGINAL DOCUMENT
                    # ---------------------------------------------

                    if intent.name == "document_retrieve":

                        if not document_repository:
                            return SystemResponse(
                                success=False,
                                confidence=intent.confidence,
                                source="document_repository",
                                error="Document repository is unavailable."
                            )

                        documents = await document_repository.search_documents(
                            user_id=user_id,
                            query=query,
                            limit=10
                        )

                        # The raw request may contain words such as
                        # "give", "send", "my", "pdf", etc., so a
                        # filename search using the whole query may
                        # fail. Fall back to all documents and let
                        # the transport layer resolve the best match.
                        if not documents:
                            documents = await document_repository.list_documents(
                                user_id=user_id,
                                limit=20
                            )

                        if not documents:
                            return SystemResponse(
                                success=True,
                                confidence=intent.confidence,
                                source="document_repository",
                                data={
                                    "message": (
                                        "I couldn't find a stored "
                                        "document matching that request, Sir."
                                    )
                                }
                            )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            source="document_retrieval",
                            data={
                                "document_action": "send_document",
                                "query": query,
                                "documents": documents
                            }
                        )

                    # ---------------------------------------------
                    # QUERY / SUMMARISE STORED DOCUMENT
                    # ---------------------------------------------

                    if intent.name == "document_query":

                        if not document_ai:
                            return SystemResponse(
                                success=False,
                                confidence=intent.confidence,
                                source="document",
                                error="Document intelligence is unavailable."
                            )

                        answer = await document_ai.answer_question(
                            session_id=session_id,
                            question=query,
                            state=ctx.get("state")
                        )

                        if answer:

                            if self.state_manager:
                                self.state_manager.update_state(
                                    session_id,
                                    last_document_question=query,
                                    last_document_answer=answer
                                )

                            return SystemResponse(
                                success=True,
                                confidence=intent.confidence,
                                source="document",
                                data={
                                    "response": answer
                                }
                            )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            source="document",
                            data={
                                "message": (
                                    "I couldn't find enough information "
                                    "in the stored document to answer that, Sir."
                                )
                            }
                        )

                # Greeting can be handled entirely by PersonalityEngine.
                if intent.name == "greeting":
                    logger.info(
                        "[CognitiveCore] Greeting fast-path activated."
                    )

                    return SystemResponse(
                        success=True,
                        confidence=intent.confidence,
                        data={
                            "intent": "greeting",
                            "query": query
                        },
                        source="greeting_fast_path"
                    )

                # Explicit memory operations should go directly to the
                # memory conversation layer instead of requiring an LLM
                # response merely to verbalize stored information.
                if intent.name in (
                    "memory_recall",
                    "memory_delete",
                ):
                    logger.info(
                        "[CognitiveCore] Memory fast-path activated: %s",
                        intent.name
                    )

                    if self.memory_conversation_manager:

                        reply = await self.memory_conversation_manager.handle(
                            query=query,
                            context=ctx
                        )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            data={
                                "message": reply
                            },
                            source="memory_conversation"
                        )

            reasoning = None

            if self.reasoning_engine:
                reasoning = await self.reasoning_engine.reason(ctx)
                ctx["reasoning"] = reasoning

            state = ctx.get("state", {})

            logger.info(
                "[Document] Current state: %s",
                state
            )

            if state.get("active_document"):
                logger.info("[Document] Active document detected.")

            # ---------------------------------------------------------
            # Reasoning is complete.
            #
            # IMPORTANT:
            # Do NOT execute agents here.
            #
            # ReasoningEngine only recommends what ARIA should do.
            # DecisionEngine must make the final routing decision first.
            # The selected capability will be executed afterwards.
            # ---------------------------------------------------------

            if reasoning:
                logger.info(
                    "[CognitiveCore] Reasoning complete: "
                    "primary_action=%s confidence=%.2f",
                    reasoning.primary_action,
                    reasoning.confidence
                )

                ctx["reasoning"] = reasoning

            # 4. Decision Engine
            decision = None

            if self.decision_engine:
                decision = await self.decision_engine.decide(
                    context=ctx,
                    skill_manager=self.skill_manager,
                    planner=self.planner
                )

                logger.info(
                    "[Decision] Selected action: %s",
                    decision.action
                )

            logger.info(
                "[Decision] Selected action: %s",
                decision.action if decision else None
            )

            if decision:

                secondary_actions = []

                if hasattr(decision, "secondary_actions") and decision.secondary_actions:
                    secondary_actions = decision.secondary_actions

                # -----------------------------------------------------
                # Execute the agent workflow selected during reasoning.
                #
                # Reasoning chooses the appropriate specialised agents.
                # DecisionEngine confirms the execution route.
                # Only now are those agents allowed to execute.
                # -----------------------------------------------------

                if (
                    reasoning
                    and reasoning.workflow
                    and len(reasoning.workflow) > 0
                    and decision.action not in (
                        "memory_conversation",
                        "document",
                        "delete_document",
                        "delete_all_documents",
                        "reindex_documents",
                    )
                ):

                    agent_results = []

                    for agent in reasoning.workflow:

                        try:
                            logger.info(
                                "[CognitiveCore] Executing agent: %s",
                                agent.name
                            )

                            result = await agent.execute(
                                query,
                                ctx
                            )

                            if result and result.success:
                                agent_results.append(result)

                            elif result:
                                logger.warning(
                                    "[CognitiveCore] Agent %s failed: %s",
                                    agent.name,
                                    result.error
                                )

                        except Exception:
                            logger.exception(
                                "[CognitiveCore] Agent execution failed: %s",
                                getattr(agent, "name", "unknown")
                            )

                    if agent_results:

                        fused_response = self.response_fusion.combine(
                            agent_results
                        )

                        if fused_response:

                            logger.info(
                                "[CognitiveCore] Agent workflow produced "
                                "a usable response."
                            )

                            return SystemResponse(
                                success=True,
                                confidence=max(
                                    result.confidence
                                    for result in agent_results
                                ),
                                source="agent",
                                data={
                                    "response": fused_response
                                }
                            )

                # Memory Conversation
                if decision.action == "memory_conversation":
                    reply = ""
                    if self.memory_conversation_manager:
                        reply = await self.memory_conversation_manager.handle(
                            query=query,
                            context=ctx
                        )
                    else:
                        reply = "Memory conversation manager is unconfigured, Sir."

                    return SystemResponse(
                        success=True,
                        confidence=decision.confidence,
                        data={
                            "message": reply
                        },
                        source="memory"
                    )

                # Direct skill
                elif decision.action == "skill":
                    if self.skill_manager and hasattr(self.skill_manager, "route_and_execute"):
                        skill_res = await self.skill_manager.route_and_execute(query, ctx)

                        if skill_res:
                            return SystemResponse(
                                success=skill_res.success,
                                confidence=skill_res.confidence,
                                data=skill_res.data,
                                source=skill_res.source
                            )

                # Planner
                elif decision.action == "planner":
                    pass

                # Document
                elif decision.action == "document":

                    document_ai = ctx.get("document_intelligence")

                    if document_ai:

                        answer = await document_ai.answer_question(
                            session_id=session_id,
                            question=query,
                            state=ctx.get("state")
                        )

                        if self.state_manager:

                            self.state_manager.update_state(
                                session_id,
                                last_document_question=query,
                                last_document_answer=answer
                            )

                        if answer:

                            return SystemResponse(
                                success=True,
                                confidence=decision.confidence,
                                source="document",
                                data={
                                    "response": answer
                                }
                            )

                # Document Management Actions
                elif decision.action == "delete_document":

                    document_ai = ctx.get("document_intelligence")
                    doc_name = (decision.data or {}).get("document_name") if hasattr(decision, "data") else None

                    if document_ai and doc_name:
                        await document_ai.delete_document(
                            session_id=session_id,
                            document_name=doc_name,
                            user_id=user_id
                        )

                    if self.state_manager:
                        self.state_manager.clear_document_context(
                            session_id
                        )

                    return SystemResponse(
                        success=True,
                        confidence=decision.confidence,
                        source="document_management",
                        data={
                            "response": "Document deleted."
                        }
                    )

                elif decision.action == "delete_all_documents":

                    document_ai = ctx.get("document_intelligence")

                    if document_ai:
                        await document_ai.delete_all_documents(
                            session_id=session_id,
                            user_id=user_id
                        )

                    if self.state_manager:
                        self.state_manager.clear_document_context(
                            session_id
                        )

                    return SystemResponse(
                        success=True,
                        confidence=decision.confidence,
                        source="document_management",
                        data={
                            "response": "All uploaded documents deleted."
                        }
                    )

                elif decision.action == "reindex_documents":

                    document_ai = ctx.get("document_intelligence")

                    if document_ai:
                        await document_ai.reindex_documents(
                            session_id
                        )

                    return SystemResponse(
                        success=True,
                        confidence=decision.confidence,
                        source="document_management",
                        data={
                            "response": "Document index rebuilt."
                        }
                    )

                # Chat
                elif decision.action == "chat":
                    if self.skill_manager and hasattr(self.skill_manager, "route_and_execute"):
                        skill_res = await self.skill_manager.route_and_execute(query, ctx)

                        if skill_res:
                            return SystemResponse(
                                success=skill_res.success,
                                confidence=skill_res.confidence,
                                data=skill_res.data,
                                source=skill_res.source
                            )

            # 2. Otherwise, fall back to Planner + Executor Orchestration
            plan = None
            if self.planner and hasattr(self.planner, "create_plan"):
                plan = await self.planner.create_plan(query, ctx)
            elif self.planner and hasattr(self.planner, "plan"):
                # Handle sync planner if applicable
                plan = self.planner.plan(query, ctx)

            # Graceful handling if planner returns empty or no tasks
            if not plan or not getattr(plan, "tasks", None):
                return SystemResponse(
                    success=True,
                    confidence=getattr(plan, "confidence", 0.5),
                    data={"intent": "conversational", "query": query},
                    source="planner_conversational"
                )

            # 3. Execute the generated plan
            exec_result = {}
            if self.executor and hasattr(self.executor, "execute_plan"):
                exec_result = await self.executor.execute_plan(plan, ctx)
            elif self.executor and hasattr(self.executor, "execute"):
                exec_result = self.executor.execute(plan, ctx)

            final_data = exec_result.get("task_outputs", {}) if isinstance(exec_result, dict) else exec_result
            success = exec_result.get("success", True) if isinstance(exec_result, dict) else True

            if self.state_manager:
                self.state_manager.update_state(
                    session_id,
                    last_action="planner_executor",
                    last_success=success
                )

            # Execute any secondary actions
            if (
                success
                and secondary_actions
                and "chat" not in final_data
            ):

                for action in secondary_actions:

                    if action != "chat":
                        continue

                    chat_res = await self.skill_manager.route_and_execute(
                        query,
                        ctx
                    )

                    if chat_res and chat_res.success:

                        final_data["chat"] = chat_res.data

                        break

            return SystemResponse(
                success=success,
                confidence=getattr(plan, "confidence", 0.85),
                data=final_data,
                source="planner_executor",
                error=None if success else "Orchestration tasks encountered failures."
            )

        except Exception as e:
            logger.exception("[CognitiveCore ERROR] Processing failed: %s", e)
            return SystemResponse(
                success=False,
                confidence=0.0,
                source="cognitive_core",
                error=str(e)
            )
