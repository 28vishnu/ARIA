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
from brain.learning.experience_engine import ExperienceEngine
from brain.memory.jarvis_memory_system import JarvisMemorySystem
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

# =========================================================
# Phase 1 — Self-Engineering
# =========================================================

from brain.development.repository_manager import RepositoryManager
from brain.development.repository_intelligence import RepositoryIntelligence
from brain.development.source_analyzer import SourceAnalyzer
from brain.development.dependency_analyzer import DependencyAnalyzer
from brain.development.architecture_intelligence import ArchitectureIntelligence

from brain.development.workspace import DevelopmentWorkspace
from brain.development.filesystem_guard import FilesystemGuard
from brain.development.sandbox import DevelopmentSandbox

from brain.development.requirement_parser import RequirementParser
from brain.development.requirement_intelligence import RequirementIntelligence
from brain.development.change_planner import ChangePlanner
from brain.development.change_impact_planner import ChangeImpactPlanner
from brain.development.code_writer import CodeWriter

from brain.development.validator import DevelopmentValidator
from brain.development.test_runner import DevelopmentTestRunner
from brain.development.failure_analyzer import FailureAnalyzer
from brain.development.repair_engine import RepairEngine

from brain.development.development_agent import DevelopmentAgent
from brain.development.development_controller import DevelopmentController

from brain.development.git_manager import GitManager
from brain.development.github_manager import GitHubManager
from brain.development.github_sync import GitHubSync
from brain.development.git_branch_lifecycle import GitBranchLifecycle
from brain.development.github_project_creator import GitHubProjectCreator
from brain.development.research_service import RealTimeResearch

from brain.development.build_manager import BuildManager
from brain.development.deployment_manager import DeploymentManager
from brain.development.health_monitor import HealthMonitor
from brain.development.rollback_manager import RollbackManager

from brain.development.approval_manager import ApprovalManager
from brain.development.deployment_policy import DeploymentPolicy
from brain.development.telegram_approval_interface import (
    TelegramApprovalInterface,
)

from brain.integration.phase1_runtime import create_phase1_runtime
from brain.development.phase1_persistent_runtime_adapter import (
    Phase1PersistentRuntimeAdapter,
)
from brain.development.phase1_readiness_gateway import (
    Phase1ReadinessGateway,
)
from brain.integration.phase1_capability_hub import Phase1CapabilityHub
from brain.integration.phase1_delivery_gateway import Phase1DeliveryGateway
from brain.development.engineering_execution_mode import EngineeringExecutionMode
from brain.development.autonomous_engineering_lifecycle import AutonomousEngineeringLifecycle
from brain.development.master_delivery_authorization import MasterDeliveryAuthorization
from brain.integration.multimodal_capability_gateway import MultimodalCapabilityGateway
from brain.core.jarvis_final_integration import JarvisFinalIntegration

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
from brain.tools.tool_manager import ToolManager
from brain.tools.calculator_tool import CalculatorTool
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
from brain.development.code_generation_router import CodeGenerationRouter
from brain.development.local_code_model import LocalCodeModel
from brain.development.code_generation_bridge import LLMCodeGenerationBridge

from brain.events.event_bus import EventBus
from brain.events.event import Event
from brain.events import event_types
from core.health_checker import HealthChecker


logger = logging.getLogger("aria")


# =========================================================
# Local Knowledge Configuration
# =========================================================

KNOWLEDGE_VECTOR_COLLECTION = "aria_knowledge_minilm_v1"
LEGACY_VECTOR_COLLECTION = "aria_memory"


