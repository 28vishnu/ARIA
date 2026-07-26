import logging
from typing import List
from plugins.base import BasePlugin

logger = logging.getLogger("aria")

class DependencyResolver:
    @staticmethod
    def resolve_order(plugins: List[BasePlugin]) -> List[BasePlugin]:
        """Performs topological sorting to resolve plugin initialization order based on dependencies."""
        resolved: List[BasePlugin] = []
        unresolved = list(plugins)
        plugin_map = {p.manifest.id: p for p in plugins}

        while unresolved:
            progress = False
            for p in list(unresolved):
                # Check if all dependencies are already resolved
                deps = p.manifest.dependencies
                if all(dep in [r.manifest.id for r in resolved] for dep in deps):
                    resolved.append(p)
                    unresolved.remove(p)
                    progress = True
            if not progress:
                # Circular dependency or missing dependency fallback
                logger.warning("[DependencyResolver] Circular dependency or unresolved dependency detected; forcing sequence.")
                resolved.extend(unresolved)
                break
        return resolved
