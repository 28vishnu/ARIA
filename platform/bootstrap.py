import os
import logging
import httpx
import motor.motor_asyncio
import chromadb
import certifi

from platform.configuration import load_config, AppConfig
from platform.dependency_injection import ServiceRegistry
from platform.health import HealthChecker

from memory_engine import MemoryEngine
from brain.document_intelligence import DocumentIntelligence
from skills import create_default_skill_manager
from actions.registry import create_default_action_manager
from brain.planner import Planner
from brain.executor import Executor
from brain.event import EventBus
from brain.context_manager import ContextManager
from brain.session import SessionManager
from plugins.manager import PluginManager
from personality.engine import PersonalityEngine
from autonomy.goal_manager import GoalManager
from autonomy.scheduler import BackgroundScheduler

logger = logging.getLogger("aria")

# LLM Fallback Router
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
    """Centralized wiring container for ARIA's 12-phase platform architecture."""
    config = load_config()
    registry = ServiceRegistry()
    registry.register("config", config)

    logger.info("[Bootstrap] Initializing ARIA Platform container...")

    # 1. HTTP Client & LLM Router
    http_client = httpx.AsyncClient(timeout=config.timeout_seconds)
    registry.register("http_client", http_client)
    llm_router = FallbackRouter(config)
    registry.register("llm_router", llm_router)

    # 2. Database & Vector Persistence
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

    # 3. Core Engines & Managers
    memory_engine = MemoryEngine(db_inst)
    await memory_engine.initialize_indexes()
    registry.register("memory_engine", memory_engine)

    doc_intelligence = DocumentIntelligence(docs_col, llm_router=llm_router)
    registry.register("document_intelligence", doc_intelligence)

    skill_manager = create_default_skill_manager()
    registry.register("skill_manager", skill_manager)

    action_manager = create_default_action_manager()
    registry.register("action_manager", action_manager)

    planner = Planner(llm_router)
    registry.register("planner", planner)

    executor = Executor(skill_manager)
    registry.register("executor", executor)

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
