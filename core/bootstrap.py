import logging

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
import chromadb

from core.configuration import load_config
from core.dependency_injection import ServiceRegistry

from brain.memory.memory_engine import MemoryEngine
from brain.memory.working_memory import WorkingMemory
from brain.memory.memory_router import MemoryRouter
from brain.memory.memory_conversation_manager import MemoryConversationManager
from brain.document.document_intelligence import DocumentIntelligence
from brain.knowledge.knowledge_manager import KnowledgeManager
from brain.knowledge.knowledge_database import KnowledgeDatabase
from brain.knowledge.knowledge_graph import KnowledgeGraph
from brain.knowledge.graph_builder import GraphBuilder
from brain.knowledge.learning_engine import LearningEngine
from brain.learning.autonomous_learning import AutonomousLearning
from brain.self_reflection.self_reflection import SelfReflection
from brain.world.world_model import WorldModel
from brain.world.context_builder import ContextBuilder as WorldContextBuilder
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
from skills.research import ResearchSkill

from actions.manager import ActionManager
from actions.actions.file import FileAction
from actions.actions.notification import NotificationAction
from actions.actions.web_search import WebSearchAction

from brain.planning.planner import Planner
from brain.executor import Executor
from brain.core.cognitive_core import CognitiveCore

from personality.engine import PersonalityEngine
from brain.context.context_builder import ContextBuilder
from brain.decision.decision_engine import DecisionEngine
from brain.intent.intent_analyzer import IntentAnalyzer
from brain.reasoning.reasoning_engine import ReasoningEngine
from brain.llm.llm_router import LLMRouter

