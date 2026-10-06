"""
ARIA Phase 1/11 capability integration hub.

Provides one read-only capability graph over ARIA's existing:
- skills
- tools
- plugins
- document pipeline
- voice synthesis
- vision analysis
- multimodal routing

This module does not create a second executor or engineering runtime.
It only exposes existing services through one stable integration surface.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("aria")


class Phase1CapabilityHub:
    VERSION = "phase1-capability-hub-20261005"

    def __init__(
        self,
        *,
        skill_manager: Any = None,
        tool_manager: Any = None,
        action_manager: Any = None,
        agent_manager: Any = None,
        document_pipeline: Any = None,
        plugin_manager: Any = None,
        voice_engine: Any = None,
        vision_engine: Any = None,
        multimodal_router: Any = None,
        capability_selector: Any = None,
    ) -> None:
        self.skill_manager = skill_manager
        self.tool_manager = tool_manager
        self.action_manager = action_manager
        self.document_pipeline = document_pipeline

        self.plugin_manager = plugin_manager or self._safe_plugin_manager()
        self.voice_engine = voice_engine or self._safe_voice_engine()
        self.vision_engine = vision_engine or self._safe_vision_engine()
        self.multimodal_router = multimodal_router or self._safe_multimodal_router()

        if capability_selector is None:
            try:
                from brain.integration.unified_capability_selector import UnifiedCapabilitySelector
                capability_selector = UnifiedCapabilitySelector(
                    skill_manager=skill_manager,
                    tool_manager=tool_manager,
                    action_manager=action_manager,
                    agent_manager=agent_manager,
                    plugin_manager=self.plugin_manager,
                )
            except Exception as exc:
                logger.warning("[CapabilityHub] Unified selector unavailable: %s", exc)
        self.capability_selector = capability_selector

        self._wire_multimodal_router()

    @staticmethod
    def _safe_plugin_manager():
        try:
            from plugins.manager import PluginManager
            return PluginManager()
        except Exception as exc:
            logger.warning("[CapabilityHub] Plugin subsystem unavailable: %s", exc)
            return None

    @staticmethod
    def _safe_voice_engine():
        try:
            from voice_engine import VoiceEngine
            return VoiceEngine()
        except Exception as exc:
            logger.warning("[CapabilityHub] Voice subsystem unavailable: %s", exc)
            return None

    @staticmethod
    def _safe_vision_engine():
        try:
            from vision_engine import VisionEngine
            return VisionEngine()
        except Exception as exc:
            logger.warning("[CapabilityHub] Vision subsystem unavailable: %s", exc)
            return None

    def _safe_multimodal_router(self):
        try:
            from multimodal.router import MultimodalRouter
            return MultimodalRouter(
                image_analyzer=self.vision_engine,
                document_parser=self.document_pipeline,
                stt_provider=None,
            )
        except Exception as exc:
            logger.warning("[CapabilityHub] Multimodal router unavailable: %s", exc)
            return None

    def _wire_multimodal_router(self) -> None:
        router = self.multimodal_router
        if router is None:
            return
        if hasattr(router, "image_analyzer"):
            router.image_analyzer = self.vision_engine
        if hasattr(router, "document_parser"):
            router.document_parser = self.document_pipeline

    def capabilities(self) -> Dict[str, Any]:
        skills = []
        tools = []
        actions = []
        plugins = []

        try:
            if self.skill_manager is not None:
                skills = self.skill_manager.get_capabilities()
        except Exception:
            logger.exception("[CapabilityHub] Failed to inspect skills")

        try:
            if self.tool_manager is not None:
                tools = self.tool_manager.capabilities()
        except Exception:
            logger.exception("[CapabilityHub] Failed to inspect tools")

        try:
            if self.action_manager is not None:
                actions = [
                    {
                        "name": name,
                        "description": str(getattr(action, "description", "") or ""),
                    }
                    for name, action in getattr(self.action_manager, "actions", {}).items()
                ]
        except Exception:
            logger.exception("[CapabilityHub] Failed to inspect actions")

        try:
            if self.plugin_manager is not None:
                plugins = [
                    {
                        "id": plugin_id,
                        "state": str(getattr(plugin, "state", "unknown")),
                        "capabilities": list(
                            getattr(getattr(plugin, "manifest", None), "capabilities", []) or []
                        ),
                    }
                    for plugin_id, plugin in getattr(self.plugin_manager, "plugins", {}).items()
                ]
        except Exception:
            logger.exception("[CapabilityHub] Failed to inspect plugins")

        return {
            "version": self.VERSION,
            "skills": skills,
            "tools": tools,
            "actions": actions,
            "plugins": plugins,
            "documents": self.document_pipeline is not None,
            "voice": self.voice_engine is not None,
            "vision": self.vision_engine is not None,
            "multimodal": self.multimodal_router is not None,
        }

    async def select_capability(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self.capability_selector is None:
            return {"success": False, "error": "Unified capability selector unavailable."}
        selection = await self.capability_selector.select(query, context or {})
        return {"success": True, "selection": selection.to_dict()}

    def health(self) -> Dict[str, Any]:
        capabilities = self.capabilities()
        return {
            "healthy": bool(
                capabilities["documents"]
                and capabilities["multimodal"]
            ),
            "version": self.VERSION,
            "skills": len(capabilities["skills"]),
            "tools": len(capabilities["tools"]),
            "actions": len(capabilities["actions"]),
            "plugins": len(capabilities["plugins"]),
            "documents": capabilities["documents"],
            "voice": capabilities["voice"],
            "vision": capabilities["vision"],
            "multimodal": capabilities["multimodal"],
            "selector": self.capability_selector is not None,
        }

    def status(self) -> Dict[str, Any]:
        return self.health()


__all__ = ["Phase1CapabilityHub"]