async def bootstrap_application() -> ServiceRegistry:

    logger.info("[BOOT TEST] 1 - Bootstrap started")

    # ---------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------

    config = load_config()

    registry = ServiceRegistry()

    registry.register(
        "config",
        config,
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
            mongo_client,
        )

        registry.register(
            "memory_engine",
            memory_engine,
        )

        registry.register(
            "document_repository",
            document_repository,
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
            memory_conversation_manager,
        )

        logger.info(
            "[BOOT TEST] MemoryConversationManager configured"
        )

    else:

        logger.warning(
            "[BOOT TEST] MemoryConversationManager disabled because "
            "MemoryEngine is unavailable"
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
        name=LEGACY_VECTOR_COLLECTION
    )

    knowledge_vector_store = chroma_client.get_or_create_collection(
        name=KNOWLEDGE_VECTOR_COLLECTION
    )

    registry.register(
        "vector_db",
        vector_store,
    )

    registry.register(
        "knowledge_vector_db",
        knowledge_vector_store,
    )

    logger.info(
        "[BOOT TEST] 5 - ChromaDB configured | "
        "legacy=%s | knowledge=%s | local_embedding_dim=384",
        LEGACY_VECTOR_COLLECTION,
        KNOWLEDGE_VECTOR_COLLECTION,
    )

    # ---------------------------------------------------------
    # HTTP Client
    # ---------------------------------------------------------

    http_client = httpx.AsyncClient(
        timeout=config.timeout_seconds
    )

    registry.register(
        "http_client",
        http_client,
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
        llm_router,
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
        document_repository=document_repository,
    )

    registry.register(
        "document_intelligence",
        doc_intelligence,
    )

    state_manager = StateManager()

    world_model = WorldModel(
        mongodb=db_inst if mongo_client else None
    )

    await world_model.load()

    # ---------------------------------------------------------
    # Knowledge Database
    # ---------------------------------------------------------

    knowledge_database = KnowledgeDatabase(
        mongo_collection=(
            db_inst["knowledge"]
            if db_inst is not None
            else None
        ),
        vector_db=knowledge_vector_store,
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

    # ---------------------------------------------------------
    # Knowledge Manager
    # ---------------------------------------------------------

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

    registry.register(
        "memory_router",
        memory_router,
    )

    # ---------------------------------------------------------
    # Step 5 — Canonical JARVIS Memory / Project Memory
    # ---------------------------------------------------------

    # RepositoryMemory is required by the canonical JARVIS memory system.
    # It must be created before JarvisMemorySystem is constructed.
    repository_memory = RepositoryMemory()

    experience_engine = ExperienceEngine(
        mongo_db=db_inst,
        learning_engine=learning_engine,
        knowledge_database=knowledge_database,
    )

    registry.register(
        "experience_engine",
        experience_engine,
    )

    jarvis_memory_system = JarvisMemorySystem(
        working_memory=working_memory,
        memory_engine=memory_engine,
        memory_router=memory_router,
        repository_memory=repository_memory,
        experience_engine=experience_engine,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
    )

    registry.register(
        "jarvis_memory_system",
        jarvis_memory_system,
    )

    logger.info(
        "[Phase5] JARVIS memory system ready | healthy=%s | "
        "personal=%s | project=%s | experience=%s",
        jarvis_memory_system.health().get("healthy"),
        memory_engine is not None,
        repository_memory is not None,
        experience_engine is not None,
    )

    # ---------------------------------------------------------
    # Self Reflection
    # ---------------------------------------------------------

    self_reflection = SelfReflection(
        memory_engine=memory_engine,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
        learning_engine=learning_engine,
    )

    # ---------------------------------------------------------
    # Autonomous Learning
    # ---------------------------------------------------------

    autonomous_learning = AutonomousLearning(
        memory_engine=memory_engine,
        learning_engine=learning_engine,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
        world_model=world_model,
    )

    # ---------------------------------------------------------
    # Event Listeners
    # ---------------------------------------------------------

    def register_event_listeners():

        event_bus.register_listener(
            event_types.RESPONSE_GENERATED,
            autonomous_learning,
        )

        event_bus.register_listener(
            event_types.RESPONSE_GENERATED,
            self_reflection,
        )

        event_bus.register_listener(
            event_types.DOCUMENT_UPLOADED,
            autonomous_learning,
        )

        event_bus.register_listener(
            event_types.DOCUMENT_SUMMARIZED,
            autonomous_learning,
        )

        event_bus.register_listener(
            event_types.PLAN_COMPLETED,
            autonomous_learning,
        )

        event_bus.register_listener(
            event_types.WORKFLOW_COMPLETED,
            self_reflection,
        )

        event_bus.register_listener(
            event_types.TASK_FAILED,
            self_reflection,
        )

        event_bus.register_listener(
            event_types.TASK_COMPLETED,
            autonomous_learning,
        )

        event_bus.register_listener(
            event_types.WORKFLOW_COMPLETED,
            autonomous_learning,
        )

        event_bus.register_listener(
            event_types.KNOWLEDGE_ADDED,
            knowledge_graph,
        )

        event_bus.register_listener(
            event_types.KNOWLEDGE_ADDED,
            world_model,
        )

    register_event_listeners()

    # ---------------------------------------------------------
    # Runtime Conversation Intelligence
    # ---------------------------------------------------------

    conversation_manager = ConversationManager(
        llm_router=llm_router
    )

    registry.register(
        "conversation_manager",
        conversation_manager,
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
        goal_manager,
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

    registry.register(
        "knowledge_database",
        knowledge_database,
    )

    registry.register(
        "knowledge_graph",
        knowledge_graph,
    )

    registry.register(
        "world_model",
        world_model,
    )

    registry.register(
        "graph_builder",
        graph_builder,
    )

    registry.register(
        "knowledge_manager",
        knowledge_manager,
    )

    # ---------------------------------------------------------
    # Learning & Events
    # ---------------------------------------------------------

    registry.register(
        "learning_engine",
        learning_engine,
    )

    registry.register(
        "self_reflection",
        self_reflection,
    )

    registry.register(
        "autonomous_learning",
        autonomous_learning,
    )

    registry.register(
        "event_bus",
        event_bus,
    )

    registry.register(
        "context_builder",
        context_builder,
    )

    logger.info(
        "[BOOT TEST] 7 - DocumentIntelligence created"
    )

    # ---------------------------------------------------------
    # Document & Learning Engine
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

    # ---------------------------------------------------------
    # Phase 1 — Repository Intelligence
    # ---------------------------------------------------------

    repository_manager = RepositoryManager(
        max_file_size_bytes=int(
            os.getenv(
                "ARIA_REPOSITORY_MAX_FILE_SIZE",
                str(10 * 1024 * 1024),
            )
        ),
    )

    source_analyzer = SourceAnalyzer()
    dependency_analyzer = DependencyAnalyzer()

    architecture_intelligence = ArchitectureIntelligence(
        repository_manager=repository_manager,
        source_analyzer=source_analyzer,
        dependency_analyzer=dependency_analyzer,
        max_source_files=int(
            os.getenv(
                "ARIA_ARCHITECTURE_MAX_SOURCE_FILES",
                "2000",
            )
        ),
    )

    registry.register(
        "repository_manager",
        repository_manager,
    )

    registry.register(
        "source_analyzer",
        source_analyzer,
    )

    registry.register(
        "dependency_analyzer",
        dependency_analyzer,
    )

    registry.register(
        "architecture_intelligence",
        architecture_intelligence,
    )

    logger.info(
        "[Phase1] Repository intelligence registered | "
        "read_only=True | root=%s",
        os.getcwd(),
    )

    # ---------------------------------------------------------
    # Phase 1 — Development Workspace
    # ---------------------------------------------------------

    workspace_root = os.getenv(
        "ARIA_DEVELOPMENT_WORKSPACE_ROOT",
        os.path.join(
            os.getcwd(),
            ".aria_workspaces",
        ),
    )

    development_workspace = DevelopmentWorkspace(
        repository_root=os.getcwd(),
        workspace_base=workspace_root,
        max_workspaces=int(
            os.getenv(
                "ARIA_MAX_DEVELOPMENT_WORKSPACES",
                "3",
            )
        ),
    )

    registry.register(
        "development_workspace",
        development_workspace,
    )

    logger.info(
        "[Phase1] DevelopmentWorkspace registered | root=%s",
        workspace_root,
    )

    # ---------------------------------------------------------
    # Phase 1 — Workspace-scoped factories
    # ---------------------------------------------------------

    registry.register(
        "filesystem_guard_factory",
        FilesystemGuard,
    )

    registry.register(
        "development_sandbox_factory",
        DevelopmentSandbox,
    )

    registry.register(
        "code_writer_factory",
        CodeWriter,
    )

    registry.register(
        "validator_factory",
        DevelopmentValidator,
    )

    registry.register(
        "test_runner_factory",
        DevelopmentTestRunner,
    )

    registry.register(
        "build_manager_factory",
        BuildManager,
    )

    # ---------------------------------------------------------
    # Phase 1 — Requirement / Planning Services
    # ---------------------------------------------------------

    requirement_parser = RequirementParser()
    requirement_intelligence = RequirementIntelligence(
        requirement_parser
    )

    change_planner = ChangePlanner()

    change_impact_planner = ChangeImpactPlanner(
        architecture_intelligence,
        max_targets=int(
            os.getenv(
                "ARIA_CHANGE_IMPACT_MAX_TARGETS",
                "40",
            )
        ),
        max_dependency_hops=int(
            os.getenv(
                "ARIA_CHANGE_IMPACT_MAX_HOPS",
                "2",
            )
        ),
    )

    registry.register(
        "requirement_parser",
        requirement_parser,
    )

    registry.register(
        "requirement_intelligence",
        requirement_intelligence,
    )

    registry.register(
        "change_planner",
        change_planner,
    )

    registry.register(
        "change_impact_planner",
        change_impact_planner,
    )

    # ---------------------------------------------------------
    # Phase 1 — Failure / Repair Services
    # ---------------------------------------------------------

    failure_analyzer = FailureAnalyzer()

    repair_engine = RepairEngine(
        max_attempts=int(
            os.getenv(
                "ARIA_REPAIR_MAX_ATTEMPTS",
                "3",
            )
        ),
    )

    registry.register(
        "failure_analyzer",
        failure_analyzer,
    )

    registry.register(
        "repair_engine",
        repair_engine,
    )

    # ---------------------------------------------------------
    # Phase 1 — Git / GitHub
    # ---------------------------------------------------------

    git_manager = GitManager(
        repository_root=os.getcwd(),
    )

    github_manager = GitHubManager(
        git_manager=git_manager,
        allow_push=False,
    )

    registry.register(
        "git_manager",
        git_manager,
    )

    registry.register(
        "github_manager",
        github_manager,
    )

    # ---------------------------------------------------------
    # Step 2 — Canonical Repository Intelligence
    # ---------------------------------------------------------

    repository_intelligence = RepositoryIntelligence(
        repository_manager=repository_manager,
        architecture_intelligence=architecture_intelligence,
        git_manager=git_manager,
        github_manager=github_manager,
    )

    registry.register(
        "repository_intelligence",
        repository_intelligence,
    )

    logger.info(
        "[Phase2] Repository intelligence ready | version=%s | root=%s",
        repository_intelligence.VERSION,
        repository_intelligence.repository_root,
    )

    # ---------------------------------------------------------
    # Phase 1 — GitHub Synchronization / Branch Lifecycle
    # ---------------------------------------------------------

    github_sync = GitHubSync(
        git_manager=git_manager,
        github_manager=github_manager,
        command_timeout=float(
            os.getenv(
                "ARIA_GITHUB_SYNC_TIMEOUT",
                "180",
            )
        ),
    )

    git_branch_lifecycle = GitBranchLifecycle(
        git_manager=git_manager,
        prefix=os.getenv(
            "ARIA_AUTONOMOUS_BRANCH_PREFIX",
            "aria/auto",
        ),
    )

    registry.register(
        "github_sync",
        github_sync,
    )

    registry.register(
        "git_branch_lifecycle",
        git_branch_lifecycle,
    )

    # ---------------------------------------------------------
    # Phase 1 — New Project / Repository Creation
    # ---------------------------------------------------------

    project_workspace_root = os.getenv(
        "ARIA_PROJECTS_ROOT",
        os.path.join(
            os.getcwd(),
            "projects",
        ),
    )

    github_project_creator = GitHubProjectCreator(
        workspace_root=project_workspace_root,
        api_timeout=float(
            os.getenv(
                "ARIA_GITHUB_PROJECT_TIMEOUT",
                "60",
            )
        ),
    )

    registry.register(
        "github_project_creator",
        github_project_creator,
    )

    logger.info(
        "[Phase1] Project creation capability registered | "
        "workspace_root=%s | remote_authorization_required=%s",
        project_workspace_root,
        True,
    )

    # ---------------------------------------------------------
    # Phase 1 — Build / Deployment / Health / Rollback
    # ---------------------------------------------------------

    deployment_manager = DeploymentManager(
        git_manager=git_manager,
        allow_staging=(
            os.getenv(
                "ARIA_ALLOW_STAGING_DEPLOYMENT",
                "true",
            ).lower()
            in {"1", "true", "yes", "on"}
        ),
        allow_production=False,
    )

    health_monitor = HealthMonitor()

    rollback_manager = RollbackManager(
        git_manager=git_manager,
    )

    registry.register(
        "deployment_manager",
        deployment_manager,
    )

    registry.register(
        "health_monitor",
        health_monitor,
    )

    registry.register(
        "rollback_manager",
        rollback_manager,
    )

    # ---------------------------------------------------------
    # Phase 1 — Approval / Deployment Policy
    # ---------------------------------------------------------

    approval_manager = ApprovalManager()

    deployment_policy = DeploymentPolicy()

    telegram_approval_interface = TelegramApprovalInterface(
        approval_manager=approval_manager,
    )

    registry.register(
        "approval_manager",
        approval_manager,
    )

    registry.register(
        "telegram_approval_interface",
        telegram_approval_interface,
    )

    registry.register(
        "deployment_policy",
        deployment_policy,
    )

    logger.info(
        "[Phase1][TelegramApproval] Telegram approval interface "
        "registered | master_only=True | fail_closed=True"
    )

    # ---------------------------------------------------------
    # Phase 1 — LLM Code Generation Bridge
    # ---------------------------------------------------------

    local_code_model = LocalCodeModel(
        backend=os.getenv(
            "ARIA_LOCAL_CODEGEN_BACKEND",
            "ollama",
        ),
        base_url=os.getenv(
            "ARIA_LOCAL_CODEGEN_URL",
            "http://127.0.0.1:11434",
        ),
        model=os.getenv(
            "ARIA_LOCAL_CODEGEN_MODEL",
            "qwen2.5-coder:7b",
        ),
        timeout=float(
            os.getenv(
                "ARIA_LOCAL_CODEGEN_TIMEOUT",
                "180",
            )
        ),
    )

    registry.register(
        "local_code_model",
        local_code_model,
    )

    code_generation_router = CodeGenerationRouter(
        config=config,
        provider=os.getenv(
            "ARIA_CODEGEN_PROVIDER",
            "groq",
        ),
        allow_fallback=os.getenv(
            "ARIA_CODEGEN_ALLOW_FALLBACK",
            "false",
        ),
        max_input_chars=int(
            os.getenv(
                "ARIA_CODEGEN_MAX_INPUT_CHARS",
                "60000",
            )
        ),
    )

    code_generation_router.local_model = local_code_model

    registry.register(
        "code_generation_router",
        code_generation_router,
    )

    code_generation_bridge = LLMCodeGenerationBridge(
        code_generation_router=code_generation_router,
        temperature=float(
            os.getenv(
                "ARIA_CODE_GENERATION_TEMPERATURE",
                "0.15",
            )
        ),
        max_tokens=int(
            os.getenv(
                "ARIA_CODE_GENERATION_MAX_TOKENS",
                "16384",
            )
        ),
    )

    registry.register(
        "code_generation_bridge",
        code_generation_bridge,
    )

    development_agent = DevelopmentAgent(
        repository_manager=repository_manager,
        workspace_manager=development_workspace,
        code_generator=code_generation_bridge,
        requirement_intelligence=requirement_intelligence,
        architecture_intelligence=architecture_intelligence,
        change_impact_planner=change_impact_planner,
        max_repair_attempts=int(
            os.getenv(
                "ARIA_REPAIR_MAX_ATTEMPTS",
                "3",
            )
        ),
    )

    registry.register(
        "development_agent",
        development_agent,
    )

    # ---------------------------------------------------------
    # Phase 1 — Development Controller
    # ---------------------------------------------------------

    development_controller = DevelopmentController(
        agent=development_agent,
    )

    registry.register(
        "development_controller",
        development_controller,
    )

    # ---------------------------------------------------------
    # Phase 1 — Autonomous Runtime Integration
    # ---------------------------------------------------------

    legacy_phase1_runtime = create_phase1_runtime(
        development_controller=development_controller,
        git_manager=git_manager,
        github_manager=github_manager,
        deployment_manager=deployment_manager,
        memory_engine=memory_engine,
        knowledge_database=knowledge_database,
        knowledge_graph=knowledge_graph,
        document_ai=doc_intelligence,
    )

    # Expose the canonical repository-understanding service to the
    # Phase1PersistentRuntimeAdapter. The adapter then injects it into
    # FinalAutonomousEngineer as repository_engine.
    legacy_phase1_runtime.components[
        "repository_engine"
    ] = repository_intelligence

    phase1_runtime = Phase1PersistentRuntimeAdapter(
        legacy_phase1_runtime,
        development_controller=development_controller,
    )

    phase1_readiness_gateway = Phase1ReadinessGateway(
        runtime=phase1_runtime,
    )

    registry.register(
        "phase1_readiness_gateway",
        phase1_readiness_gateway,
    )

    registry.register(
        "phase1_runtime",
        phase1_runtime,
    )

    logger.info(
        "[Phase1] Autonomous runtime integration registered | "
        "healthy=%s | components=%s",
        phase1_runtime.health()["healthy"],
        phase1_runtime.status()["component_count"],
    )

    # ---------------------------------------------------------
    # Phase 1 — Capability Registry
    # ---------------------------------------------------------

    registry.register(
        "phase1_capability_registry",
        {
            "repository_manager": repository_manager,
            "source_analyzer": source_analyzer,
            "dependency_analyzer": dependency_analyzer,
            "architecture_intelligence": architecture_intelligence,
            "development_workspace": development_workspace,
            "requirement_parser": requirement_parser,
            "requirement_intelligence": requirement_intelligence,
            "change_planner": change_planner,
            "change_impact_planner": change_impact_planner,
            "filesystem_guard_factory": FilesystemGuard,
            "development_sandbox_factory": DevelopmentSandbox,
            "code_writer_factory": CodeWriter,
            "validator_factory": DevelopmentValidator,
            "test_runner_factory": DevelopmentTestRunner,
            "failure_analyzer": failure_analyzer,
            "repair_engine": repair_engine,
            "code_generation_router": code_generation_router,
            "local_code_model": local_code_model,
            "code_generation_bridge": code_generation_bridge,
            "development_agent": development_agent,
            "development_controller": development_controller,
            "git_manager": git_manager,
            "github_manager": github_manager,
            "github_sync": github_sync,
            "repository_intelligence": repository_intelligence,
            "git_branch_lifecycle": git_branch_lifecycle,
            "github_project_creator": github_project_creator,
            "phase1_runtime": phase1_runtime,
            "phase1_readiness_gateway": phase1_readiness_gateway,
            "autonomous_development_bridge": phase1_runtime.get(
                "autonomous_development_bridge"
            ),
            "autonomous_coding_loop": phase1_runtime.get(
                "autonomous_coding_loop"
            ),
            "autonomous_validation_loop": phase1_runtime.get(
                "autonomous_validation_loop"
            ),
            "autonomous_repair_loop": phase1_runtime.get(
                "autonomous_repair_loop"
            ),
            "knowledge_coding_feedback": phase1_runtime.get(
                "knowledge_coding_feedback"
            ),
            "permissioned_git_workflow": phase1_runtime.get(
                "permissioned_git_workflow"
            ),
            "permissioned_deployment_workflow": phase1_runtime.get(
                "permissioned_deployment_workflow"
            ),
            "build_manager_factory": BuildManager,
            "deployment_manager": deployment_manager,
            "health_monitor": health_monitor,
            "rollback_manager": rollback_manager,
            "approval_manager": approval_manager,
            "telegram_approval_interface": telegram_approval_interface,
            "deployment_policy": deployment_policy,
        },
    )

    logger.info(
        "[Phase1] Self-engineering subsystem registered | "
        "repository intelligence=%s | workspace=%s | "
        "validation=%s | git=%s | deployment=%s | approval=%s",
        True,
        True,
        True,
        True,
        True,
        True,
    )

    # ---------------------------------------------------------
    # Document Pipeline
    # ---------------------------------------------------------

    pipeline = DocumentPipeline(
        document_manager=document_manager,
        chunker=chunker,
        concept_extractor=concept_extractor,
        document_memory=document_memory,
        semantic_search=semantic_search,
    )

    document_manager.register_parser(
        ".pdf",
        PDFParser(),
    )

    document_manager.register_parser(
        ".docx",
        DOCXParser(),
    )

    document_manager.register_parser(
        ".jpg",
        ImageParser(),
    )

    document_manager.register_parser(
        ".jpeg",
        ImageParser(),
    )

    document_manager.register_parser(
        ".png",
        ImageParser(),
    )

    document_manager.register_parser(
        ".zip",
        ZIPParser(),
    )

    registry.register(
        "document_manager",
        document_manager,
    )

    registry.register(
        "document_pipeline",
        pipeline,
    )

    registry.register(
        "chunker",
        chunker,
    )

    registry.register(
        "concept_extractor",
        concept_extractor,
    )

    registry.register(
        "document_memory",
        document_memory,
    )

    registry.register(
        "semantic_search",
        semantic_search,
    )

    registry.register(
        "study_engine",
        study_engine,
    )

    registry.register(
        "flashcard_generator",
        flashcard_generator,
    )

    registry.register(
        "mcq_generator",
        mcq_generator,
    )

    registry.register(
        "revision_engine",
        revision_engine,
    )

    registry.register(
        "repo_analyzer",
        repo_analyzer,
    )

    registry.register(
        "code_parser",
        code_parser,
    )

    registry.register(
        "dependency_graph",
        dependency_graph,
    )

    registry.register(
        "repository_memory",
        repository_memory,
    )

    # ---------------------------------------------------------
    # Agents, Coordinator & Lead Agent
    # ---------------------------------------------------------

    logger.info(
        "[BOOT TEST] 8 - Starting AgentManager"
    )

    agent_manager = AgentManager()

    agent_coordinator = AgentCoordinator(
        agent_manager
    )

    lead_agent = LeadAgent()

    agent_manager.register(
        CodeAgent()
    )

    agent_manager.register(
        MathAgent()
    )

    agent_manager.register(
        PlanningAgent()
    )

    agent_manager.register(
        ResearchAgent()
    )

    agent_manager.register(
        WritingAgent()
    )

    registry.register(
        "agent_manager",
        agent_manager,
    )

    registry.register(
        "agent_coordinator",
        agent_coordinator,
    )

    registry.register(
        "lead_agent",
        lead_agent,
    )

    logger.info(
        "[BOOT TEST] Registered %d specialist agents",
        len(agent_manager.agents),
    )

    # ---------------------------------------------------------
    # Skills & Actions
    # ---------------------------------------------------------

    session_manager = SessionManager(
        state_manager
    )

    skill_manager = SkillManager()

    skill_manager.register(
        ChatSkill()
    )

    skill_manager.register(
        DocumentSkill()
    )

    skill_manager.register(
        MemorySkill()
    )

    skill_manager.register(
        ProfileSkill()
    )

    skill_manager.register(
        ResearchSkill()
    )

    skill_manager.register(
        CalculatorSkill()
    )

    action_manager = ActionManager(
        permission_mode=config.permission_mode
    )

    action_manager.register(
        FileAction()
    )

    action_manager.register(
        NotificationAction()
    )

    action_manager.register(
        WebSearchAction()
    )

    action_manager.register(
        TimeAction()
    )

    action_manager.register(
        WeatherAction()
    )

    # ---------------------------------------------------------
    # Phase 11 — Central Tool Orchestration
    # ---------------------------------------------------------

    tool_manager = ToolManager(
        selection_threshold=max(
            0.0,
            min(
                1.0,
                float(
                    os.getenv(
                        "ARIA_TOOL_SELECTION_THRESHOLD",
                        "0.25",
                    )
                ),
            ),
        ),
        execution_timeout=max(
            1.0,
            float(
                os.getenv(
                    "ARIA_TOOL_EXECUTION_TIMEOUT",
                    "60",
                )
            ),
        ),
    )

    registry.register(
        "tool_manager",
        tool_manager,
    )

    logger.info(
        "[Phase11] ToolManager initialized | "
        "threshold=%.2f timeout=%.1fs",
        tool_manager.selection_threshold,
        tool_manager.execution_timeout,
    )

    # ---------------------------------------------------------
    # Shared Search Tool
    # ---------------------------------------------------------

    search_tool = SearchTool(
        max_results=10,
        timeout=max(
            3.0,
            float(
                getattr(
                    config,
                    "timeout_seconds",
                    20.0,
                )
            ),
        ),
    )

    registry.register(
        "search_tool",
        search_tool,
    )

    # ---------------------------------------------------------
    # Phase 1 — Real-Time Research Integration
    # ---------------------------------------------------------

    real_time_research = RealTimeResearch(
        search_tool=search_tool,
        max_results=int(
            os.getenv(
                "ARIA_RESEARCH_MAX_RESULTS",
                "8",
            )
        ),
        search_depth=os.getenv(
            "ARIA_RESEARCH_SEARCH_DEPTH",
            "advanced",
        ),
        timeout_seconds=float(
            os.getenv(
                "ARIA_RESEARCH_TIMEOUT",
                "30",
            )
        ),
    )

    registry.register(
        "real_time_research",
        real_time_research,
    )

    logger.info(
        "[Phase1] Real-time research registered | "
        "available=%s | max_results=%s",
        real_time_research.health()["search_available"],
        real_time_research.max_results,
    )

    try:

        tool_manager.register(
            search_tool,
            aliases=[
                "web",
                "web_search",
                "internet",
                "online_search",
            ],
        )

    except Exception:

        logger.exception(
            "[Phase11] Failed to register SearchTool "
            "with ToolManager."
        )

    logger.info(
        "[Bootstrap] SearchTool registered | "
        "available=%s | tools=%s",
        search_tool.is_available(),
        tool_manager.list_tools(),
    )

    # Register safe built-in calculator capability.
    try:

        tool_manager.register(
            CalculatorTool(),
            aliases=[
                "calc",
                "math",
            ],
        )

    except Exception:

        logger.exception(
            "[Phase11] Failed to register CalculatorTool."
        )

    # ---------------------------------------------------------
    # Step 6 — Explicit planning / phase-only execution boundary
    # ---------------------------------------------------------

    engineering_execution_mode = EngineeringExecutionMode(
        repository_engine=repository_intelligence,
        readiness_gateway=phase1_readiness_gateway,
    )

    registry.register(
        "engineering_execution_mode",
        engineering_execution_mode,
    )

    logger.info(
        "[Phase6] Engineering execution mode ready | %s",
        engineering_execution_mode.health(),
    )

    # ---------------------------------------------------------
    # Step 7 — Canonical autonomous engineering lifecycle
    # ---------------------------------------------------------

    autonomous_engineering_lifecycle = AutonomousEngineeringLifecycle(
        final_engineer=getattr(
            phase1_runtime,
            "final_engineer",
            None,
        ),
        execution_mode=engineering_execution_mode,
        readiness_gateway=phase1_readiness_gateway,
    )

    registry.register(
        "autonomous_engineering_lifecycle",
        autonomous_engineering_lifecycle,
    )

    logger.info(
        "[Phase7] Autonomous engineering lifecycle ready | %s",
        autonomous_engineering_lifecycle.health(),
    )

    # ---------------------------------------------------------
    # Unified capability hub
    # ---------------------------------------------------------

    capability_hub = Phase1CapabilityHub(
        skill_manager=skill_manager,
        tool_manager=tool_manager,
        action_manager=action_manager,
        agent_manager=agent_manager,
        document_pipeline=pipeline,
    )

    capability_selector = capability_hub.capability_selector

    registry.register(
        "phase1_capability_hub",
        capability_hub,
    )

    registry.register(
        "unified_capability_selector",
        capability_selector,
    )

    logger.info(
        "[Phase1] Capability hub ready | %s",
        capability_hub.health(),
    )

    # ---------------------------------------------------------
    # Canonical Git / GitHub / Deployment Delivery Boundary
    # ---------------------------------------------------------

    delivery_gateway = Phase1DeliveryGateway(
        git_service=phase1_runtime.git_manager,
        github_service=phase1_runtime.github_manager,
        deployment_service=phase1_runtime.deployment_manager,
    )

    registry.register(
        "phase1_delivery_gateway",
        delivery_gateway,
    )

    logger.info(
        "[Phase1] Delivery gateway ready | %s",
        delivery_gateway.health(),
    )


    # ---------------------------------------------------------
    # Step 8 — Explicit Master delivery authorization boundary
    # ---------------------------------------------------------

    master_delivery_authorization = MasterDeliveryAuthorization(
        approval_manager=approval_manager,
        delivery_gateway=delivery_gateway,
    )

    registry.register(
        "master_delivery_authorization",
        master_delivery_authorization,
    )

    logger.info(
        "[Phase8] Master delivery authorization ready | %s",
        master_delivery_authorization.health(),
    )

    # ---------------------------------------------------------
    # Step 9 — Canonical multimodal capability gateway
    # ---------------------------------------------------------

    # Optional providers are loaded lazily. A missing vision/voice backend
    # must never prevent ARIA from booting. Document processing remains
    # available through the already-initialized DocumentPipeline.
    vision_engine = None
    try:
        from vision_engine import VisionEngine
        vision_engine = VisionEngine()
    except Exception as exc:
        logger.warning(
            "[Phase9] Vision provider unavailable; continuing safely: %s",
            exc,
        )

    computer_tool = None
    try:
        from brain.tools.computer_control_tool import ComputerControlTool
        computer_tool = ComputerControlTool()
    except Exception as exc:
        logger.warning(
            "[Phase9] Computer-control tool unavailable; continuing safely: %s",
            exc,
        )

    multimodal_gateway = MultimodalCapabilityGateway(
        document_pipeline=pipeline,
        vision_engine=vision_engine,
        voice_manager=None,
        computer_tool=computer_tool,
    )

    registry.register(
        "multimodal_capability_gateway",
        multimodal_gateway,
    )

    logger.info(
        "[Phase9] Multimodal capability gateway ready | %s",
        multimodal_gateway.health(),
    )

    # ---------------------------------------------------------
    # Step 10 — Final JARVIS integration boundary
    # ---------------------------------------------------------

    jarvis_final_integration = JarvisFinalIntegration(
        memory_system=jarvis_memory_system,
        execution_mode=engineering_execution_mode,
        autonomous_engineering_lifecycle=autonomous_engineering_lifecycle,
        master_delivery_authorization=master_delivery_authorization,
        multimodal_gateway=multimodal_gateway,
        repository_intelligence=repository_intelligence,
        readiness_gateway=phase1_readiness_gateway,
    )

    registry.register(
        "jarvis_final_integration",
        jarvis_final_integration,
    )

    logger.info(
        "[Phase10] Final JARVIS integration ready | %s",
        jarvis_final_integration.health(),
    )

    # ---------------------------------------------------------
    # Shared Web Search Action
    # ---------------------------------------------------------

    web_search_action = action_manager.actions.get(
        "web_search_action"
    )

    if web_search_action is not None:

        try:

            web_search_action.search_tool = search_tool

            logger.info(
                "[Bootstrap] Shared SearchTool connected "
                "to WebSearchAction."
            )

        except Exception:

            logger.exception(
                "[Bootstrap] Failed to connect SearchTool "
                "to WebSearchAction."
            )

    # ---------------------------------------------------------
    # Background Scheduler
    # ---------------------------------------------------------

    scheduler = BackgroundScheduler(
        max_concurrent_jobs=int(
            os.getenv(
                "ARIA_MAX_CONCURRENT_JOBS",
                "5",
            )
        ),
        default_timeout_seconds=float(
            os.getenv(
                "ARIA_JOB_TIMEOUT_SECONDS",
                "300",
            )
        ),
    )

    registry.register(
        "scheduler",
        scheduler,
    )

    # ---------------------------------------------------------
    # Automation Watchers
    # ---------------------------------------------------------

    tavily_client = getattr(
        web_search_action,
        "tavily",
        None,
    )

    automation_watchers = AutomationWatchers(
        tavily_client=tavily_client,
        telegram_token=getattr(
            config,
            "telegram_token",
            None,
        ),
        admin_chat_id=os.getenv(
            "ADMIN_CHAT_ID"
        ),
        search_tool=search_tool,
        http_timeout=max(
            3.0,
            float(
                getattr(
                    config,
                    "timeout_seconds",
                    20.0,
                )
            ),
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

    # ---------------------------------------------------------
    # Phase 10 — Autonomous Self-Improvement Cycle
    # ---------------------------------------------------------

    async def _run_daily_reflection():

        result = await self_reflection.daily_review()

        logger.info(
            "[Phase10] Daily reflection completed: %s",
            result.get("type")
            if isinstance(result, dict)
            else "completed",
        )

        return result

    async def _run_weekly_reflection():

        result = await self_reflection.weekly_review()

        logger.info(
            "[Phase10] Weekly reflection completed: %s",
            result.get("type")
            if isinstance(result, dict)
            else "completed",
        )

        return result

    async def _run_learning_consolidation():

        result = await autonomous_learning.consolidate()

        logger.info(
            "[Phase10] Learning consolidation completed: %s",
            result.get("status")
            if isinstance(result, dict)
            else "completed",
        )

        return result

    consolidation_interval = max(
        3600.0,
        float(
            os.getenv(
                "ARIA_LEARNING_CONSOLIDATION_INTERVAL",
                "21600",
            )
        ),
    )

    daily_review_interval = max(
        3600.0,
        float(
            os.getenv(
                "ARIA_DAILY_REFLECTION_INTERVAL",
                "86400",
            )
        ),
    )

    weekly_review_interval = max(
        3600.0,
        float(
            os.getenv(
                "ARIA_WEEKLY_REFLECTION_INTERVAL",
                "604800",
            )
        ),
    )

    consolidation_job_id = scheduler.schedule_recurring(
        consolidation_interval,
        _run_learning_consolidation,
        goal_id="phase10_learning_consolidation",
        timeout_seconds=min(
            scheduler.default_timeout_seconds,
            300.0,
        ),
        run_immediately=False,
    )

    daily_reflection_job_id = scheduler.schedule_recurring(
        daily_review_interval,
        _run_daily_reflection,
        goal_id="phase10_daily_reflection",
        timeout_seconds=min(
            scheduler.default_timeout_seconds,
            300.0,
        ),
        run_immediately=False,
    )

    weekly_reflection_job_id = scheduler.schedule_recurring(
        weekly_review_interval,
        _run_weekly_reflection,
        goal_id="phase10_weekly_reflection",
        timeout_seconds=min(
            scheduler.default_timeout_seconds,
            600.0,
        ),
        run_immediately=False,
    )

    registry.register(
        "phase10_jobs",
        {
            "consolidation": consolidation_job_id,
            "daily_reflection": daily_reflection_job_id,
            "weekly_reflection": weekly_reflection_job_id,
        },
    )

    logger.info(
        "[Bootstrap] Phase 10 self-improvement cycle active | "
        "consolidation=%ss daily=%ss weekly=%ss",
        consolidation_interval,
        daily_review_interval,
        weekly_review_interval,
    )

    # ---------------------------------------------------------
    # Planner / Executor
    # ---------------------------------------------------------
    #
    # IMPORTANT:
    # Planner's deployed constructor accepts the LLM router.
    # Do NOT pass memory_router or the other legacy keyword
    # dependencies into Planner(...).
    #
    # Those services are connected after construction below.
    # This prevents:
    #
    # TypeError:
    # Planner.__init__() got an unexpected keyword argument
    # 'memory_router'
    #
    # ---------------------------------------------------------

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
        tool_manager=tool_manager,
    )

    # ---------------------------------------------------------
    # Personality / Decision / Intent
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Reasoning Engine
    # ---------------------------------------------------------

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

    registry.register(
        "session_manager",
        session_manager,
    )

    registry.register(
        "state_manager",
        state_manager,
    )

    registry.register(
        "skill_manager",
        skill_manager,
    )

    registry.register(
        "action_manager",
        action_manager,
    )

    registry.register(
        "planner",
        planner,
    )

    registry.register(
        "executor",
        executor,
    )

    registry.register(
        "personality_engine",
        personality_engine,
    )

    registry.register(
        "decision_engine",
        decision_engine,
    )

    registry.register(
        "intent_analyzer",
        intent_analyzer,
    )

    registry.register(
        "reasoning_engine",
        reasoning_engine,
    )

    # ---------------------------------------------------------
    # Phase 11 Capability Registry
    # ---------------------------------------------------------

    registry.register(
        "phase11_capability_registry",
        {
            "tool_manager": tool_manager,
            "search_tool": search_tool,
            "agent_manager": agent_manager,
            "agent_coordinator": agent_coordinator,
            "planner": planner,
            "executor": executor,
            "reasoning_engine": reasoning_engine,
            "decision_engine": decision_engine,
            "intent_analyzer": intent_analyzer,
            "goal_manager": goal_manager,
            "task_manager": task_manager,
        },
    )

    logger.info(
        "[Phase11] Capability graph prepared | tools=%s",
        tool_manager.list_tools(),
    )

    # ---------------------------------------------------------
    # Phase 1 Capability Registry
    # ---------------------------------------------------------

    registry.register(
        "phase1_capability_registry",
        {
            "repository_manager": repository_manager,
            "source_analyzer": source_analyzer,
            "dependency_analyzer": dependency_analyzer,
            "architecture_intelligence": architecture_intelligence,
            "development_workspace": development_workspace,
            "requirement_parser": requirement_parser,
            "requirement_intelligence": requirement_intelligence,
            "change_planner": change_planner,
            "change_impact_planner": change_impact_planner,

            "filesystem_guard_factory": FilesystemGuard,
            "development_sandbox_factory": DevelopmentSandbox,
            "code_writer_factory": CodeWriter,
            "validator_factory": DevelopmentValidator,
            "test_runner_factory": DevelopmentTestRunner,
            "build_manager_factory": BuildManager,

            "failure_analyzer": failure_analyzer,
            "repair_engine": repair_engine,
            "development_agent": development_agent,
            "development_controller": development_controller,
            "git_manager": git_manager,
            "github_manager": github_manager,
            "github_sync": github_sync,
            "git_branch_lifecycle": git_branch_lifecycle,
            "github_project_creator": github_project_creator,
            "real_time_research": real_time_research,
            "phase1_runtime": phase1_runtime,

            "autonomous_development_bridge": phase1_runtime.get(
                "autonomous_development_bridge"
            ),

            "autonomous_coding_loop": phase1_runtime.get(
                "autonomous_coding_loop"
            ),

            "autonomous_validation_loop": phase1_runtime.get(
                "autonomous_validation_loop"
            ),

            "autonomous_repair_loop": phase1_runtime.get(
                "autonomous_repair_loop"
            ),

            "knowledge_coding_feedback": phase1_runtime.get(
                "knowledge_coding_feedback"
            ),

            "permissioned_git_workflow": phase1_runtime.get(
                "permissioned_git_workflow"
            ),

            "permissioned_deployment_workflow": phase1_runtime.get(
                "permissioned_deployment_workflow"
            ),

            "deployment_manager": deployment_manager,
            "health_monitor": health_monitor,
            "rollback_manager": rollback_manager,
            "approval_manager": approval_manager,
            "telegram_approval_interface": telegram_approval_interface,
            "deployment_policy": deployment_policy,
        },
    )

    logger.info(
        "[Phase1] Capability registry prepared | "
        "self_engineering=True",
    )

    # ---------------------------------------------------------
    # Cross Wiring
    # ---------------------------------------------------------
    #
    # Planner is intentionally constructed with only the
    # constructor-supported dependency.
    #
    # Runtime services are attached after construction so
    # older/newer Planner implementations remain compatible.
    #
    # ---------------------------------------------------------

    planner.executor = executor
    planner.memory_engine = memory_engine
    planner.memory_router = memory_router
    planner.reasoning_engine = reasoning_engine
    planner.skill_manager = skill_manager
    planner.action_manager = action_manager
    planner.knowledge_manager = knowledge_manager
    planner.knowledge_graph = knowledge_graph
    planner.world_model = world_model
    planner.event_bus = event_bus

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

    logger.info(
        "[Bootstrap] Cross wiring complete."
    )

    # ---------------------------------------------------------
    # Cognitive Core
    # ---------------------------------------------------------

    cognitive_core = CognitiveCore(
        planner=planner,
        executor=executor,
        skill_manager=skill_manager,
        tool_manager=tool_manager,
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
        phase1_runtime=phase1_runtime,
        capability_selector=capability_selector,
        jarvis_final_integration=jarvis_final_integration,
    )

    # ---------------------------------------------------------
    # Canonical JARVIS integration contract
    # ---------------------------------------------------------
    #
    # Bootstrap owns construction and dependency wiring only.  The actual
    # request-routing/execution policy is implemented by the integration
    # files themselves.  These explicit references make every canonical
    # Phase 1-10 owner available from the same CognitiveCore boundary and
    # allow later integration layers to consume the exact instances created
    # here instead of constructing competing copies.
    #
    cognitive_core.jarvis_final_integration = jarvis_final_integration
    cognitive_core.jarvis_request_kernel = getattr(
        cognitive_core,
        "jarvis_request_kernel",
        None,
    )
    cognitive_core.unified_capability_selector = capability_selector
    cognitive_core.engineering_execution_mode = engineering_execution_mode
    cognitive_core.autonomous_engineering_lifecycle = (
        autonomous_engineering_lifecycle
    )
    cognitive_core.master_delivery_authorization = (
        master_delivery_authorization
    )
    cognitive_core.multimodal_capability_gateway = multimodal_gateway
    cognitive_core.repository_intelligence = repository_intelligence
    cognitive_core.phase1_readiness_gateway = phase1_readiness_gateway

    # Give the final integration boundary references to the canonical
    # capability and delivery owners.  These are references only; no work is
    # executed during bootstrap.
    jarvis_final_integration.capability_selector = capability_selector
    jarvis_final_integration.cognitive_core = cognitive_core
    jarvis_final_integration.phase1_runtime = phase1_runtime
    jarvis_final_integration.delivery_gateway = delivery_gateway

    # Keep the autonomous lifecycle connected to the same execution and
    # authorization boundaries used by the rest of the system.
    autonomous_engineering_lifecycle.master_delivery_authorization = (
        master_delivery_authorization
    )
    autonomous_engineering_lifecycle.delivery_gateway = delivery_gateway

    canonical_integration_contract = {
        "request_kernel": getattr(
            cognitive_core,
            "jarvis_request_kernel",
            None,
        ),
        "final_integration": jarvis_final_integration,
        "capability_selector": capability_selector,
        "execution_mode": engineering_execution_mode,
        "autonomous_engineering": autonomous_engineering_lifecycle,
        "delivery_authorization": master_delivery_authorization,
        "multimodal_gateway": multimodal_gateway,
        "repository_intelligence": repository_intelligence,
        "readiness_gateway": phase1_readiness_gateway,
        "phase1_runtime": phase1_runtime,
        "cognitive_core": cognitive_core,
    }

    missing_contract_components = [
        name
        for name, component in canonical_integration_contract.items()
        if component is None
    ]

    if missing_contract_components:
        raise RuntimeError(
            "Canonical JARVIS integration contract is incomplete: "
            + ", ".join(missing_contract_components)
        )

    registry.register(
        "canonical_jarvis_integration",
        canonical_integration_contract,
    )

    logger.info(
        "[Bootstrap] Canonical JARVIS integration contract validated | "
        "components=%s",
        sorted(canonical_integration_contract.keys()),
    )

    registry.register(
        "cognitive_core",
        cognitive_core,
    )

    registry.register(
        "phase11_status",
        {
            "version": "11.2",
            "tool_manager": tool_manager.list_tools(),
            "cognitive_core": cognitive_core,
            "planner": planner,
            "executor": executor,
            "reasoning_engine": reasoning_engine,
            "decision_engine": decision_engine,
            "intent_analyzer": intent_analyzer,
        },
    )

    # ---------------------------------------------------------
    # Health Checker
    # ---------------------------------------------------------

    health_checker = HealthChecker(
        registry
    )

    registry.register(
        "health_checker",
        health_checker
    )

    # ---------------------------------------------------------
    # Semantic Graph Persistence
    # ---------------------------------------------------------

    working_memory.semantic().save_semantic_graph()

    logger.info(
        "[Bootstrap] Semantic Graph: %s",
        working_memory.semantic_summary(),
    )

    # ---------------------------------------------------------
    # System Started Event
    # ---------------------------------------------------------

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