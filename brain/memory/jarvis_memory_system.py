"""Canonical persistent memory and project-memory gateway for ARIA.

Step 5 of the JARVIS integration.  This module unifies the already existing
memory components without replacing them and without executing tools.

Responsibilities:
- working/recent conversation memory
- durable personal memory through MemoryEngine
- repository/project memory through RepositoryMemory
- execution experience through ExperienceEngine
- deterministic recall and learning APIs
- safe degradation when MongoDB or optional services are unavailable

The gateway never writes source files, commits, pushes, deploys, or executes
engineering tasks.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aria")


class JarvisMemorySystem:
    """Single memory boundary used by the future final cognitive integration."""

    VERSION = "ARIA-JARVIS-MEMORY-20261006"

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
            "errors": 0,
        }

    # ------------------------------------------------------------------
    # Health / status
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        return {
            "healthy": True,
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
            self.working_memory.set(key, value)
            return True
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] working-memory write failed")
            return False

    def recall_working(self, key: str, default: Any = None) -> Any:
        if self.working_memory is None:
            return default

        try:
            return self.working_memory.get(key, default)
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] working-memory read failed")
            return default

    def working_snapshot(self) -> Dict[str, Any]:
        if self.working_memory is None:
            return {}

        try:
            return dict(self.working_memory.snapshot())
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] working-memory snapshot failed")
            return {}

    # ------------------------------------------------------------------
    # Durable personal memory
    # ------------------------------------------------------------------

    async def remember(
        self,
        memory: Any,
        *,
        explicit: bool = False,
    ) -> Any:
        """Store durable memory through the existing MemoryEngine/Router."""
        self._statistics["stores"] += 1

        try:
            if self.memory_router is not None and hasattr(
                self.memory_router,
                "store_profile",
            ) and isinstance(memory, dict):
                result = await self.memory_router.store_profile(memory)
                if result is not None:
                    return result

            if self.memory_engine is not None:
                processor = getattr(
                    self.memory_engine,
                    "process_and_store",
                    None,
                )
                if processor is not None:
                    return await self._maybe_await(
                        processor(memory)
                    )

            if self.working_memory is not None and isinstance(memory, dict):
                key = str(memory.get("key") or "memory")
                value = memory.get("value", memory)
                self.working_memory.set(key, value)
                return {"success": True, "working_memory": True}

            return {"success": False, "reason": "no_memory_backend"}
        except Exception as exc:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] durable memory write failed")
            return {
                "success": False,
                "error": str(exc),
                "explicit": explicit,
            }

    async def recall(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Recall relevant information across memory layers."""
        self._statistics["recalls"] += 1
        limit = max(1, min(int(limit), 100))

        result: Dict[str, Any] = {
            "query": query,
            "working_memory": self.working_snapshot(),
            "personal_memory": [],
            "repository_memory": [],
            "experiences": [],
            "knowledge": None,
            "graph": None,
        }

        try:
            if self.memory_engine is not None:
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

        try:
            result["repository_memory"] = self._repository_recall(
                query,
                limit,
            )
        except Exception:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] repository-memory recall failed")

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

        return result

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
            self.repository_memory.store(
                repository_name,
                parsed_files,
            )
            self._statistics["repository_snapshots"] += 1
            return {
                "success": True,
                "repository": repository_name,
                "files": len(parsed_files or []),
            }
        except Exception as exc:
            self._statistics["errors"] += 1
            logger.exception("[JarvisMemory] repository-memory write failed")
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
            return self.repository_memory.get_repository(
                repository_name
            )
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

        results: List[Dict[str, Any]] = []
        repositories = getattr(
            self.repository_memory,
            "repositories",
            {},
        )

        if not isinstance(repositories, dict):
            return []

        terms = [
            item for item in normalized.replace("/", " ").split()
            if len(item) >= 3
        ]

        for repository, files in repositories.items():
            if not isinstance(files, list):
                continue

            for item in files:
                if not isinstance(item, dict):
                    continue

                searchable = " ".join(
                    [
                        str(item.get("file", "")),
                        " ".join(
                            str(x.get("name", ""))
                            for x in item.get("classes", [])
                            if isinstance(x, dict)
                        ),
                        " ".join(
                            str(x.get("name", ""))
                            for x in item.get("functions", [])
                            if isinstance(x, dict)
                        ),
                    ]
                ).lower()

                score = sum(
                    1 for term in terms
                    if term in searchable
                )

                if score:
                    results.append({
                        "repository": repository,
                        "file": item.get("file", ""),
                        "score": score,
                        "classes": item.get("classes", []),
                        "functions": item.get("functions", []),
                    })

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
            recorder = getattr(
                self.experience_engine,
                "record",
                None,
            )
            if recorder is not None:
                return await self._maybe_await(
                    recorder(outcome)
                )

            recorder = getattr(
                self.experience_engine,
                "record_experience",
                None,
            )
            if recorder is not None:
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

        return await self.remember({
            "key": "successful_pattern",
            "value": {
                "task": task_description,
                "outcome": outcome,
            },
            "memory_type": "experience",
        })

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

        return await self.remember({
            "key": "failure_pattern",
            "value": {
                "task": task_description,
                "error": str(error),
            },
            "memory_type": "experience",
        })

    # ------------------------------------------------------------------
    # Unified context
    # ------------------------------------------------------------------

    async def build_context(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Build a memory context packet without invoking execution."""
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

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value
