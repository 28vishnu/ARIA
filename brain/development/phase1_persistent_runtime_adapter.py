from __future__ import annotations

import logging
from typing import Any

from .persistent_engineering_runtime import (
    PersistentEngineeringRuntime,
)

logger = logging.getLogger(
    "aria.phase1_persistent_runtime_adapter"
)


class Phase1PersistentRuntimeAdapter:
    """
    Compatibility adapter between the existing Phase 1 runtime bundle
    and the authoritative persistent engineering runtime.

    Architecture:

        Telegram
            ↓
        TelegramEngineeringRuntime
            ↓
        Phase1PersistentRuntimeAdapter
            ↓
        PersistentEngineeringRuntime
            ↓
        Existing Phase 1 Runtime Bundle
            ↓
        AutonomousDevelopmentBridge
            ↓
        DevelopmentController
            ↓
        DevelopmentAgent

    Important:

    - Existing Phase 1 capabilities remain available.
    - Existing dictionary-style `.get()` access remains available.
    - Existing `.status()` / `.health()` remain compatible.
    - Persistent engineering sessions become the recovery boundary.
    - The adapter does NOT create a second development bridge when the
      existing Phase 1 runtime already provides one.
    - GitHub push and deployment remain controlled by their existing
      permissioned systems.
    """

    VERSION = (
        "PHASE1-PERSISTENT-ADAPTER-V1"
    )

    PERSISTENT_RUNTIME_KEY = (
        "persistent_engineering_runtime"
    )

    PERSISTENCE_KEY = (
        "engineering_persistence"
    )

    def __init__(
        self,
        legacy_runtime: Any,
        *,
        development_controller: Any | None = None,
        persistence: Any | None = None,
        timeout_seconds: float = 1800.0,
    ) -> None:
        if legacy_runtime is None:
            raise ValueError(
                "legacy_runtime is required."
            )

        self.legacy_runtime = legacy_runtime
        self.development_controller = (
            development_controller
        )
        self.persistence = persistence
        self.timeout_seconds = float(
            timeout_seconds
        )

        self._development_runtime = (
            self._resolve_development_runtime()
        )

        self.runtime = (
            PersistentEngineeringRuntime(
                self._development_runtime,
                persistence=persistence,
            )
        )

        logger.info(
            "[Phase1PersistentAdapter] Initialized | "
            "runtime=%s | development_runtime=%s",
            self.VERSION,
            type(
                self._development_runtime
            ).__name__,
        )

    # ============================================================
    # Runtime resolution
    # ============================================================

    def _resolve_development_runtime(
        self,
    ) -> Any:
        """
        Reuse the already-created Phase 1 autonomous development
        bridge whenever possible.

        This is critical because creating another bridge would produce
        duplicate autonomous-development infrastructure.
        """

        bridge = self._legacy_get(
            "autonomous_development_bridge"
        )

        if bridge is not None:
            logger.info(
                "[Phase1PersistentAdapter] "
                "Reusing existing autonomous development bridge."
            )

            return bridge

        # Some older runtime bundles may expose the development
        # controller directly instead of the bridge.
        controller = self._legacy_get(
            "development_controller"
        )

        if controller is not None:
            logger.info(
                "[Phase1PersistentAdapter] "
                "Falling back to legacy development controller."
            )

            return controller

        if self.development_controller is not None:
            logger.info(
                "[Phase1PersistentAdapter] "
                "Using supplied development controller."
            )

            return self.development_controller

        # Last-resort compatibility path.
        #
        # Import lazily so simply importing this adapter does not
        # instantiate another bridge unless it is genuinely needed.
        try:
            from .autonomous_development_bridge import (
                AutonomousDevelopmentBridge,
            )

            if self.development_controller is None:
                raise RuntimeError(
                    "No existing autonomous development bridge or "
                    "development controller is available."
                )

            return AutonomousDevelopmentBridge(
                self.development_controller,
                timeout_seconds=self.timeout_seconds,
            )

        except Exception as exc:
            raise RuntimeError(
                "Unable to resolve the existing Phase 1 "
                "development runtime."
            ) from exc

    # ============================================================
    # Legacy runtime compatibility
    # ============================================================

    def _legacy_get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Safely read a capability from the legacy runtime.

        Supports:

        - dict
        - Mapping-like objects
        - objects exposing get()
        - objects exposing attributes
        """

        runtime = self.legacy_runtime

        try:
            getter = getattr(
                runtime,
                "get",
                None,
            )

            if callable(getter):
                value = getter(
                    key,
                    default,
                )

                if value is not None:
                    return value

        except Exception:
            logger.debug(
                "[Phase1PersistentAdapter] "
                "Legacy get failed | key=%s",
                key,
                exc_info=True,
            )

        try:
            if isinstance(
                runtime,
                dict,
            ):
                return runtime.get(
                    key,
                    default,
                )

        except Exception:
            logger.debug(
                "[Phase1PersistentAdapter] "
                "Dictionary lookup failed | key=%s",
                key,
                exc_info=True,
            )

        try:
            return getattr(
                runtime,
                key,
                default,
            )

        except Exception:
            return default

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Preserve the existing Phase 1 `.get()` API.

        This is required because bootstrap and the capability registry
        already use:

            phase1_runtime.get("...")

        """

        if key == self.PERSISTENT_RUNTIME_KEY:
            return self.runtime

        if key == self.PERSISTENCE_KEY:
            return self.persistence

        return self._legacy_get(
            key,
            default,
        )

    def __getitem__(
        self,
        key: str,
    ) -> Any:
        value = self.get(
            key,
            None,
        )

        if value is None:
            raise KeyError(key)

        return value

    def __contains__(
        self,
        key: object,
    ) -> bool:
        if not isinstance(
            key,
            str,
        ):
            return False

        return (
            self.get(
                key,
                None,
            )
            is not None
        )

    def keys(self) -> list[str]:
        """
        Return known legacy and authoritative runtime keys.
        """

        keys = [
            self.PERSISTENT_RUNTIME_KEY,
            self.PERSISTENCE_KEY,
        ]

        runtime = self.legacy_runtime

        try:
            if hasattr(
                runtime,
                "keys",
            ):
                for key in runtime.keys():
                    if key not in keys:
                        keys.append(key)

        except Exception:
            logger.debug(
                "[Phase1PersistentAdapter] "
                "Could not enumerate legacy runtime keys.",
                exc_info=True,
            )

        return keys

    # ============================================================
    # Authoritative engineering operations
    # ============================================================

    async def develop(
        self,
        requirement: str,
        **kwargs: Any,
    ) -> Any:
        """
        Start a new persistent autonomous engineering session.
        """

        if not str(
            requirement or ""
        ).strip():
            raise ValueError(
                "Engineering requirement cannot be empty."
            )

        logger.info(
            "[Phase1PersistentAdapter] "
            "Starting persistent development | "
            "requirement=%r",
            requirement,
        )

        return await self.runtime.develop(
            requirement,
            **kwargs,
        )

    async def resume(
        self,
        session_id: str,
        **kwargs: Any,
    ) -> Any:
        """
        Resume a persisted engineering session.
        """

        if not str(
            session_id or ""
        ).strip():
            raise ValueError(
                "session_id is required."
            )

        logger.info(
            "[Phase1PersistentAdapter] "
            "Resuming engineering session | "
            "session_id=%s",
            session_id,
        )

        return await self.runtime.resume(
            session_id,
            **kwargs,
        )

    async def engineering_status(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Return authoritative persisted engineering status.
        """

        return await self.runtime.status(
            session_id
        )

    async def recoverable_sessions(
        self,
    ) -> tuple[str, ...]:
        """
        Return persisted sessions that can be resumed.
        """

        return await self.runtime.recoverable_sessions()

    async def checkpoint(
        self,
        session_id: str,
    ) -> bool:
        """
        Persist the current engineering state.
        """

        return await self.runtime.checkpoint(
            session_id
        )

    # ============================================================
    # Legacy-compatible status
    # ============================================================

    def status(
        self,
    ) -> dict[str, Any]:
        """
        Preserve the existing synchronous Phase 1 status contract.

        The persistent runtime itself exposes asynchronous session
        status, so this method reports integration health without
        falsely claiming that an individual engineering session has
        completed.
        """

        try:
            legacy_status: dict[str, Any] = {}

            legacy_status_method = getattr(
                self.legacy_runtime,
                "status",
                None,
            )

            if callable(
                legacy_status_method
            ):
                try:
                    value = legacy_status_method()

                    if isinstance(
                        value,
                        dict,
                    ):
                        legacy_status = dict(
                            value
                        )

                except Exception:
                    logger.exception(
                        "[Phase1PersistentAdapter] "
                        "Legacy status failed."
                    )

            legacy_component_count = int(
                legacy_status.get(
                    "component_count",
                    0,
                )
                or 0
            )

            return {
                **legacy_status,
                "healthy": bool(
                    legacy_status.get(
                        "healthy",
                        True,
                    )
                ),
                "runtime_version": (
                    self.VERSION
                ),
                "component_count": (
                    legacy_component_count + 2
                ),
                "persistent_engineering_runtime": True,
                "persistent_runtime_version": (
                    getattr(
                        self.runtime,
                        "VERSION",
                        "UNKNOWN",
                    )
                ),
                "development_runtime": (
                    type(
                        self._development_runtime
                    ).__name__
                ),
            }

        except Exception as exc:
            logger.exception(
                "[Phase1PersistentAdapter] "
                "Status failed."
            )

            return {
                "healthy": False,
                "runtime_version": self.VERSION,
                "component_count": 0,
                "persistent_engineering_runtime": True,
                "error": str(exc),
            }

    # ============================================================
    # Legacy-compatible health
    # ============================================================

    def health(
        self,
    ) -> dict[str, Any]:
        """
        Preserve the existing synchronous health contract.
        """

        try:
            legacy_health: dict[str, Any] = {}

            legacy_health_method = getattr(
                self.legacy_runtime,
                "health",
                None,
            )

            if callable(
                legacy_health_method
            ):
                try:
                    value = legacy_health_method()

                    if isinstance(
                        value,
                        dict,
                    ):
                        legacy_health = dict(
                            value
                        )

                except Exception:
                    logger.exception(
                        "[Phase1PersistentAdapter] "
                        "Legacy health failed."
                    )

            legacy_healthy = bool(
                legacy_health.get(
                    "healthy",
                    True,
                )
            )

            persistent_runtime_available = (
                self.runtime is not None
            )

            healthy = (
                legacy_healthy
                and persistent_runtime_available
            )

            return {
                **legacy_health,
                "healthy": healthy,
                "runtime_version": self.VERSION,
                "persistent_engineering_runtime": (
                    persistent_runtime_available
                ),
                "persistence_configured": (
                    self.persistence is not None
                ),
                "development_runtime": (
                    type(
                        self._development_runtime
                    ).__name__
                ),
            }

        except Exception as exc:
            logger.exception(
                "[Phase1PersistentAdapter] "
                "Health failed."
            )

            return {
                "healthy": False,
                "runtime_version": self.VERSION,
                "persistent_engineering_runtime": True,
                "error": str(exc),
            }

    # ============================================================
    # Capability access helpers
    # ============================================================

    def capability(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        return self.get(
            key,
            default,
        )

    def legacy_runtime_status(
        self,
    ) -> dict[str, Any]:
        try:
            method = getattr(
                self.legacy_runtime,
                "status",
                None,
            )

            if callable(method):
                result = method()

                if isinstance(
                    result,
                    dict,
                ):
                    return result

        except Exception as exc:
            return {
                "healthy": False,
                "error": str(exc),
            }

        return {}

    def legacy_runtime_health(
        self,
    ) -> dict[str, Any]:
        try:
            method = getattr(
                self.legacy_runtime,
                "health",
                None,
            )

            if callable(method):
                result = method()

                if isinstance(
                    result,
                    dict,
                ):
                    return result

        except Exception as exc:
            return {
                "healthy": False,
                "error": str(exc),
            }

        return {}

    # ============================================================
    # Diagnostics
    # ============================================================

    def describe(
        self,
    ) -> dict[str, Any]:
        return {
            "adapter_version": self.VERSION,
            "persistent_runtime": True,
            "persistence_configured": (
                self.persistence is not None
            ),
            "legacy_runtime_type": (
                type(
                    self.legacy_runtime
                ).__name__
            ),
            "development_runtime_type": (
                type(
                    self._development_runtime
                ).__name__
            ),
            "capabilities": {
                "develop": callable(
                    getattr(
                        self,
                        "develop",
                        None,
                    )
                ),
                "resume": callable(
                    getattr(
                        self,
                        "resume",
                        None,
                    )
                ),
                "status": callable(
                    getattr(
                        self,
                        "status",
                        None,
                    )
                ),
                "health": callable(
                    getattr(
                        self,
                        "health",
                        None,
                    )
                ),
                "checkpoint": callable(
                    getattr(
                        self,
                        "checkpoint",
                        None,
                    )
                ),
                "recoverable_sessions": callable(
                    getattr(
                        self,
                        "recoverable_sessions",
                        None,
                    )
                ),
            },
        }


__all__ = [
    "Phase1PersistentRuntimeAdapter",
]