import logging
import os

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
from brain.agents.coordinator import AgentCoordinator
from brain.agents.lead_agent import LeadAgent
from brain.agents.code_agent import CodeAgent
from brain.agents.math_agent import MathAgent
from brain.agents.planning_agent import PlanningAgent
from brain.agents.research_agent import ResearchAgent
from brain.agents.writing_agent import WritingAgent
from brain.session import SessionManager
from brain.state.state_manager import StateManager
from brain.conversation.conversation_manager import ConversationManager
from brain.goals.goal_manager import GoalManager
from brain.tasks.task_manager import TaskManager

from brain.documents.manager import DocumentManager
from brain.documents.pipeline import DocumentPipeline
from brain.documents.indexing.chunker import Chunker
from brain.documents.indexing.concept_extractor import ConceptExtractor
from brain.documents.indexing.semantic_search import SemanticSearch
from brain.documents.memory.document_memory import DocumentMemory
from brain.documents.study.study_engine import StudyEngine
from brain.documents.study.flashcard_generator import FlashcardGenerator
from brain.documents.study.mcq_generator import MCQGenerator
from brain.documents.study.revision_engine import RevisionEngine
from brain.documents.parsers.pdf_parser import PDFParser
from brain.documents.parsers.docx_parser import DOCXParser
from brain.documents.parsers.image_parser import ImageParser
from brain.documents.parsers.zip_parser import ZIPParser
from brain.documents.repository.repo_analyzer import RepositoryAnalyzer
from brain.documents.repository.code_parser import CodeParser
from brain.documents.repository.dependency_graph import DependencyGraph
from brain.documents.repository.repository_memory import RepositoryMemory

from skills.manager import SkillManager
from skills.chat import ChatSkill
from skills.document import DocumentSkill
from skills.memory import MemorySkill
from skills.profile import ProfileSkill
from skills.research import ResearchSkill
from skills.calculator import CalculatorSkill

from actions.manager import ActionManager
from actions.actions.file import FileAction
from actions.actions.notification import NotificationAction
from actions.actions.web_search import WebSearchAction
from actions.actions.time import TimeAction
from actions.actions.weather import WeatherAction

from brain.tools.search_tool import SearchTool
from autonomy.scheduler import BackgroundScheduler
from automation_watchers import AutomationWatchers

