from abc import ABC, abstractmethod
from typing import Dict, Any
from plugins.metadata import PluginManifest

class BasePlugin(ABC):
    def __init__(self, manifest: PluginManifest):
        self.manifest = manifest
        self.status = "installed"  # installed, loaded, running, paused, disabled, error

    @abstractmethod
    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Initializes plugin resources and binds to core capabilities."""
        pass

    @abstractmethod
    async def shutdown(self) -> bool:
        """Safely cleans up plugin resources before unloading."""
        pass
