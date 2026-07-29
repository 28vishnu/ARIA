import logging

from motor.motor_asyncio import AsyncIOMotorClient
import chromadb

from core.configuration import load_config
from core.dependency_injection import ServiceRegistry

from brain.memory.memory_engine import MemoryEngine
from brain.document.document_intelligence import DocumentIntelligence
from brain.agents.agent_manager import AgentManager
from brain.session import SessionManager
from brain.state.state_manager import StateManager

from skills.manager import SkillManager
from skills.chat import ChatSkill
from skills.document import DocumentSkill
from skills.memory import MemorySkill
from skills.profile import ProfileSkill

from brain.planner import Planner
from brain.executor import Executor
from brain.core.cognitive_core import CognitiveCore

from personality.engine import PersonalityEngine
from brain.context.context_manager import ContextBuilder
from brain.decision.decision_engine import DecisionEngine
from brain.intent.intent_analyzer import IntentAnalyzer
from brain.reasoning.reasoning_engine import ReasoningEngine
from brain.llm.llm_router import LLMRouter


logger = logging.getLogger("aria")


async def bootstrap_application() -> ServiceRegistry:

    logger.info("[BOOT TEST] 1 - Bootstrap started")

    # ---------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------

    config = load_config()

    registry = ServiceRegistry()

    registry.register(
        "config",
        config
    )

    # ---------------------------------------------------------
    # MongoDB
    # ---------------------------------------------------------

    logger.info("[BOOT TEST] 2 - Starting MongoDB")

    mongo_client = None
    memory_engine = None

    if config.mongodb_uri:

        mongo_client = AsyncIOMotorClient(
            config.mongodb_uri
        )

        db_inst = mongo_client["aria_db"]

        memory_engine = MemoryEngine(
            db_inst
        )

        registry.register(
            "mongo_client",
            mongo_client
        )

        registry.register(
            "memory_engine",
            memory_engine
        )

        logger.info(
            "[BOOT TEST] 3 - MongoDB configured"
        )

    else:

        logger.warning(
            "[BOOT TEST] MongoDB disabled because MONGODB_URI is empty"
        )

    # ---------------------------------------------------------
    # ChromaDB
    # ---------------------------------------------------------

    logger.info(
        "[BOOT TEST] 4 - Starting ChromaDB"
    )

    chroma_client = chromadb.PersistentClient(
        path=config.vector_persist_path
    )

    vector_store = chroma_client.get_or_create_collection(
        name="aria_memory"
    )

    registry.register(
        "vector_db",
        vector_store
    )

    logger.info(
        "[BOOT TEST] 5 - ChromaDB configured"
    )

    # ---------------------------------------------------------
    # LLM Router
    # ---------------------------------------------------------

    llm_router = LLMRouter(
        config
    )

    registry.register(
        "llm_router",
        llm_router
    )

    # ---------------------------------------------------------
    # Document Intelligence
    # ---------------------------------------------------------

    logger.info(
        "[BOOT TEST] 6 - Creating DocumentIntelligence"
    )

    doc_intelligence = DocumentIntelligence(
        memory_engine=memory_engine,
        llm_router=llm_router,
        vector_db=vector_store
    )

    registry.register(
        "document_intelligence",
        doc_intelligence
    )

    logger.info(
        "[BOOT TEST] 7 - DocumentIntelligence created"
    )

    # ---------------------------------------------------------
    # Agent Manager
    # ---------------------------------------------------------

    logger.info(
        "[BOOT TEST] 8 - Starting AgentManager"
    )

    agent_manager = AgentManager()

    registry.register(
        "agent_manager",
        agent_manager
    )

    # ---------------------------------------------------------
    # Core Services
    # ---------------------------------------------------------

    context_builder = ContextBuilder()
    state_manager = StateManager()

    session_manager = SessionManager(state_manager)

    skill_manager = SkillManager()

    skill_manager.register(ChatSkill())
    skill_manager.register(DocumentSkill())
    skill_manager.register(MemorySkill())
    skill_manager.register(ProfileSkill())

    planner = Planner(llm_router)
    executor = Executor(skill_manager)

    personality_engine = PersonalityEngine(
        llm_router=llm_router
    )

    decision_engine = DecisionEngine()
    intent_analyzer = IntentAnalyzer()

    reasoning_engine = ReasoningEngine(
        agent_manager=agent_manager
    )

    registry.register(
        "session_manager",
        session_manager
    )

    registry.register(
        "state_manager",
        state_manager
    )

    registry.register(
        "skill_manager",
        skill_manager
    )

    registry.register(
        "planner",
        planner
    )

    registry.register(
        "executor",
        executor
    )

    registry.register(
        "personality_engine",
        personality_engine
    )

    registry.register(
        "context_builder",
        context_builder
    )

    registry.register(
        "decision_engine",
        decision_engine
    )

    registry.register(
        "intent_analyzer",
        intent_analyzer
    )

    registry.register(
        "reasoning_engine",
        reasoning_engine
    )

    # ---------------------------------------------------------
    # Cognitive Core
    # ---------------------------------------------------------

    cognitive_core = CognitiveCore(
        planner=planner,
        executor=executor,
        skill_manager=skill_manager,
        memory_router=memory_engine,
        state_manager=state_manager,
        intent_analyzer=intent_analyzer,
        context_builder=context_builder,
        decision_engine=decision_engine,
        reasoning_engine=reasoning_engine
    )

    registry.register(
        "cognitive_core",
        cognitive_core
    )

    logger.info(
        "[BOOT TEST] 9 - BOOTSTRAP COMPLETE"
    )

    return registry
