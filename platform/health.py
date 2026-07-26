import logging
from typing import Dict, Any

logger = logging.getLogger("aria")

class HealthChecker:
    def __init__(self, mongo_client=None, chroma_client=None):
        self.mongo = mongo_client
        self.chroma = chroma_client

    async def check_readiness(self) -> Dict[str, Any]:
        """Performs deep health checks across database and vector persistence layers."""
        health_status = {"status": "healthy", "dependencies": {}}
        
        # Check MongoDB
        if self.mongo is not None:
            try:
                await self.mongo.admin.command('ping')
                health_status["dependencies"]["mongodb"] = "connected"
            except Exception as e:
                health_status["status"] = "degraded"
                health_status["dependencies"]["mongodb"] = f"unhealthy: {e}"
        else:
            health_status["dependencies"]["mongodb"] = "unconfigured"

        # Check Chroma Vector Store
        if self.chroma is not None:
            try:
                self.chroma.heartbeat()
                health_status["dependencies"]["chromadb"] = "active"
            except Exception as e:
                health_status["status"] = "degraded"
                health_status["dependencies"]["chromadb"] = f"unhealthy: {e}"
        else:
            health_status["dependencies"]["chromadb"] = "unconfigured"

        return health_status
