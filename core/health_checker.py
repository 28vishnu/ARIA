from core.dependency_injection import ServiceRegistry


class HealthChecker:
    def __init__(self, registry: ServiceRegistry):
        self.registry = registry

    async def check_readiness(self):
        return {
            "status": "healthy",
            "ready": True,
            "services": {
                "memory_engine": self.registry.has("memory_engine"),
                "planner": self.registry.has("planner"),
                "cognitive_core": self.registry.has("cognitive_core"),
                "document_intelligence": self.registry.has("document_intelligence"),
                "conversation_manager": self.registry.has("conversation_manager"),
                "http_client": self.registry.has("http_client"),
            },
        }
