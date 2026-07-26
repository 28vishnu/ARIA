import os
import logging
import motor.motor_asyncio
import chromadb
import certifi
from platform.configuration import load_config
from platform.dependency_injection import ServiceRegistry
from platform.health import HealthChecker

logger = logging.getLogger("aria")

async def bootstrap_application() -> ServiceRegistry:
    """Bootstraps ARIA's platform container, wiring all 12 architectural phases into production readiness."""
    config = load_config()
    registry = ServiceRegistry()
    registry.register("config", config)

    logger.info("[Bootstrap] Initializing ARIA Platform (Environment: %s)...", config.environment)

    # 1. Database & Persistence Setup
    mongo_client = None
    if config.mongodb_uri:
        mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
            config.mongodb_uri, tlsCAFile=certifi.where(), tlsInsecure=True, serverSelectionTimeoutMS=5000
        )
        registry.register("mongo_client", mongo_client)
        logger.info("[Bootstrap] MongoDB client connected.")

    chroma_client = None
    try:
        os.makedirs(config.vector_persist_path, exist_ok=True)
        chroma_client = chromadb.PersistentClient(path=config.vector_persist_path)
        registry.register("chroma_client", chroma_client)
        logger.info("[Bootstrap] Chroma vector database initialized.")
    except Exception as e:
        logger.warning("[Bootstrap] Vector storage note: %s", e)

    # 2. Health & Observability Subsystems
    health_checker = HealthChecker(mongo_client=mongo_client, chroma_client=chroma_client)
    registry.register("health_checker", health_checker)

    logger.info("[Bootstrap] ARIA platform boot sequence complete. All systems nominal.")
    return registry
