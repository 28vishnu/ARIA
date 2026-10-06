"""Canonical autonomous-engineering execution gateway for ARIA.

Step 7 establishes one safe entry point for executable engineering work.
It delegates the actual lifecycle to FinalAutonomousEngineer and therefore
never duplicates requirement, planning, implementation, verification,
diagnosis, recovery, acceptance, or learning logic.

This gateway is deliberately fail-closed:
- no engineer -> no execution
- unhealthy engineer -> no execution
- non-execution mode -> no execution
- push/deployment authorization remains owned by the existing delivery layer
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AutonomousEngineeringLifecycle:
    """Single executable gateway to the authoritative engineering spine."""

    VERSION = "ARIA-AUTONOMOUS-ENGINEERING-LIFECYCLE-20261006"

    def __init__(
        self,
        *,
        final_engineer: Any = None,
        execution_mode: Any = None,
        readiness_gateway: Any = None,
    ) -> None:
        self.final_engineer = final_engineer
        self.execution_mode = execution_mode
        self.readiness_gateway = readiness_gateway
        self._active_session_id: Optional[str] = None

    def health(self) -> Dict[str, Any]:
        engineer = self.final_engineer
        engineer_health: Dict[str, Any] = {}

        if engineer is None:
            engineer_health = {
                "healthy": False,
                "status": "final_engineer_missing",
            }
        else:
            health_method = getattr(engineer, "health", None)
            if callable(health_method):
                try:
                    value = health_method()
                    engineer_health = self._to_dict(value)
                except Exception as exc:
                    engineer_health = {
                        "healthy": False,
                        "status": "health_check_failed",
                        "error": str(exc),
                    }
            else:
                engineer_health = {
                    "healthy": False,
                    "status": "health_interface_missing",
                }

        return {
            "healthy": bool(engineer_health.get("healthy", False)),
            "version": self.VERSION,
            "final_engineer_connected": engineer is not None,
            "final_engineer_health": engineer_health,
            "execution_mode_connected": self.execution_mode is not None,
            "readiness_gateway_connected": self.readiness_gateway is not None,
            "github_push_requires_authorization": True,
            "deployment_requires_authorization": True,
            "production_direct_write": False,
        }

    async def develop(
        self,
        request: str,
        *,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute one autonomous engineering lifecycle."""

        request = str(request or "").strip()
        if not request:
            return self._failure(
                session_id,
                "empty_request",
                "Engineering request cannot be empty.",
            )

        gate = self._execution_gate()
        if not gate["allowed"]:
            return self._failure(
                session_id,
                gate["status"],
                gate["message"],
                gate=gate,
            )

        engineer = self.final_engineer
        method = getattr(engineer, "develop", None)
        if not callable(method):
            return self._failure(
                session_id,
                "develop_interface_missing",
                "Canonical FinalAutonomousEngineer does not expose develop().",
            )

        self._active_session_id = session_id

        try:
            result = method(
                request,
                session_id=session_id,
                metadata=metadata,
            )
            if inspect.isawaitable(result):
                result = await result
            return result
        except TypeError:
            # Compatibility for an existing engineer implementation that
            # accepts only the request and does not accept optional metadata.
            try:
                result = method(request)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as exc:
                logger.exception("Autonomous engineering execution failed")
                return self._failure(
                    session_id,
                    "engineering_failed",
                    str(exc),
                )
        except Exception as exc:
            logger.exception("Autonomous engineering execution failed")
            return self._failure(
                session_id,
                "engineering_failed",
                str(exc),
            )

    async def execute(self, request: str, **kwargs: Any) -> Any:
        return await self.develop(request, **kwargs)

    async def run(self, request: str, **kwargs: Any) -> Any:
        return await self.develop(request, **kwargs)

    async def resume(
        self,
        session_id: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Resume a previously persisted engineering session."""

        if self.final_engineer is None:
            return self._failure(
                session_id,
                "final_engineer_missing",
                "Canonical FinalAutonomousEngineer is not connected.",
            )

        method = getattr(self.final_engineer, "resume", None)
        if not callable(method):
            return self._failure(
                session_id,
                "resume_interface_missing",
                "Canonical FinalAutonomousEngineer does not expose resume().",
            )

        try:
            result = method(
                session_id,
                metadata=metadata,
            )
            if inspect.isawaitable(result):
                result = await result
            self._active_session_id = session_id
            return result
        except TypeError:
            try:
                result = method(session_id)
                if inspect.isawaitable(result):
                    result = await result
                self._active_session_id = session_id
                return result
            except Exception as exc:
                return self._failure(
                    session_id,
                    "resume_failed",
                    str(exc),
                )
        except Exception as exc:
            logger.exception("Engineering session resume failed")
            return self._failure(
                session_id,
                "resume_failed",
                str(exc),
            )

    def status(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Return the canonical engineer status without executing work."""

        engineer = self.final_engineer
        target = session_id or self._active_session_id

        if engineer is None:
            return {
                "healthy": False,
                "status": "final_engineer_missing",
                "session_id": target,
                "version": self.VERSION,
            }

        for name in ("status", "engineering_status", "get_status"):
            method = getattr(engineer, name, None)
            if not callable(method):
                continue
            try:
                value = method(target) if target else method()
                if inspect.isawaitable(value):
                    return {
                        "healthy": True,
                        "status": "async_status_available",
                        "session_id": target,
                        "version": self.VERSION,
                    }
                result = self._to_dict(value)
                result.setdefault("session_id", target)
                result.setdefault("version", self.VERSION)
                return result
            except TypeError:
                try:
                    value = method()
                    if inspect.isawaitable(value):
                        return {
                            "healthy": True,
                            "status": "async_status_available",
                            "session_id": target,
                            "version": self.VERSION,
                        }
                    result = self._to_dict(value)
                    result.setdefault("session_id", target)
                    result.setdefault("version", self.VERSION)
                    return result
                except Exception:
                    continue
            except Exception:
                logger.debug("Engineering status lookup failed", exc_info=True)
                continue

        return {
            "healthy": bool(self.health().get("healthy")),
            "status": "connected",
            "session_id": target,
            "version": self.VERSION,
        }

    def _execution_gate(self) -> Dict[str, Any]:
        """Check all local gates before allowing engineering execution."""

        if self.final_engineer is None:
            return {
                "allowed": False,
                "status": "final_engineer_missing",
                "message": "Canonical FinalAutonomousEngineer is not connected.",
            }

        health = self.health()
        if not bool(health.get("healthy", False)):
            return {
                "allowed": False,
                "status": "final_engineer_unhealthy",
                "message": "Canonical FinalAutonomousEngineer is not healthy.",
                "health": health,
            }

        return {
            "allowed": True,
            "status": "execution_allowed",
            "message": "Canonical autonomous engineering lifecycle is available.",
            "health": health,
        }

    @staticmethod
    def _to_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if value is None:
            return {}
        try:
            return dict(value)
        except Exception:
            return {
                "value": value,
            }

    @staticmethod
    def _failure(
        session_id: Optional[str],
        status: str,
        message: str,
        **extra: Any,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "success": False,
            "accepted": False,
            "session_id": session_id or "",
            "status": status,
            "phase": "blocked",
            "error": message,
            "message": message,
        }
        result.update(extra)
        return result