from brain.planner import Planner
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
from core.health_checker import HealthChecker


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
    db_inst = None

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

    if memory_engine is not None:
        memory_engine.llm_router = llm_router

        logger.info(
            "[BOOT TEST] LLM Router connected to MemoryEngine"
        )

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

    if memory_engine is not None:
        memory_engine.learning_engine = learning_engine

        logger.info(
            "[Bootstrap] LearningEngine connected to MemoryEngine."
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
        event_bus=event_bus,
    )

    # ---------------------------------------------------------
    # Memory Router Setup
    # ---------------------------------------------------------

    working_memory = WorkingMemory()
    graph = working_memory.semantic().load_semantic_graph()

    if graph:
        semantic = working_memory.semantic()

        for node_id, node in graph.get("nodes", {}).items():
            semantic.add_node(
                node_id=node_id,
                node_type=node["node_type"],
                value=node["value"],
                metadata=node.get("metadata", {}),
            )

        for edge in graph.get("edges", []):
            semantic.add_relation(
                edge["source"],
                edge["relation"],
                edge["target"],
            )

        logger.info(
            "[Bootstrap] Semantic graph restored."
        )

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
        event_bus.register_listener(event_types.PLAN_COMPLETED, autonomous_learning)
        event_bus.register_listener(event_types.WORKFLOW_COMPLETED, self_reflection)
        event_bus.register_listener(event_types.TASK_FAILED, self_reflection)
        event_bus.register_listener(event_types.TASK_COMPLETED, autonomous_learning)
        event_bus.register_listener(event_types.WORKFLOW_COMPLETED, autonomous_learning)
        event_bus.register_listener(event_types.KNOWLEDGE_ADDED, knowledge_graph)
        event_bus.register_listener(event_types.KNOWLEDGE_ADDED, world_model)

    register_event_listeners()

    # ---------------------------------------------------------
    # Runtime Conversation Intelligence
    # ---------------------------------------------------------

    conversation_manager = ConversationManager(
        llm_router=llm_router
    )

    registry.register(
        "conversation_manager",
        conversation_manager
    )

    logger.info(
        "[BOOT TEST] ConversationManager configured"
    )

    goal_manager = GoalManager(
        working_memory=working_memory
    )

    task_manager = TaskManager()

    registry.register(
        "goal_manager",
        goal_manager
    )
    registry.register(
        "task_manager",
        task_manager,
    )

    context_builder = ContextBuilder(
        state_manager=state_manager,
        world_model=world_model,
        memory_router=memory_router,
        knowledge_graph=knowledge_graph,
        conversation_manager=conversation_manager,
        working_memory=working_memory,
    )

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
    # Knowledge & Learning Engine
    # ---------------------------------------------------------

    document_manager = DocumentManager()
    chunker = Chunker()
    concept_extractor = ConceptExtractor()
    document_memory = DocumentMemory()
    semantic_search = SemanticSearch(
        document_memory,
    )
    study_engine = StudyEngine(
        semantic_search,
        document_memory,
    )
    flashcard_generator = FlashcardGenerator(
        document_memory,
    )
    mcq_generator = MCQGenerator(
        document_memory,
    )
    revision_engine = RevisionEngine(
        document_memory,
    )
    repo_analyzer = RepositoryAnalyzer()
    code_parser = CodeParser()
    dependency_graph = DependencyGraph()
    repository_memory = RepositoryMemory()
    pipeline = DocumentPipeline(
        document_manager=document_manager,
        chunker=chunker,
        concept_extractor=concept_extractor,
        document_memory=document_memory,
        semantic_search=semantic_search,
    )

    document_manager.register_parser(".pdf", PDFParser())
    document_manager.register_parser(".docx", DOCXParser())
    document_manager.register_parser(".jpg", ImageParser())
    document_manager.register_parser(".jpeg", ImageParser())
    document_manager.register_parser(".png", ImageParser())
    document_manager.register_parser(".zip", ZIPParser())

    registry.register("document_manager", document_manager)
    registry.register("document_pipeline", pipeline)
    registry.register("chunker", chunker)
    registry.register("concept_extractor", concept_extractor)
    registry.register("document_memory", document_memory)
    registry.register("semantic_search", semantic_search)
    registry.register("study_engine", study_engine)
    registry.register("flashcard_generator", flashcard_generator)
    registry.register("mcq_generator", mcq_generator)
    registry.register("revision_engine", revision_engine)
    registry.register("repo_analyzer", repo_analyzer)
    registry.register("code_parser", code_parser)
    registry.register("dependency_graph", dependency_graph)
    registry.register("repository_memory", repository_memory)

    # ---------------------------------------------------------
    # Agents, Coordinator & Lead Agent
    # ---------------------------------------------------------

    logger.info(
        "[BOOT TEST] 8 - Starting AgentManager"
    )

    agent_manager = AgentManager()
    agent_coordinator = AgentCoordinator(agent_manager)
    lead_agent = LeadAgent()

    agent_manager.register(CodeAgent())
    agent_manager.register(MathAgent())
    agent_manager.register(PlanningAgent())
    agent_manager.register(ResearchAgent())
    agent_manager.register(WritingAgent())

    registry.register("agent_manager", agent_manager)
    registry.register("agent_coordinator", agent_coordinator)
    registry.register("lead_agent", lead_agent)

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
    skill_manager.register(CalculatorSkill())

    action_manager = ActionManager(
        permission_mode=config.permission_mode
    )

    action_manager.register(FileAction())
    action_manager.register(NotificationAction())
    action_manager.register(WebSearchAction())
    action_manager.register(TimeAction())
    action_manager.register(WeatherAction())

    # ---------------------------------------------------------
    # Phase 9 — Shared Real-World Intelligence
    # ---------------------------------------------------------

    # One shared search service is created at bootstrap. Actions,
    # watchers, and future integrations can reuse the same provider.
    search_tool = SearchTool(
        max_results=10,
        timeout=max(
            3.0,
            float(getattr(config, "timeout_seconds", 20.0)),
        ),
    )

    registry.register(
        "search_tool",
        search_tool,
    )

    logger.info(
        "[Bootstrap] SearchTool registered | available=%s",
        search_tool.is_available(),
    )

    # Reuse the same search provider in the action layer when supported.
    web_search_action = action_manager.get("web_search_action")
    if web_search_action is not None:
        try:
            web_search_action.search_tool = search_tool
            logger.info(
                "[Bootstrap] Shared SearchTool connected to WebSearchAction."
            )
        except Exception:
            logger.exception(
                "[Bootstrap] Failed to connect SearchTool to WebSearchAction."
            )

    # Shared autonomous scheduler.
    scheduler = BackgroundScheduler(
        max_concurrent_jobs=int(
            os.getenv("ARIA_MAX_CONCURRENT_JOBS", "5")
        ),
        default_timeout_seconds=float(
            os.getenv("ARIA_JOB_TIMEOUT_SECONDS", "300")
        ),
    )

    registry.register(
        "scheduler",
        scheduler,
    )

    # Real-world read-only watchers.
    tavily_client = getattr(
        web_search_action,
        "tavily",
        None,
    )

    automation_watchers = AutomationWatchers(
        tavily_client=tavily_client,
        telegram_token=getattr(config, "telegram_token", None),
        admin_chat_id=os.getenv("ADMIN_CHAT_ID"),
        search_tool=search_tool,
        http_timeout=max(
            3.0,
            float(getattr(config, "timeout_seconds", 20.0)),
        ),
    )

    registry.register(
        "automation_watchers",
        automation_watchers,
    )

    logger.info(
        "[Bootstrap] Phase 9 integrations ready | "
        "search=%s scheduler=%s watchers=%s",
        search_tool.is_available(),
        True,
        True,
    )

    planner = Planner(
        llm_router=llm_router,
    )

    executor = Executor(
        planner=planner,
        event_bus=event_bus,
        skill_manager=skill_manager,
        action_manager=action_manager,
        mongodb=db_inst if mongo_client else None,
        agent_manager=agent_manager,
        agent_coordinator=agent_coordinator,
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
        agent_coordinator=agent_coordinator,
        lead_agent=lead_agent,
        llm_router=llm_router,
        action_manager=action_manager,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
        world_model=world_model,
        event_bus=event_bus,
        working_memory=working_memory,
        goal_manager=goal_manager,
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

    # ---------- Cross Wiring ----------

    planner.executor = executor
    planner.memory_engine = memory_engine
    planner.reasoning_engine = reasoning_engine
    executor.planner = planner
    executor.memory_engine = memory_engine
    executor.reasoning_engine = reasoning_engine
    reasoning_engine.memory_engine = memory_engine
    reasoning_engine.planner = planner
    reasoning_engine.executor = executor
    decision_engine.reasoning_engine = reasoning_engine
    decision_engine.memory_engine = memory_engine
    agent_coordinator.reasoning_engine = reasoning_engine
    agent_coordinator.memory_engine = memory_engine

    if memory_engine is not None:
        memory_engine.reasoning_engine = reasoning_engine
        memory_engine.planner = planner

    logger.info("[Bootstrap] Cross wiring complete.")

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
        llm_router=llm_router,
        conversation_manager=conversation_manager,
        working_memory=working_memory,
        memory_engine=memory_engine,
        goal_manager=goal_manager,
        task_manager=task_manager,
        agent_coordinator=agent_coordinator,
        lead_agent=lead_agent,
        document_pipeline=pipeline,
        study_engine=study_engine,
        repository_memory=repository_memory,
    )

    registry.register(
        "cognitive_core",
        cognitive_core
    )

    health_checker = HealthChecker(registry)
    registry.register(
        "health_checker",
        health_checker
    )

    working_memory.semantic().save_semantic_graph()

    logger.info(
        "[Bootstrap] Semantic Graph: %s",
        working_memory.semantic_summary(),
    )

    await event_bus.publish(
        Event(
            type=event_types.SYSTEM_STARTED,
            source="bootstrap",
            data={},
        )
    )

    logger.info(
        "[BOOT TEST] 9 - BOOTSTRAP COMPLETE"
    )

    return registry
