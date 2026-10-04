"""Repository self-model contracts for ARIA autonomous engineering.

Step 7 gives ARIA a durable representation of the repository it is operating
on. The model is descriptive only; it does not inspect or modify the
filesystem itself.

Later repository-intelligence services will populate this model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence


class RepositoryPathKind(str, Enum):
    """Classification of repository paths."""

    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    UNKNOWN = "unknown"


class RepositoryComponentKind(str, Enum):
    """High-level architectural component types."""

    APPLICATION = "application"
    CORE = "core"
    BRAIN = "brain"
    DEVELOPMENT = "development"
    INTEGRATION = "integration"
    TEST = "test"
    CONFIGURATION = "configuration"
    DOCUMENTATION = "documentation"
    SCRIPT = "script"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RepositoryPath:
    """One known repository path."""

    path: str
    kind: RepositoryPathKind
    size_bytes: int = 0
    extension: str = ""
    protected: bool = False
    generated: bool = False
    excluded_from_scan: bool = False
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError(
                "Repository path must not be empty."
            )

        if self.size_bytes < 0:
            raise ValueError(
                "size_bytes must be non-negative."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind.value,
            "size_bytes": self.size_bytes,
            "extension": self.extension,
            "protected": self.protected,
            "generated": self.generated,
            "excluded_from_scan": self.excluded_from_scan,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "RepositoryPath":
        if not isinstance(payload, dict):
            raise TypeError(
                "RepositoryPath payload must be a dictionary."
            )

        try:
            kind = RepositoryPathKind(
                str(
                    payload.get(
                        "kind",
                        RepositoryPathKind.UNKNOWN.value,
                    )
                )
            )
        except ValueError:
            kind = RepositoryPathKind.UNKNOWN

        return cls(
            path=str(
                payload.get(
                    "path",
                    "",
                )
            ),
            kind=kind,
            size_bytes=int(
                payload.get(
                    "size_bytes",
                    0,
                )
            ),
            extension=str(
                payload.get(
                    "extension",
                    "",
                )
            ),
            protected=bool(
                payload.get(
                    "protected",
                    False,
                )
            ),
            generated=bool(
                payload.get(
                    "generated",
                    False,
                )
            ),
            excluded_from_scan=bool(
                payload.get(
                    "excluded_from_scan",
                    False,
                )
            ),
            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )


@dataclass(frozen=True)
class RepositoryComponent:
    """One logical architectural component."""

    component_id: str
    name: str
    kind: RepositoryComponentKind

    root_paths: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    dependents: tuple[str, ...] = ()

    public_interfaces: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()

    confidence: float = 0.0
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.component_id.strip():
            raise ValueError(
                "component_id must not be empty."
            )

        if not self.name.strip():
            raise ValueError(
                "component name must not be empty."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "name": self.name,
            "kind": self.kind.value,
            "root_paths": list(self.root_paths),
            "files": list(self.files),
            "dependencies": list(self.dependencies),
            "dependents": list(self.dependents),
            "public_interfaces": list(
                self.public_interfaces
            ),
            "protected_paths": list(
                self.protected_paths
            ),
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "RepositoryComponent":
        if not isinstance(payload, dict):
            raise TypeError(
                "RepositoryComponent payload must be a dictionary."
            )

        try:
            kind = RepositoryComponentKind(
                str(
                    payload.get(
                        "kind",
                        RepositoryComponentKind.UNKNOWN.value,
                    )
                )
            )
        except ValueError:
            kind = RepositoryComponentKind.UNKNOWN

        return cls(
            component_id=str(
                payload.get(
                    "component_id",
                    "",
                )
            ),
            name=str(
                payload.get(
                    "name",
                    "",
                )
            ),
            kind=kind,
            root_paths=_string_tuple(
                payload.get("root_paths")
            ),
            files=_string_tuple(
                payload.get("files")
            ),
            dependencies=_string_tuple(
                payload.get("dependencies")
            ),
            dependents=_string_tuple(
                payload.get("dependents")
            ),
            public_interfaces=_string_tuple(
                payload.get("public_interfaces")
            ),
            protected_paths=_string_tuple(
                payload.get("protected_paths")
            ),
            confidence=float(
                payload.get(
                    "confidence",
                    0.0,
                )
            ),
            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )


@dataclass(frozen=True)
class RepositoryModel:
    """Complete structured model of the repository."""

    model_version: str

    repository_root: str

    files: tuple[RepositoryPath, ...] = ()
    components: tuple[RepositoryComponent, ...] = ()

    ignored_paths: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()
    generated_paths: tuple[str, ...] = ()

    entrypoints: tuple[str, ...] = ()
    test_roots: tuple[str, ...] = ()
    configuration_roots: tuple[str, ...] = ()

    architecture_summary: str = ""

    file_count: int = 0
    directory_count: int = 0

    confidence: float = 0.0

    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.repository_root.strip():
            raise ValueError(
                "repository_root must not be empty."
            )

        if self.file_count < 0:
            raise ValueError(
                "file_count must be non-negative."
            )

        if self.directory_count < 0:
            raise ValueError(
                "directory_count must be non-negative."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def path(
        self,
        relative_path: str,
    ) -> RepositoryPath | None:
        target = str(
            relative_path
        )

        for item in self.files:
            if item.path == target:
                return item

        return None

    def component(
        self,
        component_id: str,
    ) -> RepositoryComponent | None:
        target = str(
            component_id
        )

        for item in self.components:
            if item.component_id == target:
                return item

        return None

    def is_protected(
        self,
        relative_path: str,
    ) -> bool:
        target = str(
            relative_path
        )

        if target in self.protected_paths:
            return True

        item = self.path(
            target
        )

        return bool(
            item and item.protected
        )

    def is_ignored(
        self,
        relative_path: str,
    ) -> bool:
        target = str(
            relative_path
        )

        if target in self.ignored_paths:
            return True

        item = self.path(
            target
        )

        return bool(
            item and item.excluded_from_scan
        )

    def is_generated(
        self,
        relative_path: str,
    ) -> bool:
        target = str(
            relative_path
        )

        if target in self.generated_paths:
            return True

        item = self.path(
            target
        )

        return bool(
            item and item.generated
        )

    def dependency_chain(
        self,
        component_id: str,
    ) -> tuple[str, ...]:
        component = self.component(
            component_id
        )

        if component is None:
            return ()

        return component.dependencies

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "repository_root": self.repository_root,
            "files": [
                item.to_dict()
                for item in self.files
            ],
            "components": [
                item.to_dict()
                for item in self.components
            ],
            "ignored_paths": list(
                self.ignored_paths
            ),
            "protected_paths": list(
                self.protected_paths
            ),
            "generated_paths": list(
                self.generated_paths
            ),
            "entrypoints": list(
                self.entrypoints
            ),
            "test_roots": list(
                self.test_roots
            ),
            "configuration_roots": list(
                self.configuration_roots
            ),
            "architecture_summary": self.architecture_summary,
            "file_count": self.file_count,
            "directory_count": self.directory_count,
            "confidence": self.confidence,
            "warnings": list(
                self.warnings
            ),
            "metadata": dict(
                self.metadata
            ),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "RepositoryModel":
        if not isinstance(payload, dict):
            raise TypeError(
                "RepositoryModel payload must be a dictionary."
            )

        files = tuple(
            RepositoryPath.from_dict(item)
            for item in payload.get(
                "files",
                [],
            )
            if isinstance(item, dict)
        )

        components = tuple(
            RepositoryComponent.from_dict(item)
            for item in payload.get(
                "components",
                [],
            )
            if isinstance(item, dict)
        )

        return cls(
            model_version=str(
                payload.get(
                    "model_version",
                    "unknown",
                )
            ),
            repository_root=str(
                payload.get(
                    "repository_root",
                    "",
                )
            ),
            files=files,
            components=components,
            ignored_paths=_string_tuple(
                payload.get("ignored_paths")
            ),
            protected_paths=_string_tuple(
                payload.get("protected_paths")
            ),
            generated_paths=_string_tuple(
                payload.get("generated_paths")
            ),
            entrypoints=_string_tuple(
                payload.get("entrypoints")
            ),
            test_roots=_string_tuple(
                payload.get("test_roots")
            ),
            configuration_roots=_string_tuple(
                payload.get("configuration_roots")
            ),
            architecture_summary=str(
                payload.get(
                    "architecture_summary",
                    "",
                )
            ),
            file_count=int(
                payload.get(
                    "file_count",
                    0,
                )
            ),
            directory_count=int(
                payload.get(
                    "directory_count",
                    0,
                )
            ),
            confidence=float(
                payload.get(
                    "confidence",
                    0.0,
                )
            ),
            warnings=_string_tuple(
                payload.get("warnings")
            ),
            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )


def _string_tuple(
    value: Any,
) -> tuple[str, ...]:
    if value is None:
        return ()

    if isinstance(value, str):
        return (value,)

    if not isinstance(
        value,
        (list, tuple, set),
    ):
        raise TypeError(
            "Expected a string or sequence of strings."
        )

    return tuple(
        str(item)
        for item in value
    )


__all__ = [
    "RepositoryPathKind",
    "RepositoryComponentKind",
    "RepositoryPath",
    "RepositoryComponent",
    "RepositoryModel",
]