"""Authoritative implementation adapter for ARIA.

Step 11 connects the new engineering contracts to ARIA's existing
DevelopmentAgent / DevelopmentController implementation layer.

Important:

This adapter does not replace the existing implementation engine.

It translates:

    EngineeringSession
        +
    EngineeringTask
        ↓
    ImplementationRequest
        ↓
    Existing DevelopmentController
        ↓
    ImplementationResult

The authoritative session remains the source of engineering state.
"""

from __future__ import annotations

import inspect
from typing import Any, Mapping

from .contracts.engineering_implementation import (
    ImplementationChange,
    ImplementationEvidence,
    ImplementationRequest,
    ImplementationResult,
    ImplementationStatus,
)


class AuthoritativeImplementationEngine:
    """Adapter between EngineeringSession and legacy implementation."""

    VERSION = "PHASE1-AUTHORITATIVE-IMPLEMENTATION-20261004"

    def __init__(
        self,
        development_controller: Any,
        *,
        development_agent: Any | None = None,
    ) -> None:
        if development_controller is None:
            raise ValueError(
                "development_controller is required."
            )

        self.development_controller = (
            development_controller
        )

        self.development_agent = (
            development_agent
        )

    async def execute(
        self,
        request: ImplementationRequest,
    ) -> ImplementationResult:
        """Execute one implementation request through existing ARIA services."""

        if not isinstance(
            request,
            ImplementationRequest,
        ):
            raise TypeError(
                "request must be an ImplementationRequest."
            )

        try:
            raw_result = await self._invoke_controller(
                request
            )

            return self._normalize_result(
                request,
                raw_result,
            )

        except Exception as exc:
            return self._failure_result(
                request,
                exc,
            )

    async def _invoke_controller(
        self,
        request: ImplementationRequest,
    ) -> Any:
        """Call the existing DevelopmentController safely.

        The adapter deliberately keeps compatibility logic here instead
        of spreading it through the authoritative engineering contracts.
        """

        controller = (
            self.development_controller
        )

        execute = getattr(
            controller,
            "execute",
            None,
        )

        if execute is None:
            raise AttributeError(
                "DevelopmentController does not expose execute()."
            )

        kwargs: dict[str, Any] = {}

        signature = inspect.signature(
            execute
        )

        parameters = signature.parameters

        if "changes" in parameters:
            kwargs[
                "changes"
            ] = None

        if "test_paths" in parameters:
            kwargs[
                "test_paths"
            ] = None

        if "workspace_id" in parameters:
            kwargs[
                "workspace_id"
            ] = request.workspace_id

        result = execute(
            request.requirement,
            **kwargs,
        )

        if inspect.isawaitable(
            result
        ):
            return await result

        return result

    def _normalize_result(
        self,
        request: ImplementationRequest,
        raw_result: Any,
    ) -> ImplementationResult:
        """Translate legacy result objects into the canonical contract."""

        success = self._read_bool(
            raw_result,
            "success",
        )

        status_value = self._read_value(
            raw_result,
            "status",
        )

        if success is True:
            status = (
                ImplementationStatus.COMPLETED
            )
        elif status_value in {
            "blocked",
            "task_graph_blocked",
        }:
            status = (
                ImplementationStatus.BLOCKED
            )
        elif success is False:
            status = (
                ImplementationStatus.FAILED
            )
        else:
            status = (
                ImplementationStatus.COMPLETED
                if self._looks_successful(
                    raw_result
                )
                else ImplementationStatus.FAILED
            )

        changes = self._extract_changes(
            raw_result
        )

        changed_paths = tuple(
            item.path
            for item in changes
        )

        errors = self._extract_strings(
            raw_result,
            "errors",
        )

        diagnostics = self._extract_strings(
            raw_result,
            "diagnostics",
        )

        summary = str(
            self._read_value(
                raw_result,
                "summary",
            )
            or self._read_value(
                raw_result,
                "message",
            )
            or ""
        )

        evidence = ImplementationEvidence(
            evidence_id=(
                f"{request.session_id}:"
                f"{request.task_id}:implementation"
            ),
            task_id=request.task_id,
            status=status,
            changed_paths=changed_paths,
            changes=changes,
            workspace_id=(
                request.workspace_id
                or self._extract_workspace_id(
                    raw_result
                )
            ),
            implementation_summary=summary,
            diagnostics=diagnostics,
            errors=errors,
            metadata={
                "adapter_version": self.VERSION,
                "legacy_status": status_value,
            },
        )

        return ImplementationResult(
            session_id=request.session_id,
            task_id=request.task_id,
            status=status,
            evidence=evidence,
            changes=changes,
            workspace_id=(
                request.workspace_id
                or self._extract_workspace_id(
                    raw_result
                )
            ),
            next_action=(
                "continue_to_verification"
                if status
                is ImplementationStatus.COMPLETED
                else "diagnose_and_reassess"
            ),
            blockers=(
                errors
                if status
                is not ImplementationStatus.COMPLETED
                else ()
            ),
            metadata={
                "adapter_version": self.VERSION,
                "raw_result_type": type(
                    raw_result
                ).__name__,
                "legacy_report": self._safe_legacy_report(raw_result),
            },
        )

    @staticmethod
    def _safe_legacy_report(
        raw_result: Any,
    ) -> dict[str, Any]:
        """
        Preserve the useful validation/test evidence produced by the
        existing DevelopmentAgent without leaking a live result object
        into the authoritative contract.
        """
        method = getattr(
            raw_result,
            "to_dict",
            None,
        )
        if callable(method):
            try:
                value = method()
                if isinstance(value, dict):
                    return value
            except Exception:
                pass

        if isinstance(raw_result, dict):
            return dict(raw_result)

        return {
            "success": bool(
                getattr(raw_result, "success", False)
            ),
            "status": str(
                getattr(raw_result, "status", "")
            ),
            "errors": list(
                getattr(raw_result, "errors", ())
                or ()
            ),
        }

    @classmethod
    def _extract_workspace_id(
        cls,
        value: Any,
    ) -> str | None:
        workspace = cls._read_value(
            value,
            "workspace",
        )
        if isinstance(workspace, Mapping):
            raw = workspace.get("workspace_id") or workspace.get("id")
            return str(raw) if raw else None

        raw = getattr(
            workspace,
            "workspace_id",
            getattr(workspace, "id", None),
        )
        return str(raw) if raw else None

    def _failure_result(
        self,
        request: ImplementationRequest,
        exc: Exception,
    ) -> ImplementationResult:
        """Convert adapter/controller failure into canonical evidence."""

        message = (
            f"{type(exc).__name__}: {exc}"
        )

        evidence = ImplementationEvidence(
            evidence_id=(
                f"{request.session_id}:"
                f"{request.task_id}:implementation:error"
            ),
            task_id=request.task_id,
            status=ImplementationStatus.FAILED,
            changed_paths=(),
            changes=(),
            workspace_id=request.workspace_id,
            implementation_summary="",
            diagnostics=(
                message,
            ),
            errors=(
                message,
            ),
            metadata={
                "adapter_version": self.VERSION,
                "exception_type": type(
                    exc
                ).__name__,
            },
        )

        return ImplementationResult(
            session_id=request.session_id,
            task_id=request.task_id,
            status=ImplementationStatus.FAILED,
            evidence=evidence,
            changes=(),
            workspace_id=request.workspace_id,
            next_action="diagnose_and_reassess",
            blockers=(
                message,
            ),
            metadata={
                "adapter_version": self.VERSION,
            },
        )

    @staticmethod
    def _read_value(
        value: Any,
        name: str,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            Mapping,
        ):
            return value.get(
                name
            )

        direct = getattr(
            value,
            name,
            None,
        )
        if direct is not None:
            return direct

        # DevelopmentController returns DevelopmentJob, whose actual
        # engineering evidence lives in DevelopmentJob.report.
        report = getattr(
            value,
            "report",
            None,
        )
        if report is not None:
            return getattr(
                report,
                name,
                None,
            )

        return None

    @classmethod
    def _read_bool(
        cls,
        value: Any,
        name: str,
    ) -> bool | None:
        raw = cls._read_value(
            value,
            name,
        )

        if isinstance(
            raw,
            bool,
        ):
            return raw

        return None

    @classmethod
    def _looks_successful(
        cls,
        value: Any,
    ) -> bool:
        status = cls._read_value(
            value,
            "status",
        )

        if isinstance(
            status,
            str,
        ):
            normalized = status.lower()

            if normalized in {
                "success",
                "completed",
                "accepted",
                "passed",
            }:
                return True

        return False

    @classmethod
    def _extract_strings(
        cls,
        value: Any,
        name: str,
    ) -> tuple[str, ...]:
        raw = cls._read_value(
            value,
            name,
        )

        if raw is None:
            return ()

        if isinstance(
            raw,
            str,
        ):
            return (
                raw,
            )

        if isinstance(
            raw,
            (list, tuple, set),
        ):
            return tuple(
                str(item)
                for item in raw
                if str(item).strip()
            )

        return (
            str(raw),
        )

    @classmethod
    def _extract_changes(
        cls,
        value: Any,
    ) -> tuple[ImplementationChange, ...]:
        raw = cls._read_value(
            value,
            "changes",
        )

        if raw is None:
            return ()

        if isinstance(
            raw,
            Mapping,
        ):
            raw = [
                raw,
            ]

        if not isinstance(
            raw,
            (list, tuple),
        ):
            return ()

        changes: list[
            ImplementationChange
        ] = []

        for item in raw:
            if isinstance(
                item,
                ImplementationChange,
            ):
                changes.append(
                    item
                )
                continue

            if isinstance(
                item,
                Mapping,
            ):
                path = str(
                    item.get(
                        "path",
                        "",
                    )
                ).strip()

                if not path:
                    continue

                operation = str(
                    item.get(
                        "operation",
                        "modify",
                    )
                )

                content = item.get(
                    "content"
                )

                changes.append(
                    ImplementationChange(
                        path=path,
                        content=(
                            str(content)
                            if content is not None
                            else None
                        ),
                        operation=operation,
                        reason=str(
                            item.get(
                                "reason",
                                "",
                            )
                        ),
                        metadata=dict(
                            item.get(
                                "metadata",
                                {},
                            )
                        ),
                    )
                )

        return tuple(
            changes
        )


__all__ = [
    "AuthoritativeImplementationEngine",
]