import os
import logging
import httpx
import motor.motor_asyncio
import chromadb
import certifi

from core.configuration import load_config, AppConfig
from core.dependency_injection import ServiceRegistry
from core.health import HealthChecker

from brain.memory.memory_engine import MemoryEngine
from brain.memory.memory_conversation_manager import MemoryConversationManager
from brain.memory.working_memory import WorkingMemory
from brain.memory.memory_router import MemoryRouter
from brain.document.document_intelligence import DocumentIntelligence
from skills import create_default_skill_manager
from skills.time import TimeSkill
from skills.date import DateSkill
from skills.weather import WeatherSkill
from skills.search import SearchSkill
from skills.chat import ChatSkill
from skills.agent import AgentSkill
from actions.registry import create_default_action_manager
from brain.planner import Planner
from brain.executor import Executor
from brain.decision.decision_engine import DecisionEngine
from brain.context.context_builder import ContextBuilder
from brain.state.state_manager import StateManager
from brain.intent.intent_analyzer import IntentAnalyzer
from brain.reasoning.reasoning_engine import ReasoningEngine
from brain.tools.tool_manager import ToolManager
from brain.tools.calculator_tool import CalculatorTool
from brain.tools.python_tool import PythonTool
from brain.agents.agent_manager import AgentManager
from brain.agents.code_agent import CodeAgent
from brain.agents.python_agent import PythonAgent
from brain.agents.research_agent import ResearchAgent
from brain.agents.math_agent import MathAgent
from brain.agents.writing_agent import WritingAgent
from brain.agents.memory_agent import MemoryAgent
from brain.agents.planning_agent import PlanningAgent
from brain.agents.task_planner import TaskPlanner
from brain.event import EventBus
from brain.context_manager import ContextManager
from brain.session import SessionManager
from plugins.manager import PluginManager
from personality.engine import PersonalityEngine
from autonomy.goal_manager import GoalManager
from autonomy.scheduler import BackgroundScheduler

from brain.core.cognitive_core import CognitiveCore

logger = logging.getLogger("aria")

class GroqProvider:
    def __init__(self, api_key: str):
        from groq import Groq
        self.client = Groq(api_key=api_key) if api_key else None
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client: raise Exception("Groq unconfigured")
        def _exec():
            res = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile", messages=messages, temperature=temperature, max_tokens=max_tokens
            )
            return res.choices[0].message.content.strip()
        import asyncio
        return await asyncio.to_thread(_exec)

class GeminiProvider:
    def __init__(self, api_key: str):
        from google import genai
        self.client = genai.Client(api_key=api_key) if api_key else None
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        if not self.client: raise Exception("Gemini unconfigured")
        prompt_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in messages]) + "\nARIA:"
        def _exec():
            res = self.client.models.generate_content(model="gemini-2.0-flash", contents=prompt_str)
            return res.text.strip()
        import asyncio
        return await asyncio.to_thread(_exec)

class FallbackRouter:
    def __init__(self, config: AppConfig):
        self.providers = [
            GroqProvider(config.groq_api_key),
            GeminiProvider(config.gemini_api_key)
        ]
    async def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 350) -> str:
        for provider in self.providers:
            try:
                return await provider.chat(messages, temperature, max_tokens)
            except Exception:
                continue
        return "Neural pathways exhausted, Sir."

