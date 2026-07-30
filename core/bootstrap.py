import logging

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
import chromadb

from core.configuration import load_config
from core.dependency_injection import ServiceRegistry

from brain.memory.memory_engine import MemoryEngine
from brain.memory.memory_conversation_manager import MemoryConversationManager
from brain.document.document_intelligence import DocumentIntelligence
from brain.document.document_repository import DocumentRepository
from brain.agents.agent_manager import AgentManager
from brain.agents.code_agent import CodeAgent
from brain.agents.math_agent import MathAgent
from brain.agents.planning_agent import PlanningAgent
from brain.agents.research_agent import ResearchAgent
from brain.agents.writing_agent import WritingAgent
from brain.session import SessionManager
from brain.state.state_manager import StateManager

from skills.manager import SkillManager
from skills.chat import ChatSkill
from skills.document import DocumentSkill
from skills.memory import MemorySkill
from skills.profile import ProfileSkill

from actions.manager import ActionManager
from actions.actions.file import FileAction
from actions.actions.notification import NotificationAction

from brain.planner import Planner
from brain.executor import Executor
from brain.core.cognitive_core import CognitiveCore

from personality.engine import PersonalityEngine
from brain.context.context_builder import ContextBuilder
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
    document_repository = None

    if config.mongodb_uri:

        mongo_client = AsyncIOMotorClient(
            config.mongodb_uri
        )

        db_inst = mongo_client["aria_db"]

        memory_engine = MemoryEngine(
            db_inst
        )

        document_repository = DocumentRepository(
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

        registry.register(
            "document_repository",
            document_repository
        )

        logger.info(
            "[BOOT TEST] 3 - MongoDB configured"
        )

    else:

        logger.warning(
            "[BOOT TEST] MongoDB disabled because MONGODB_URI is empty"
        )

    # ---------------------------------------------------------
    # Memory Conversation Manager
    # ---------------------------------------------------------

    memory_conversation_manager = None

    if memory_engine is not None:
        memory_conversation_manager = MemoryConversationManager(
            memory_engine=memory_engine
        )

        registry.register(
            "memory_conversation_manager",
            memory_conversation_manager
        )

        logger.info(
            "[BOOT TEST] MemoryConversationManager configured"
        )
    else:
        logger.warning(
            "[BOOT TEST] MemoryConversationManager disabled because MemoryEngine is unavailable"
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
    # HTTP Client
    # ---------------------------------------------------------

    http_client = httpx.AsyncClient(
        timeout=config.timeout_seconds
    )

    registry.register(
        "http_client",
        http_client
    )

    logger.info(
        "[BOOT TEST] HTTP client configured"
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

    # Connect LLM intelligence to long-term memory
    if memory_engine is not None:
        memory_engine.llm_router = llm_router

        logger.info(
            "[BOOT TEST] LLM Router connected to MemoryEngine"
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
        vector_db=vector_store,
        document_repository=document_repository
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

    # Register ARIA's specialist reasoning agents.
    # These agents allow the reasoning layer to dynamically select
    # expertise instead of relying entirely on hard-coded routing.
    agent_manager.register(CodeAgent())
    agent_manager.register(MathAgent())
    agent_manager.register(PlanningAgent())
    agent_manager.register(ResearchAgent())
    agent_manager.register(WritingAgent())

    registry.register(
        "agent_manager",
        agent_manager
    )

    logger.info(
        "[BOOT TEST] Registered %d specialist agents",
        len(agent_manager.agents)
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

    # Action Manager
    action_manager = ActionManager(
        permission_mode=config.permission_mode
    )

    # Register executable actions
    action_manager.register(FileAction())
    action_manager.register(NotificationAction())

    logger.info(
        "[BOOT TEST] Registered executable actions: %s",
        list(action_manager.actions.keys())
    )

    planner = Planner(llm_router)
    executor = Executor(skill_manager)

    personality_engine = PersonalityEngine(
        llm_router=llm_router
    )

    decision_engine = DecisionEngine()
    intent_analyzer = IntentAnalyzer(
        llm_router=llm_router
    )

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
        "action_manager",
        action_manager
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
        memory_conversation_manager=memory_conversation_manager,
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
