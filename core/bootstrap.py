import os
import logging
import asyncio
from core.config import Config
from core.dependency_injection import ServiceRegistry
from memory.mongo_client import MongoClient
from memory.memory_engine import MemoryEngine
from memory.vector_store import VectorStore
from brain.document.document_intelligence import DocumentIntelligence
from brain.agents.agent_manager import AgentManager
from brain.session.session_manager import SessionManager
from brain.state.state_manager import StateManager
from brain.skills.skill_manager import SkillManager
from brain.actions.action_manager import ActionManager
from brain.planner.planner import Planner
from brain.executor.executor import Executor
from brain.core.cognitive_core import CognitiveCore
from personality.personality_engine import PersonalityEngine
from brain.context.context_manager import ContextManager
from brain.decision.decision_engine import DecisionEngine
from brain.intent.intent_analyzer import IntentAnalyzer
from brain.reasoning.reasoning_engine import ReasoningEngine
from brain.llm.llm_router import LLMRouter

logger = logging.getLogger("aria")


async def bootstrap_application() -> ServiceRegistry:
    logger.info("[BOOT TEST] 1 - Bootstrap started")

    config = Config()
    registry = ServiceRegistry()
    registry.register("config", config)

    # Database connections
    logger.info("[BOOT TEST] 2 - Starting ChromaDB")
    vector_store = VectorStore(
        collection_name="aria_memory",
        persist_directory=getattr(config, "chroma_db_dir", "./chroma_db")
    )
    registry.register("vector_db", vector_store)
    logger.info("[BOOT TEST] 3 - ChromaDB finished")

    logger.info("[BOOT TEST] 4 - Starting MemoryEngine")
    mongo_client = MongoClient(config.mongo_uri, config.mongo_db_name)
    db_inst = mongo_client.get_database()
    memory_engine = MemoryEngine(db_inst)
    registry.register("mongo_client", mongo_client)
    registry.register("memory_engine", memory_engine)

    llm_router = LLMRouter(config)
    registry.register("llm_router", llm_router)

    logger.info("[BOOT TEST] 5 - Creating DocumentIntelligence")
    doc_intelligence = DocumentIntelligence(
        memory_engine=memory_engine,
        llm_router=llm_router,
        vector_db=vector_store
    )
    registry.register("document_intelligence", doc_intelligence)
    logger.info("[BOOT TEST] 6 - DocumentIntelligence created")

    logger.info("[BOOT TEST] 7 - Starting AgentManager")
    agent_manager = AgentManager()
    registry.register("agent_manager", agent_manager)

    session_manager = SessionManager()
    state_manager = StateManager()
    skill_manager = SkillManager()
    action_manager = ActionManager()
    planner = Planner()
    executor = Executor()
    personality_engine = PersonalityEngine()
    context_manager = ContextManager()
    decision_engine = DecisionEngine()
    intent_analyzer = IntentAnalyzer()
    reasoning_engine = ReasoningEngine()

    registry.register("session_manager", session_manager)
    registry.register("state_manager", state_manager)
    registry.register("skill_manager", skill_manager)
    registry.register("action_manager", action_manager)
    registry.register("planner", planner)
    registry.register("executor", executor)
    registry.register("personality_engine", personality_engine)
    registry.register("context_manager", context_manager)
    registry.register("decision_engine", decision_engine)
    registry.register("intent_analyzer", intent_analyzer)
    registry.register("reasoning_engine", reasoning_engine)

    cognitive_core = CognitiveCore(
        planner=planner,
        executor=executor,
        skill_manager=skill_manager,
        memory_router=memory_engine,
        state_manager=state_manager,
        intent_analyzer=intent_analyzer,
        context_builder=context_manager,
        decision_engine=decision_engine,
        reasoning_engine=reasoning_engine
    )
    registry.register("cognitive_core", cognitive_core)

    logger.info("[BOOT TEST] 8 - BOOTSTRAP COMPLETE")
    return registry