async def bootstrap_application() -> ServiceRegistry:
    config = load_config()
    registry = ServiceRegistry()
    registry.register("config", config)

    logger.info("[Bootstrap] Initializing ARIA Core container (Environment: %s)...", config.environment)

    http_client = httpx.AsyncClient(timeout=config.timeout_seconds)
    registry.register("http_client", http_client)
    llm_router = FallbackRouter(config)
    registry.register("llm_router", llm_router)

    mongo_client = None
    db_inst = None
    if config.mongodb_uri:
        mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
            config.mongodb_uri, tlsCAFile=certifi.where(), tlsInsecure=True, serverSelectionTimeoutMS=5000
        )
        db_inst = mongo_client["aria_db"]
        registry.register("mongo_client", mongo_client)
        registry.register("db", db_inst)

    chroma_client = None
    docs_col = None
    try:
        os.makedirs(config.vector_persist_path, exist_ok=True)
        chroma_client = chromadb.PersistentClient(path=config.vector_persist_path)
        docs_col = chroma_client.get_or_create_collection(name="documents")
        registry.register("chroma_client", chroma_client)
        registry.register("docs_collection", docs_col)
    except Exception as e:
        logger.warning("[Bootstrap] Vector database initialization note: %s", e)

    memory_engine = MemoryEngine(db_inst)
    await memory_engine.initialize_indexes()
    registry.register("memory_engine", memory_engine)

    memory_conversation_manager = MemoryConversationManager(memory_engine)
    registry.register(
        "memory_conversation_manager",
        memory_conversation_manager
    )

    working_memory = WorkingMemory()
    registry.register("working_memory", working_memory)

    memory_router = MemoryRouter(
        working_memory=working_memory,
        memory_engine=memory_engine
    )
    registry.register("memory_router", memory_router)

    doc_intelligence = DocumentIntelligence(
        memory_engine=memory_engine,
        llm_router=llm_router
    )
    registry.register("document_intelligence", doc_intelligence)

    skill_manager = create_default_skill_manager()
    skill_manager.register(TimeSkill())
    skill_manager.register(DateSkill())
    skill_manager.register(WeatherSkill())
    skill_manager.register(SearchSkill())
    skill_manager.register(ChatSkill())
    skill_manager.register(AgentSkill())
    registry.register("skill_manager", skill_manager)

    action_manager = create_default_action_manager()
    registry.register("action_manager", action_manager)

    planner = Planner(llm_router)
    registry.register("planner", planner)

    executor = Executor(skill_manager)
    registry.register("executor", executor)

    decision_engine = DecisionEngine()
    registry.register("decision_engine", decision_engine)

    context_builder = ContextBuilder()
    registry.register("context_builder", context_builder)

    state_manager = StateManager()
    registry.register("state_manager", state_manager)

    intent_analyzer = IntentAnalyzer()
    registry.register("intent_analyzer", intent_analyzer)

    tool_manager = ToolManager()

    tool_manager.register(
        CalculatorTool()
    )

    tool_manager.register(
        PythonTool()
    )

    registry.register(
        "tool_manager",
        tool_manager
    )

    agent_manager = AgentManager()

    logger.info(
        "[DEBUG] AgentManager has get(): %s",
        hasattr(agent_manager, "get")
    )

    agent_manager.register(CodeAgent())
    agent_manager.register(PythonAgent())
    agent_manager.register(ResearchAgent())
    agent_manager.register(MathAgent())
    agent_manager.register(WritingAgent())
    agent_manager.register(MemoryAgent())
    agent_manager.register(PlanningAgent())

    registry.register(
        "agent_manager",
        agent_manager
    )

    task_planner = TaskPlanner()

    registry.register(
        "task_planner",
        task_planner
    )

    reasoning_engine = ReasoningEngine(
        agent_manager=agent_manager
    )
    registry.register("reasoning_engine", reasoning_engine)

    cognitive_core = CognitiveCore(
        planner=planner,
        executor=executor,
        skill_manager=skill_manager,
        memory_router=memory_router,
        state_manager=state_manager,
        intent_analyzer=intent_analyzer,
        context_builder=context_builder,
        decision_engine=decision_engine,
        memory_conversation_manager=memory_conversation_manager,
        reasoning_engine=reasoning_engine
    )
    registry.register("cognitive_core", cognitive_core)

    event_bus = EventBus()
    registry.register("event_bus", event_bus)

    context_manager = ContextManager(event_bus)
    registry.register("context_manager", context_manager)

    session_manager = SessionManager(context_manager)
    registry.register("session_manager", session_manager)

    plugin_manager = PluginManager()
    registry.register("plugin_manager", plugin_manager)

    personality_engine = PersonalityEngine()
    registry.register("personality_engine", personality_engine)

    goal_manager = GoalManager()
    registry.register("goal_manager", goal_manager)

    scheduler = BackgroundScheduler()
    registry.register("scheduler", scheduler)

    health_checker = HealthChecker(mongo_client=mongo_client, chroma_client=chroma_client)
    registry.register("health_checker", health_checker)

    logger.info("[Bootstrap] ARIA platform boot sequence successfully completed.")
    return registry
