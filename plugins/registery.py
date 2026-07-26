import logging
from typing import Dict, Any, Callable

logger = logging.getLogger("aria")

class CapabilityRegistry:
    def __init__(self):
        self.capabilities: Dict[str, Callable[..., Any]] = {}

    def register_capability(self, capability_name: str, handler: Callable[..., Any]):
        self.capabilities[capability_name] = handler
        logger.info("[CapabilityRegistry] Registered capability endpoint: '%s'", capability_name)

    def invoke(self, capability_name: str, *args, **kwargs) -> Any:
        if capability_name not in self.capabilities:
            raise KeyError(f"Capability '{capability_name}' not registered in system.")
        return self.capabilities[capability_name](*args, **kwargs)
