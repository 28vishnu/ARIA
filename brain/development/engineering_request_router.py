from __future__ import annotations

"""Canonical Phase 1 engineering request router.

This router is a deterministic boundary. It never sends an engineering or
 delivery request to the general LLM path. Read-only requests go to the
readiness gateway; planning requests stay read-only; executable engineering
requests go to the canonical lifecycle; delivery operations require an
explicit, auditable Master approval.
"""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class EngineeringRequestClassification:
    is_engineering: bool
    is_read_only: bool
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_engineering": self.is_engineering,
            "is_read_only": self.is_read_only,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class EngineeringRequestRouter:
    """Single routing boundary for engineering and delivery requests."""

    VERSION = "ARIA-ENGINEERING-REQUEST-ROUTER-20261006"

    ENGINEERING_TERMS = (
        "code", "coding", "program", "programming", "software", "repository", "repo",
        "github", "git", "implement", "implementation", "develop", "development",
        "developer", "build", "bug", "debug", "debugging", "fix the error", "fix error",
        "fix the bug", "refactor", "refactoring", "feature", "functionality", "api",
        "backend", "frontend", "architecture", "deployment", "deploy", "test the code",
        "write code", "modify the code", "change the code", "create a file", "modify a file",
        "delete a file", "autonomous engineering", "engineering lifecycle", "engineering task",
        "add to aria", "add a capability", "add a feature to aria", "extend aria",
        "weather capability", "capability to aria",
    )

    SOFTWARE_INTENTS = {
        "software_development", "coding", "programming", "development", "engineering",
        "software_engineering", "repository_engineering",
    }

    READ_ONLY_TERMS = (
        "read only", "read-only", "readonly", "only inspect", "inspect only", "just inspect",
        "only analyze", "analyze only", "analysis only", "do not create", "don't create",
        "do not modify", "don't modify", "do not change", "don't change", "do not delete",
        "don't delete", "do not commit", "don't commit", "do not push", "don't push",
        "do not deploy", "don't deploy", "without modifying", "without changes",
        "without changing", "without creating", "without deleting", "without committing",
        "without pushing", "without deploying", "no modifications", "no changes",
        "plan only", "planning only", "phases only",
    )

    DELIVERY_TERMS = {
        "push": ("push", "github", "git push", "push to github", "push the project"),
        "merge": ("merge", "merge pr", "merge pull request"),
        "deploy": ("deploy", "deployment", "release to production", "publish to production"),
        "rollback": ("rollback", "roll back", "revert deployment"),
        "commit": ("commit", "git commit"),
    }

    def __init__(
        self,
        runtime: Any = None,
        *,
        lifecycle: Any = None,
        autonomous_engineering_lifecycle: Any = None,
        readiness_gateway: Any = None,
        delivery_authorization: Any = None,
        master_delivery_authorization: Any = None,
        execution_mode: Any = None,
        repository_intelligence: Any = None,
        capability_selector: Any = None,
    ) -> None:
        self.runtime = runtime
        self.lifecycle = lifecycle or autonomous_engineering_lifecycle
        self.readiness_gateway = readiness_gateway or self._runtime_component("phase1_readiness_gateway")
        self.delivery_authorization = delivery_authorization or master_delivery_authorization or self._runtime_component("master_delivery_authorization")
        self.execution_mode = execution_mode or self._runtime_component("engineering_execution_mode")
        self.repository_intelligence = repository_intelligence or self._runtime_component("repository_intelligence")
        self.capability_selector = capability_selector or self._runtime_component("unified_capability_selector")

    def classify(self, query: str, *, intent: Any = None, decision: Any = None) -> EngineeringRequestClassification:
        text = str(query or "").strip().lower()
        if not text:
            return EngineeringRequestClassification(False, False, 0.0, "empty_request")

        intent_name = self._intent_name(intent) or self._intent_name(self._decision_value(decision, "intent"))
        route_name = str(self._decision_value(decision, "route", "") or "").strip().lower()
        action_name = str(self._decision_value(decision, "action", "") or "").strip().lower()

        if (
            intent_name in self.SOFTWARE_INTENTS
            or route_name in self.SOFTWARE_INTENTS
            or action_name in {"coding", "development", "software_development", "engineering"}
        ):
            engineering, confidence, reason = True, 0.99, "software_development_decision"
        else:
            matches = [term for term in self.ENGINEERING_TERMS if term in text]
            engineering = bool(matches)
            confidence = 0.98 if len(matches) >= 3 else 0.95 if len(matches) == 2 else 0.90 if len(matches) == 1 else 0.0
            reason = "engineering_keywords" if engineering else "non_engineering_request"

        read_only = engineering and any(term in text for term in self.READ_ONLY_TERMS)
        if read_only:
            reason = "explicit_read_only_constraint"
        return EngineeringRequestClassification(engineering, read_only, confidence, reason)

    async def route(
        self,
        query: str,
        *,
        session_id: str = "",
        user_id: str = "",
        metadata: Mapping[str, Any] | None = None,
        intent: Any = None,
        decision: Any = None,
        **_: Any,
    ) -> Any:
        metadata = dict(metadata or {})
        classification = self.classify(query, intent=intent, decision=decision)
        if not classification.is_engineering:
            return None

        operation = self._delivery_operation(query)
        if operation is not None:
            return await self._route_delivery(
                query, operation, session_id=session_id, user_id=user_id, metadata=metadata
            )

        execution = self._execution_decision(query)
        if execution.get("mode") in {"plan_only", "inspect_only"} or classification.is_read_only:
            return await self._route_read_only_or_plan(
                query, classification, execution, session_id=session_id
            )

        return await self._route_execution(
            query, classification, session_id=session_id, user_id=user_id, metadata=metadata
        )

    async def _route_delivery(self, query: str, operation: str, *, session_id: str, user_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        auth = self.delivery_authorization
        if auth is None:
            return self._blocked_delivery(operation, "Master delivery authorization is unavailable.")

        request_id = str(metadata.get("approval_request_id") or metadata.get("master_approval_id") or "").strip()
        if not request_id:
            try:
                request = auth.request_approval(
                    operation=operation,
                    reason=str(query),
                    risk_level="high",
                    metadata={"session_id": session_id, "user_id": user_id, "source": metadata.get("source", "cognitive_core")},
                )
                request_id = str((request or {}).get("request_id") or (request or {}).get("id") or "")
            except Exception as exc:
                return self._blocked_delivery(operation, f"Master approval is required before {operation}.", error=str(exc))

            return self._blocked_delivery(
                operation,
                f"Master approval is required before {operation}. Approval request created.",
                approval_request_id=request_id,
            )

        try:
            status = auth.status(request_id)
        except Exception as exc:
            return self._blocked_delivery(operation, "The Master approval could not be verified.", approval_request_id=request_id, error=str(exc))

        if not bool(status.get("approved")) or status.get("authority") != getattr(auth, "MASTER_AUTHORITY", "Master"):
            return self._blocked_delivery(operation, "Master approval has not been granted for this operation.", approval_request_id=request_id)

        authorization = self._build_delivery_authorization(auth, request_id, operation)
        gateway = getattr(auth, "delivery_gateway", None)
        result = await self._invoke_delivery_gateway(gateway, operation, query, authorization, metadata)
        return {
            "success": bool(result.get("success", True)),
            "handled": True,
            "delivery": True,
            "authorized": True,
            "operation": operation,
            "approval_request_id": request_id,
            "result": result,
            "message": result.get("message") or f"{operation} was authorized and routed to the delivery gateway.",
        }

    async def _route_read_only_or_plan(self, query: str, classification: EngineeringRequestClassification, execution: dict[str, Any], *, session_id: str) -> dict[str, Any]:
        if execution.get("mode") == "plan_only":
            return {
                "success": True,
                "handled": True,
                "plan_only": True,
                "read_only": True,
                "execution_started": False,
                "mutation_performed": False,
                "classification": classification.to_dict(),
                "message": "Plan-only mode: no implementation, file mutation, commit, push, or deployment was performed.",
            }

        if execution.get("mode") == "inspect_only" or classification.is_read_only:
            gateway = self.readiness_gateway
            if gateway is None:
                return {"success": False, "handled": True, "read_only": True, "message": "The read-only readiness gateway is unavailable."}
            report = gateway.inspect(session_id=session_id or None)
            if hasattr(report, "__await__"):
                report = await report
            if not isinstance(report, dict):
                report = {"success": True, "result": report}
            return {
                "success": bool(report.get("success", True)),
                "handled": True,
                "read_only": True,
                "requires_readiness_gateway": False,
                "classification": classification.to_dict(),
                "result": report,
                "message": report.get("message") or report.get("summary") or "Read-only engineering inspection completed.",
            }

    async def _route_execution(self, query: str, classification: EngineeringRequestClassification, *, session_id: str, user_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        lifecycle = self.lifecycle
        if lifecycle is None:
            lifecycle = getattr(self.runtime, "develop", None)
            if not callable(lifecycle):
                raise RuntimeError("Canonical autonomous engineering lifecycle is unavailable.")
            result = lifecycle(query, session_id=session_id or None, metadata=metadata)
        else:
            method = getattr(lifecycle, "develop", None)
            if not callable(method):
                raise RuntimeError("Canonical autonomous engineering lifecycle does not expose develop().")
            result = method(query, session_id=session_id or None, metadata=metadata)

        if hasattr(result, "__await__"):
            result = await result
        return {
            "success": bool(getattr(result, "success", result.get("success", True) if isinstance(result, dict) else True)),
            "handled": True,
            "classification": classification.to_dict(),
            "result": result,
            "message": self._message(result),
        }

    def _execution_decision(self, query: str) -> dict[str, Any]:
        if self.execution_mode is not None:
            try:
                decision = self.execution_mode.decide(query)
                if hasattr(decision, "to_dict"):
                    return decision.to_dict()
                if isinstance(decision, dict):
                    return decision
            except Exception:
                pass
        lowered = str(query).lower()
        if any(x in lowered for x in ("plan only", "planning only", "phases only")):
            return {"mode": "plan_only", "execution_allowed": False}
        if any(x in lowered for x in self.READ_ONLY_TERMS):
            return {"mode": "inspect_only", "execution_allowed": False}
        return {"mode": "execute", "execution_allowed": True}

    def _delivery_operation(self, query: str) -> str | None:
        text = str(query or "").lower()
        for operation, terms in self.DELIVERY_TERMS.items():
            if any(term in text for term in terms):
                return operation
        return None

    @staticmethod
    def _blocked_delivery(operation: str, message: str, *, approval_request_id: str | None = None, error: str | None = None) -> dict[str, Any]:
        result = {
            "success": True,
            "handled": True,
            "delivery": True,
            "authorized": False,
            "blocked": True,
            "operation": operation,
            "message": message,
            "execution_started": False,
            "mutation_performed": False,
        }
        if approval_request_id:
            result["approval_request_id"] = approval_request_id
        if error:
            result["error"] = error
        return result

    @staticmethod
    def _build_delivery_authorization(auth: Any, request_id: str, operation: str) -> Any:
        if operation == "deploy":
            return auth.authorization_for_deployment(request_id)
        if operation == "rollback":
            return auth.authorization_for_rollback(request_id)
        try:
            from brain.development.contracts.engineering_git import GitOperation
            return auth.authorization_for_git(request_id, GitOperation(operation))
        except Exception:
            return None

    async def _invoke_delivery_gateway(self, gateway: Any, operation: str, query: str, authorization: Any, metadata: dict[str, Any]) -> dict[str, Any]:
        if gateway is None:
            return {"success": False, "message": "The delivery gateway is unavailable."}
        candidates = {
            "push": ("push", "github_push"),
            "merge": ("merge", "merge_pr", "github_merge"),
            "deploy": ("deploy", "deployment"),
            "rollback": ("rollback",),
            "commit": ("commit",),
        }.get(operation, (operation,))
        for name in candidates:
            method = getattr(gateway, name, None)
            if not callable(method):
                continue
            kwargs = {"authorization": authorization, "metadata": metadata, "request": query}
            try:
                value = method(**kwargs)
            except TypeError:
                try:
                    value = method(authorization=authorization)
                except TypeError:
                    value = method()
            if hasattr(value, "__await__"):
                value = await value
            if isinstance(value, dict):
                return value
            return {"success": bool(getattr(value, "success", True)), "result": value, "message": str(value)}
        return {"success": False, "message": f"No delivery gateway operation is available for {operation}."}

    def _runtime_component(self, name: str) -> Any:
        runtime = self.runtime
        getter = getattr(runtime, "get", None) if runtime is not None else None
        if callable(getter):
            try:
                return getter(name)
            except Exception:
                return None
        return None

    @staticmethod
    def _decision_value(value: Any, key: str, default: Any = None) -> Any:
        if value is None:
            return default
        if isinstance(value, Mapping):
            return value.get(key, default)
        return getattr(value, key, default)

    @staticmethod
    def _intent_name(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip().lower()
        return str(getattr(value, "intent", "") or "").strip().lower()

    @staticmethod
    def _message(result: Any) -> str:
        if isinstance(result, Mapping):
            return str(result.get("message") or result.get("response") or result.get("summary") or "")
        return str(getattr(result, "message", None) or getattr(result, "error", None) or result)

    def health(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "version": self.VERSION,
            "runtime_connected": self.runtime is not None,
            "lifecycle_connected": self.lifecycle is not None,
            "readiness_gateway_connected": self.readiness_gateway is not None,
            "delivery_authorization_connected": self.delivery_authorization is not None,
            "github_push_requires_authorization": True,
            "deployment_requires_authorization": True,
            "rollback_requires_authorization": True,
            "production_direct_write": False,
        }

    capabilities = health


__all__ = ["EngineeringRequestClassification", "EngineeringRequestRouter"]