from brain.events.event_bus import EventBus
from brain.events.event import Event
from brain.events import event_types


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

    # Connect semantic reasoning to memory conversation layer
    if memory_conversation_manager is not None:

        memory_conversation_manager.llm_router = llm_router

        logger.info(
            "[BOOT TEST] LLM Router connected to "
            "MemoryConversationManager"
        )

    # ---------------------------------------------------------
    # Document Intelligence & Knowledge Objects
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

    state_manager = StateManager()
    world_model = WorldModel(mongodb=db_inst if mongo_client else None)
    await world_model.load()

    knowledge_database = KnowledgeDatabase(
        mongo_collection=db_inst["knowledge"] if db_inst is not None else None,
        vector_db=vector_store,
    )
    knowledge_graph = KnowledgeGraph(
        mongodb=db_inst if mongo_client else None,
        vector_db=vector_store,
    )
    await knowledge_graph.load_graph()

    graph_builder = GraphBuilder(
        knowledge_graph
    )

    event_bus = EventBus()

    learning_engine = LearningEngine(
        knowledge_database=knowledge_database,
        memory_engine=memory_engine,
        knowledge_graph=knowledge_graph,
        graph_builder=graph_builder,
        event_bus=event_bus,
    )

    knowledge_manager = KnowledgeManager(
        document_ai=doc_intelligence,
        memory_engine=memory_engine,
        state_manager=state_manager,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
        learning_engine=learning_engine,
        world_model=world_model,
        memory_router=memory_engine,
    )

    # ---------------------------------------------------------
    # Memory Router Setup
    # ---------------------------------------------------------
    working_memory = WorkingMemory()
    memory_router = MemoryRouter(
        working_memory=working_memory,
        memory_engine=memory_engine,
        knowledge_engine=knowledge_manager,
        knowledge_graph=knowledge_graph,
        document_repository=document_repository,
    )
    registry.register("memory_router", memory_router)

    self_reflection = SelfReflection(
        memory_engine=memory_engine,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
        learning_engine=learning_engine,
    )

    autonomous_learning = AutonomousLearning(
        memory_engine=memory_engine,
        learning_engine=learning_engine,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
        world_model=world_model,
    )

    def register_event_listeners():
        event_bus.register_listener(event_types.RESPONSE_GENERATED, autonomous_learning)
        event_bus.register_listener(event_types.RESPONSE_GENERATED, self_reflection)
        event_bus.register_listener(event_types.DOCUMENT_UPLOADED, autonomous_learning)
        event_bus.register_listener(event_types.DOCUMENT_SUMMARIZED, autonomous_learning)
        event_bus.register_listener(event_types.WEB_SEARCH_FINISHED, autonomous_learning)
        event_bus.register_listener(event_types.PLAN_FINISHED, autonomous_learning)
        event_bus.register_listener(event_types.WORKFLOW_COMPLETED, self_reflection)
        event_bus.register_listener(event_types.TASK_FAILED, self_reflection)
        event_bus.register_listener(event_types.TASK_COMPLETED, autonomous_learning)
        event_bus.register_listener(event_types.WORKFLOW_COMPLETED, autonomous_learning)
        event_bus.register_listener(event_types.KNOWLEDGE_ADDED, knowledge_graph)
        event_bus.register_listener(event_types.KNOWLEDGE_ADDED, world_model)

    register_event_listeners()

    context_builder = ContextBuilder(
        state_manager=state_manager,
        world_model=world_model,
        memory_router=memory_router,
        knowledge_graph=knowledge_graph,
    )

    # Group registrations
    # ---------------------------------------------------------
    # Knowledge & Memory
    # ---------------------------------------------------------
    registry.register("knowledge_database", knowledge_database)
    registry.register("knowledge_graph", knowledge_graph)
    registry.register("world_model", world_model)
    registry.register("graph_builder", graph_builder)
    registry.register("knowledge_manager", knowledge_manager)

    # ---------------------------------------------------------
    # Learning & Events
    # ---------------------------------------------------------
    registry.register("learning_engine", learning_engine)
    registry.register("self_reflection", self_reflection)
    registry.register("autonomous_learning", autonomous_learning)
    registry.register("event_bus", event_bus)
    registry.register("context_builder", context_builder)

    logger.info(
        "[BOOT TEST] 7 - DocumentIntelligence created"
    )

    # ---------------------------------------------------------
    # Agents
    # ---------------------------------------------------------
    logger.info(
        "[BOOT TEST] 8 - Starting AgentManager"
    )

    agent_manager = AgentManager()

    # Register ARIA's specialist reasoning agents.
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
    # Skills & Actions
    # ---------------------------------------------------------

    session_manager = SessionManager(state_manager)

    skill_manager = SkillManager()

    skill_manager.register(ChatSkill())
    skill_manager.register(DocumentSkill())
    skill_manager.register(MemorySkill())
    skill_manager.register(ProfileSkill())
    skill_manager.register(ResearchSkill())

    # Action Manager
    action_manager = ActionManager(
        permission_mode=config.permission_mode
    )

    action_manager.register(FileAction())
    action_manager.register(NotificationAction())
    action_manager.register(WebSearchAction())

    planner = Planner(
        memory_router=memory_router,
        llm_router=llm_router,
        skill_manager=skill_manager,
        action_manager=action_manager,
        knowledge_manager=knowledge_manager,
        knowledge_graph=knowledge_graph,
        world_model=world_model,
        event_bus=event_bus,
    )

    executor = Executor(
        skill_manager=skill_manager,
        action_manager=action_manager,
        event_bus=event_bus,
        planner=planner,
        mongodb=db_inst if mongo_client else None,
    )

    personality_engine = PersonalityEngine(
        llm_router=llm_router
    )

    decision_engine = DecisionEngine(
        knowledge_manager=knowledge_manager,
        self_reflection=self_reflection,
    )
    intent_analyzer = IntentAnalyzer(
        llm_router=llm_router
    )

    reasoning_engine = ReasoningEngine(
        agent_manager=agent_manager,
        llm_router=llm_router,
        action_manager=action_manager,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
        world_model=world_model,
        event_bus=event_bus,
    )

    # ---------------------------------------------------------
    # Core Services & AI
    # ---------------------------------------------------------
    registry.register("session_manager", session_manager)
    registry.register("state_manager", state_manager)
    registry.register("skill_manager", skill_manager)
    registry.register("action_manager", action_manager)
    registry.register("planner", planner)
    registry.register("executor", executor)
    registry.register("personality_engine", personality_engine)
    registry.register("decision_engine", decision_engine)
    registry.register("intent_analyzer", intent_analyzer)
    registry.register("reasoning_engine", reasoning_engine)

    # ---------------------------------------------------------
    # Cognitive Core
    # ---------------------------------------------------------

    cognitive_core = CognitiveCore(
        planner=planner,
        executor=executor,
        skill_manager=skill_manager,
        action_manager=action_manager,
        memory_router=memory_router,
        state_manager=state_manager,
        intent_analyzer=intent_analyzer,
        context_builder=context_builder,
        decision_engine=decision_engine,
        memory_conversation_manager=memory_conversation_manager,
        reasoning_engine=reasoning_engine,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
        knowledge_manager=knowledge_manager,
        learning_engine=learning_engine,
        world_model=world_model,
        self_reflection=self_reflection,
        autonomous_learning=autonomous_learning,
        event_bus=event_bus,
    )

    registry.register(
        "cognitive_core",
        cognitive_core
    )

    await event_bus.publish(
        Event(
            type=event_types.SYSTEM_STARTUP,
            source="bootstrap",
            data={},
        )
    )

    logger.info(
        "[BOOT TEST] 9 - BOOTSTRAP COMPLETE"
    )

    return registry
