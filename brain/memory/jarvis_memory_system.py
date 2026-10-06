"""Canonical persistent memory and project-memory gateway for ARIA.

This module is the single JARVIS-facing memory boundary around ARIA's
existing memory owners.  It does not replace MemoryEngine, MemoryRouter,
RepositoryMemory, KnowledgeDatabase, KnowledgeGraph, or ExperienceEngine.

Responsibilities:
- working/recent conversation memory
- durable personal/project memory through existing memory owners
- repository/project memory through RepositoryMemory
- execution experience through ExperienceEngine
- deterministic recall and learning APIs
- safe degradation when optional persistence services are unavailable

The gateway never writes source files, commits, pushes, deploys, or executes
engineering tasks.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger("aria")


class JarvisMemorySystem:
    """Single memory boundary used by the canonical JARVIS integration."""

    VERSION = "ARIA-JARVIS-MEMORY-20261006-INTEGRATED"

    def __init__(
        self,
        *,
        working_memory=None,
        memory_engine=None,
        memory_router=None,
        repository_memory=None,
        experience_engine=None,
        knowledge_database=None,
        knowledge_graph=None,
    ) -> None:
        self.working_memory = working_memory
        self.memory_engine = memory_engine
        self.memory_router = memory_router
        self.repository_memory = repository_memory
        self.experience_engine = experience_engine
        self.knowledge_database = knowledge_database
        self.knowledge_graph = knowledge_graph

        self._statistics = {
            "recalls": 0,
            "stores": 0,
            "experiences": 0,
            "repository_snapshots": 0,
            "knowledge_writes": 0,
            "graph_writes": 0,
            "errors": 0,
        }

    # ------------------------------------------------------------------
    # Health / status
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        required = (
            self.working_memory is not None
            or self.memory_engine is not None
            or self.memory_router is not None
        )

        return {
            "healthy": bool(required),
            "version": self.VERSION,
            "working_memory": self.working_memory is not None,
            "memory_engine": self.memory_engine is not None,
            "memory_router": self.memory_router is not None,
            "repository_memory": self.repository_memory is not None,
            "experience_engine": self.experience_engine is not None,
            "knowledge_database": self.knowledge_database is not None,
            "knowledge_graph": self.knowledge_graph is not None,
            "statistics": dict(self._statistics),
        }

    def status(self) -> Dict[str, Any]:
        return self.health()

    # ------------------------------------------------------------------
    # Working memory
    # ------------------------------------------------------------------

    def remember_working(self, key: str, value: Any) -> bool:
        if self.working_memory is None:
            return False

        try:
            setter = getattr(self.working_memory, "set", None)
            if setter is None:
                return False
            setter(key, value)
            return True
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] working-memory write failed")
            return False

    def recall_working(self, key: str, default: Any = None) -> Any:
        if self.working_memory is None:
            return default

        try:
            getter = getattr(self.working_memory, "get", None)
            if getter is None:
                return default
            return getter(key, default)
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] working-memory read failed")
            return default

    def working_snapshot(self) -> Dict[str, Any]:
        if self.working_memory is None:
            return {}

        try:
            snapshot = getattr(self.working_memory, "snapshot", None)
            if snapshot is None:
                return {}
            value = snapshot()
            return dict(value or {})
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] working-memory snapshot failed")
            return {}

    # ------------------------------------------------------------------
    # Durable memory normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _memory_text(memory: Any) -> str:
        """Convert a memory object into the text API expected by MemoryEngine."""
        if isinstance(memory, str):
            return memory.strip()

        if isinstance(memory, Mapping):
            key = str(memory.get("key") or "memory").strip()
            value = memory.get("value")
            category = str(memory.get("category") or "").strip()

            if isinstance(value, Mapping):
                value_text = "; ".join(
                    f"{k}: {v}" for k, v in value.items()
                )
            elif isinstance(value, (list, tuple, set)):
                value_text = ", ".join(str(item) for item in value)
            else:
                value_text = str(value if value is not None else "").strip()

            prefix = f"{category}: " if category else ""
            if key and value_text:
                return f"{prefix}{key}: {value_text}".strip()
            return f"{prefix}{value_text}".strip()

        return str(memory).strip()

    @staticmethod
    def _profile_payload(memory: Any) -> Optional[Dict[str, Any]]:
        """Return a profile payload only for explicit profile-style memory."""
        if not isinstance(memory, Mapping):
            return None

        category = str(memory.get("category") or "").strip().lower()
        memory_type = str(memory.get("memory_type") or "").strip().lower()

        if category not in {
            "profile",
            "personal",
            "preference",
            "user",
        } and memory_type not in {
            "profile",
            "preference",
        }:
            return None

        key = str(memory.get("key") or "").strip()
        if not key:
            return None

        return {
            key: memory.get("value"),
        }

    async def _store_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Use the existing profile owner without falling through incorrectly.

        MemoryRouter/MemoryEngine's store_profile methods intentionally return
        None on successful persistence.  The old JARVIS wrapper treated None
        as failure and then passed the dictionary into process_and_store(),
        whose contract requires a string.  That caused the observed durable
        memory write failures.
        """
        owner = self.memory_router
        if owner is None:
            owner = self.memory_engine

        method = getattr(owner, "store_profile", None) if owner else None
        if method is None:
            return {
                "success": False,
                "reason": "profile_store_unavailable",
            }

        await self._maybe_await(method(payload))
        return {
            "success": True,
            "backend": type(owner).__name__,
            "profile": dict(payload),
        }

    async def _store_text(self, text: str) -> Dict[str, Any]:
        """Store ordinary memory through the existing canonical memory router."""
        if not text:
            return {
                "success": False,
                "reason": "empty_memory",
            }

        # MemoryRouter is the preferred owner when it exposes store_chat.
        if self.memory_router is not None:
            method = getattr(self.memory_router, "store_chat", None)
            if method is not None:
                result = await self._maybe_await(method(text))
                return {
                    "success": True,
                    "backend": type(self.memory_router).__name__,
                    "result": result,
                }

        # MemoryEngine's process_and_store explicitly accepts user_text:str.
        if self.memory_engine is not None:
            method = getattr(self.memory_engine, "process_and_store", None)
            if method is not None:
                result = await self._maybe_await(method(text))
                return {
                    "success": True,
                    "backend": type(self.memory_engine).__name__,
                    "result": result,
                }

        if self.working_memory is not None:
            self.working_memory.set("last_memory", text)
            return {
                "success": True,
                "backend": type(self.working_memory).__name__,
                "working_memory": True,
            }

        return {
            "success": False,
            "reason": "no_memory_backend",
        }

    # ------------------------------------------------------------------
    # Durable personal/project memory
    # ------------------------------------------------------------------

    async def remember(
        self,
        memory: Any,
        *,
        explicit: bool = False,
    ) -> Any:
        """Store durable memory through existing authoritative owners.

        The important contract is that dictionaries are never passed directly
        to MemoryEngine.process_and_store(), whose API requires text.
        """
        self._statistics["stores"] += 1

        try:
            profile = self._profile_payload(memory)
            if profile is not None:
                result = await self._store_profile(profile)
            else:
                text = self._memory_text(memory)
                result = await self._store_text(text)

            if not result.get("success"):
                return {
                    **result,
                    "explicit": explicit,
                }

            # KnowledgeDB is a secondary durable project/knowledge surface,
            # not the primary memory owner.  It is intentionally best-effort.
            await self._store_knowledge_best_effort(memory)

            return {
                **result,
                "explicit": explicit,
            }

        except Exception as exc:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] durable memory write failed")
            return {
                "success": False,
                "error": str(exc),
                "explicit": explicit,
            }

    async def _store_knowledge_best_effort(self, memory: Any) -> None:
        if self.knowledge_database is None:
            return

        text = self._memory_text(memory)
        if not text:
            return

        title = "jarvis_memory"
        if isinstance(memory, Mapping):
            title = str(memory.get("key") or title).strip() or title

        try:
            method = getattr(self.knowledge_database, "store", None)
            if method is None:
                return

            await self._maybe_await(
                method(
                    title=title,
                    content=text,
                    source="jarvis_memory",
                    metadata={"version": self.VERSION},
                )
            )
            self._statistics["knowledge_writes"] += 1
        except Exception:
            # KnowledgeDB is supplementary. MemoryEngine remains authoritative.
            self._statistics["errors"] += 1
            logger.warning(
                "[JarvisMemory] secondary knowledge write failed",
                exc_info=True,
            )

    async def recall(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Recall relevant information across all available memory layers."""
        self._statistics["recalls"] += 1
        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 10

        result: Dict[str, Any] = {
            "query": query,
            "working_memory": self.working_snapshot(),
            "personal_memory": [],
            "repository_memory": [],
            "experiences": [],
            "knowledge": None,
            "graph": None,
        }

        # --------------------------------------------------------------
        # Personal memory
        # --------------------------------------------------------------
        try:
            if self.memory_router is not None:
                getter = getattr(
                    self.memory_router,
                    "recall",
                    None,
                )
                if getter is not None:
                    memories = await self._maybe_await(
                        getter(query)
                    )
                    if isinstance(memories, Mapping):
                        memories = (
                            memories.get("personal_memory")
                            or memories.get("memories")
                            or []
                        )
                    if memories:
                        result["personal_memory"] = list(memories)[:limit]

            if not result["personal_memory"] and self.memory_engine is not None:
                getter = getattr(
                    self.memory_engine,
                    "get_relevant_memories",
                    None,
                )
                if getter is not None:
                    memories = await self._maybe_await(
                        getter(query, limit=limit)
                    )
                    if memories:
                        result["personal_memory"] = list(memories)[:limit]
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] personal-memory recall failed")

        # --------------------------------------------------------------
        # Repository memory
        # --------------------------------------------------------------
        try:
            result["repository_memory"] = self._repository_recall(
                query,
                limit,
            )
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] repository-memory recall failed")

        # --------------------------------------------------------------
        # Experience memory
        # --------------------------------------------------------------
        try:
            if self.experience_engine is not None:
                finder = getattr(
                    self.experience_engine,
                    "find_similar",
                    None,
                )
                if finder is not None:
                    experiences = await self._maybe_await(
                        finder(query, limit=limit)
                    )
                    if experiences:
                        result["experiences"] = list(experiences)[:limit]
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] experience recall failed")

        # --------------------------------------------------------------
        # Knowledge database / graph are optional supporting context.
        # We only call methods that are actually exposed by the existing
        # implementations.
        # --------------------------------------------------------------
        try:
            result["knowledge"] = await self._knowledge_recall(
                query,
                limit,
            )
        except Exception:
            self._statistics["errors"] += 1
            logger.warning(
                "[JarvisMemory] knowledge recall unavailable",
                exc_info=True,
            )

        return result

    async def _knowledge_recall(
        self,
        query: str,
        limit: int,
    ) -> Any:
        if self.knowledge_database is None:
            return None

        for name in (
            "search",
            "query",
            "search_knowledge",
            "find_relevant",
        ):
            method = getattr(
                self.knowledge_database,
                name,
                None,
            )
            if method is None:
                continue

            try:
                value = await self._maybe_await(
                    method(query, limit=limit)
                )
            except TypeError:
                value = await self._maybe_await(
                    method(query)
                )
            return value

        return None

    # ------------------------------------------------------------------
    # Repository / project memory
    # ------------------------------------------------------------------

    def remember_repository(
        self,
        repository_name: str,
        parsed_files: Any,
    ) -> Dict[str, Any]:
        if self.repository_memory is None:
            return {
                "success": False,
                "reason": "repository_memory_unavailable",
            }

        try:
            store = getattr(
                self.repository_memory,
                "store",
                None,
            )
            if store is None:
                return {
                    "success": False,
                    "reason": "repository_store_unavailable",
                }

            files = parsed_files or []
            store(repository_name, files)
            self._statistics["repository_snapshots"] += 1
            return {
                "success": True,
                "repository": repository_name,
                "files": len(files),
            }
        except Exception as exc:
            self._statistics["errors"] += 1
            logger.exception(
                "[JarvisMemory] repository-memory write failed"
            )
            return {
                "success": False,
                "error": str(exc),
            }

    def repository_snapshot(
        self,
        repository_name: str,
    ) -> Any:
        if self.repository_memory is None:
            return None

        try:
            getter = getattr(
                self.repository_memory,
                "get_repository",
                None,
            )
            if getter is None:
                return None
            return getter(repository_name)
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] repository snapshot failed")
            return None

    def _repository_recall(
        self,
        query: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        if self.repository_memory is None:
            return []

        normalized = str(query or "").strip().lower()
        if not normalized:
            return []

        repositories = getattr(
            self.repository_memory,
            "repositories",
            {},
        )

        if not isinstance(repositories, dict):
            return []

        terms = [
            item
            for item in normalized.replace("/", " ").split()
            if len(item) >= 3
        ]

        results: List[Dict[str, Any]] = []

        for repository, files in repositories.items():
            if not isinstance(files, list):
                continue

            for item in files:
                if not isinstance(item, dict):
                    continue

                classes = item.get("classes", [])
                functions = item.get("functions", [])

                searchable = " ".join(
                    [
                        str(item.get("file", "")),
                        " ".join(
                            str(x.get("name", ""))
                            for x in classes
                            if isinstance(x, dict)
                        ),
                        " ".join(
                            str(x.get("name", ""))
                            for x in functions
                            if isinstance(x, dict)
                        ),
                    ]
                ).lower()

                score = sum(
                    1
                    for term in terms
                    if term in searchable
                )

                if score:
                    results.append(
                        {
                            "repository": repository,
                            "file": item.get("file", ""),
                            "score": score,
                            "classes": classes,
                            "functions": functions,
                        }
                    )

        results.sort(
            key=lambda item: item.get("score", 0),
            reverse=True,
        )
        return results[:limit]

    # ------------------------------------------------------------------
    # Experience / learning
    # ------------------------------------------------------------------

    async def record_experience(
        self,
        outcome: Any,
    ) -> Any:
        if self.experience_engine is None:
            return {
                "success": False,
                "reason": "experience_engine_unavailable",
            }

        self._statistics["experiences"] += 1

        try:
            for method_name in (
                "record",
                "record_experience",
            ):
                recorder = getattr(
                    self.experience_engine,
                    method_name,
                    None,
                )
                if recorder is None:
                    continue

                return await self._maybe_await(
                    recorder(outcome)
                )

            return {
                "success": False,
                "reason": "experience_record_method_unavailable",
            }
        except Exception as exc:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] experience write failed")
            return {
                "success": False,
                "error": str(exc),
            }

    async def learn_success(
        self,
        task_description: str,
        outcome: Any,
    ) -> Any:
        if self.memory_router is not None:
            method = getattr(
                self.memory_router,
                "learn_from_success",
                None,
            )
            if method is not None:
                return await self._maybe_await(
                    method(task_description, outcome)
                )

        return await self.record_experience(
            {
                "type": "success",
                "task": task_description,
                "outcome": outcome,
            }
        )

    async def learn_failure(
        self,
        task_description: str,
        error: Any,
    ) -> Any:
        if self.memory_router is not None:
            method = getattr(
                self.memory_router,
                "learn_from_failure",
                None,
            )
            if method is not None:
                return await self._maybe_await(
                    method(task_description, str(error))
                )

        return await self.record_experience(
            {
                "type": "failure",
                "task": task_description,
                "error": str(error),
            }
        )

    # ------------------------------------------------------------------
    # Unified JARVIS context
    # ------------------------------------------------------------------

    async def build_context(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Build a read-only memory context packet for JARVIS."""
        recall = await self.recall(
            query,
            limit=limit,
        )

        return {
            "memory_system": self.VERSION,
            "query": query,
            "working_memory": recall["working_memory"],
            "personal_memory": recall["personal_memory"],
            "repository_memory": recall["repository_memory"],
            "experiences": recall["experiences"],
            "knowledge": recall["knowledge"],
            "graph": recall["graph"],
            "read_only": True,
            "execution_started": False,
        }

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value


__all__ = [
    "JarvisMemorySystem",
]
