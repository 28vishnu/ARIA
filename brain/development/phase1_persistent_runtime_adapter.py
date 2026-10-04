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
        AutonomousEngineerOrchestrator
            ↓
        DevelopmentController
            ↓
        DevelopmentAgent

    The adapter preserves the existing Phase 1 capability graph while
    making persistent engineering sessions the recovery boundary.
    """

    VERSION = (
        "PHASE1-PERSISTENT-ADAPTER-20261004"
    )

    PERSISTENT_RUNTIME_KEY = (
        "persistent_engineering_runtime"
    )

    PERSISTENCE_KEY = (
        "engineering_persistence"
    )

    REQUIRED_LEGACY_CAPABILITIES = (
        "autonomous_development_bridge",
    )

    OPTIONAL_LEGACY_CAPABILITIES = (
        "autonomous_coding_loop",
        "autonomous_validation_loop",
        "autonomous_repair_loop",
        "knowledge_coding_feedback",
        "permissioned_git_workflow",
        "permissioned_deployment_workflow",
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

        self._integration_check = (
            self._perform_integration_check()
        )

        logger.info(
            "[Phase1PersistentAdapter] Initialized | "
            "healthy=%s | runtime=%s | development_runtime=%s",
            self._integration_check["healthy"],
            self.VERSION,
            type(
                self._development_runtime
            ).__name__,
        )

    # ============================================================
    # DEVELOPMENT RUNTIME RESOLUTION
    # ============================================================

    def _resolve_development_runtime(
        self,
    ) -> Any:
        """
        Reuse the already-created Phase 1 autonomous development
        bridge whenever possible.

        This prevents creation of duplicate autonomous-development
        infrastructure.
        """

        bridge = self._legacy_get(
            "autonomous_development_bridge"
        )

        if bridge is not None:

            if callable(
                getattr(
                    bridge,
                    "develop",
                    None,
                )
            ):
                logger.info(
                    "[Phase1PersistentAdapter] "
                    "Reusing existing autonomous development bridge."
                )

                return bridge

            if callable(
                getattr(
                    bridge,
                    "execute",
                    None,
                )
            ):
                logger.info(
                    "[Phase1PersistentAdapter] "
                    "Reusing existing executable development runtime."
                )

                return bridge

            logger.warning(
                "[Phase1PersistentAdapter] "
                "Existing autonomous development bridge does not "
                "expose develop()/execute()."
            )

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

        raise RuntimeError(
            "Unable to resolve a valid Phase 1 development runtime. "
            "An autonomous_development_bridge or "
            "development_controller is required."
        )

    # ============================================================
    # LEGACY RUNTIME ACCESS
    # ============================================================

    def _legacy_get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Safely retrieve a capability from the existing Phase 1
        runtime bundle.

        Supports:

        - dict
        - mapping-like objects
        - get()
        - attributes
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
                "Legacy get() failed | key=%s",
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

            value = getattr(
                runtime,
                key,
                default,
            )

            if value is not None:
                return value

        except Exception:

            pass

        return default

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Preserve the existing Phase 1 `.get()` API.

        Existing bootstrap code can continue doing:

            phase1_runtime.get("autonomous_development_bridge")

        while new persistent capabilities are also exposed.
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
        keys = [
            self.PERSISTENT_RUNTIME_KEY,
            self.PERSISTENCE_KEY,
        ]

        runtime = self.legacy_runtime

        try:

            runtime_keys = getattr(
                runtime,
                "keys",
                None,
            )

            if callable(runtime_keys):

                for key in runtime_keys():

                    if key not in keys:
                        keys.append(key)

        except Exception:

            logger.debug(
                "[Phase1PersistentAdapter] "
                "Could not enumerate runtime keys.",
                exc_info=True,
            )

        return keys

    # ============================================================
    # STEP 28 — INTEGRATION VERIFICATION
    # ============================================================

    def _perform_integration_check(
        self,
    ) -> dict[str, Any]:
        """
        Perform a non-destructive structural integration check.

        This does NOT execute an engineering request.

        It verifies that:

        1. The legacy Phase 1 runtime exists.
        2. The autonomous development bridge exists.
        3. The bridge exposes an executable development API.
        4. The persistent runtime exists.
        5. The persistent runtime exposes develop().
        6. Resume/status/recovery boundaries exist.
        7. Existing capability access remains available.
        """

        checks: dict[str, bool] = {}

        errors: list[str] = []

        warnings: list[str] = []

        # --------------------------------------------------------
        # Legacy runtime
        # --------------------------------------------------------

        checks["legacy_runtime"] = (
            self.legacy_runtime is not None
        )

        if not checks["legacy_runtime"]:
            errors.append(
                "Legacy Phase 1 runtime is unavailable."
            )

        # --------------------------------------------------------
        # Development runtime
        # --------------------------------------------------------

        development_runtime = (
            self._development_runtime
        )

        has_develop = callable(
            getattr(
                development_runtime,
                "develop",
                None,
            )
        )

        has_execute = callable(
            getattr(
                development_runtime,
                "execute",
                None,
            )
        )

        checks["development_runtime"] = (
            has_develop
            or has_execute
        )

        if not checks["development_runtime"]:

            errors.append(
                "Resolved development runtime does not expose "
                "develop() or execute()."
            )

        # --------------------------------------------------------
        # Persistent runtime
        # --------------------------------------------------------

        checks["persistent_runtime"] = (
            self.runtime is not None
        )

        if not checks["persistent_runtime"]:

            errors.append(
                "PersistentEngineeringRuntime is unavailable."
            )

        # --------------------------------------------------------
        # Persistent develop
        # --------------------------------------------------------

        checks["persistent_develop"] = callable(
            getattr(
                self.runtime,
                "develop",
                None,
            )
        )

        if not checks["persistent_develop"]:

            errors.append(
                "PersistentEngineeringRuntime does not expose "
                "develop()."
            )

        # --------------------------------------------------------
        # Persistent resume
        # --------------------------------------------------------

        checks["persistent_resume"] = callable(
            getattr(
                self.runtime,
                "resume",
                None,
            )
        )

        if not checks["persistent_resume"]:

            errors.append(
                "PersistentEngineeringRuntime does not expose "
                "resume()."
            )

        # --------------------------------------------------------
        # Persistent status
        # --------------------------------------------------------

        checks["persistent_status"] = callable(
            getattr(
                self.runtime,
                "status",
                None,
            )
        )

        if not checks["persistent_status"]:

            errors.append(
                "PersistentEngineeringRuntime does not expose "
                "status()."
            )

        # --------------------------------------------------------
        # Recovery enumeration
        # --------------------------------------------------------

        checks["recoverable_sessions"] = callable(
            getattr(
                self.runtime,
                "recoverable_sessions",
                None,
            )
        )

        if not checks["recoverable_sessions"]:

            warnings.append(
                "Persistent runtime does not expose "
                "recoverable_sessions()."
            )

        # --------------------------------------------------------
        # Checkpoint
        # --------------------------------------------------------

        checks["checkpoint"] = callable(
            getattr(
                self.runtime,
                "checkpoint",
                None,
            )
        )

        if not checks["checkpoint"]:

            warnings.append(
                "Persistent runtime does not expose "
                "checkpoint()."
            )

        # --------------------------------------------------------
        # Existing capability graph
        # --------------------------------------------------------

        for capability in (
            self.REQUIRED_LEGACY_CAPABILITIES
        ):

            available = (
                self._legacy_get(
                    capability
                )
                is not None
            )

            checks[
                f"legacy_{capability}"
            ] = available

            if not available:

                warnings.append(
                    "Legacy Phase 1 capability is unavailable: "
                    f"{capability}"
                )

        for capability in (
            self.OPTIONAL_LEGACY_CAPABILITIES
        ):

            available = (
                self._legacy_get(
                    capability
                )
                is not None
            )

            checks[
                f"legacy_{capability}"
            ] = available

        # --------------------------------------------------------
        # Adapter compatibility
        # --------------------------------------------------------

        checks["get_compatibility"] = callable(
            getattr(
                self,
                "get",
                None,
            )
        )

        checks["health_compatibility"] = callable(
            getattr(
                self,
                "health",
                None,
            )
        )

        checks["status_compatibility"] = callable(
            getattr(
                self,
                "status",
                None,
            )
        )

        healthy = (
            len(errors) == 0
        )

        return {
            "healthy": healthy,
            "checks": checks,
            "errors": errors,
            "warnings": warnings,
            "version": self.VERSION,
        }

    def verify_integration(
        self,
    ) -> dict[str, Any]:
        """
        Return the latest structural integration verification.

        Safe to call repeatedly.
        """

        self._integration_check = (
            self._perform_integration_check()
        )

        return dict(
            self._integration_check
        )

    # ============================================================
    # AUTHORITATIVE ENGINEERING OPERATIONS
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

        verification = (
            self.verify_integration()
        )

        if not verification["healthy"]:

            raise RuntimeError(
                "Phase 1 persistent engineering runtime "
                "failed integration verification: "
                + "; ".join(
                    verification["errors"]
                )
            )

        logger.info(
            "[Phase1PersistentAdapter] "
            "Starting persistent autonomous development | "
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

        verification = (
            self.verify_integration()
        )

        if not verification["healthy"]:

            raise RuntimeError(
                "Phase 1 persistent engineering runtime "
                "failed integration verification: "
                + "; ".join(
                    verification["errors"]
                )
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

        return await self.runtime.status(
            session_id
        )

    async def recoverable_sessions(
        self,
    ) -> tuple[str, ...]:

        return await self.runtime.recoverable_sessions()

    async def checkpoint(
        self,
        session_id: str,
    ) -> bool:

        return await self.runtime.checkpoint(
            session_id
        )

    # ============================================================
    # LEGACY STATUS
    # ============================================================

    def status(
        self,
    ) -> dict[str, Any]:
        try:

            legacy_status: dict[str, Any] = {}

            method = getattr(
                self.legacy_runtime,
                "status",
                None,
            )

            if callable(method):

                try:

                    value = method()

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

            verification = (
                self.verify_integration()
            )

            healthy = (
                bool(
                    legacy_status.get(
                        "healthy",
                        True,
                    )
                )
                and verification["healthy"]
            )

            return {
                **legacy_status,
                "healthy": healthy,
                "runtime_version": self.VERSION,
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
                "integration": verification,
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
    # LEGACY HEALTH
    # ============================================================

    def health(
        self,
    ) -> dict[str, Any]:
        try:

            legacy_health: dict[str, Any] = {}

            method = getattr(
                self.legacy_runtime,
                "health",
                None,
            )

            if callable(method):

                try:

                    value = method()

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

            verification = (
                self.verify_integration()
            )

            legacy_healthy = bool(
                legacy_health.get(
                    "healthy",
                    True,
                )
            )

            healthy = (
                legacy_healthy
                and verification["healthy"]
            )

            return {
                **legacy_health,
                "healthy": healthy,
                "runtime_version": self.VERSION,
                "persistent_engineering_runtime": True,
                "persistence_configured": (
                    self.persistence is not None
                ),
                "development_runtime": (
                    type(
                        self._development_runtime
                    ).__name__
                ),
                "integration": verification,
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
    # LEGACY RUNTIME INFORMATION
    # ============================================================

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
                "healthy":