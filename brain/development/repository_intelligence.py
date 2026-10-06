from __future__ import annotations

"""Canonical read-only repository and GitHub intelligence for ARIA.

Step 2 establishes one repository-understanding boundary.  It combines the
existing local repository scanner, architecture/dependency analysis, deep
repository reasoning, Git state, and GitHub remote metadata/tree information.

This service never edits source files, commits, pushes, deploys, or exposes
GitHub credentials to the model.  Remote GitHub reads use the GitHub API when
possible; public repositories work without credentials, while private
repositories require GITHUB_TOKEN or GH_TOKEN.
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .architecture_intelligence import ArchitectureIntelligence
from .deep_repository_reasoning import DeepRepositoryReasoner
from .github_manager import GitHubManager
from .repository_manager import RepositoryManager

logger = logging.getLogger("aria.repository_intelligence")


@dataclass(frozen=True)
class RepositoryIntelligenceResult:
    success: bool
    repository_root: str
    request: str = ""
    local: dict[str, Any] = field(default_factory=dict)
    architecture: dict[str, Any] = field(default_factory=dict)
    reasoning: dict[str, Any] = field(default_factory=dict)
    git: dict[str, Any] = field(default_factory=dict)
    github: dict[str, Any] = field(default_factory=dict)
    relevant_files: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    confidence: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "repository_root": self.repository_root,
            "request": self.request,
            "local": dict(self.local),
            "architecture": dict(self.architecture),
            "reasoning": dict(self.reasoning),
            "git": dict(self.git),
            "github": dict(self.github),
            "relevant_files": list(self.relevant_files),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "confidence": self.confidence,
        }


class RepositoryIntelligenceService:
    """Single read-only repository-understanding boundary."""

    VERSION = "ARIA-REPOSITORY-INTELLIGENCE-20261006"

    def __init__(
        self,
        *,
        repository_manager: RepositoryManager,
        architecture_intelligence: ArchitectureIntelligence,
        git_manager: Any | None = None,
        github_manager: GitHubManager | None = None,
        max_file_read_bytes: int = 512 * 1024,
        max_relevant_files: int = 80,
        github_timeout: float = 20.0,
    ) -> None:
        self.repository_manager = repository_manager
        self.architecture_intelligence = architecture_intelligence
        self.git_manager = git_manager
        self.github_manager = github_manager
        self.max_file_read_bytes = max(32 * 1024, int(max_file_read_bytes))
        self.max_relevant_files = max(1, int(max_relevant_files))
        self.max_evidence_chars_per_file = 32_000
        self.max_total_evidence_chars = 1_500_000
        self.github_timeout = max(1.0, float(github_timeout))
        self._reasoner = DeepRepositoryReasoner(architecture_intelligence)
        self._cache: dict[str, RepositoryIntelligenceResult] = {}

    @property
    def repository_root(self) -> Path:
        manager_root = getattr(self.git_manager, "repository_root", None)
        if manager_root:
            return Path(manager_root).expanduser().resolve()
        return Path.cwd().resolve()

    def inspect(self, repository_path: str | Path | None = None) -> dict[str, Any]:
        """Return a complete local repository model without executing project code."""
        root = Path(repository_path or self.repository_root).expanduser().resolve()
        snapshot = self.repository_manager.inspect(root)
        architecture = self.architecture_intelligence.inspect(root)
        local = snapshot.to_dict()
        return {
            "version": self.VERSION,
            "repository_root": str(root),
            "snapshot": local,
            "files": list(local.get("files", [])),
            "local": local,
            "architecture": architecture.to_dict(),
        }

    async def understand(
        self,
        request: str,
        *,
        requirement: Any | None = None,
        metadata: dict[str, Any] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Build the repository context required before engineering planning."""
        normalized = str(request or "").strip()
        root = self.repository_root
        cache_key = f"{root}:{normalized[:2000]}"

        if not force_refresh and cache_key in self._cache:
            cached = self._cache[cache_key].to_dict()
            cached["snapshot"] = dict(cached.get("local", {}))
            cached["snapshot"].pop("file_evidence", None)
            cached["files"] = list(cached["snapshot"].get("files", []))
            cached["cached"] = True
            return cached

        errors: list[str] = []
        warnings: list[str] = []

        try:
            local = await asyncio.to_thread(self.repository_manager.inspect, root)
            architecture = await asyncio.to_thread(self.architecture_intelligence.inspect, root)
            reasoning = await asyncio.to_thread(
                self._reasoner.analyze,
                root,
                requirement_text=self._requirement_text(requirement, normalized),
                keywords=self._keywords(normalized, requirement),
            )
        except Exception as exc:
            logger.exception("[RepositoryIntelligence] Local repository analysis failed")
            return {
                "success": False,
                "version": self.VERSION,
                "repository_root": str(root),
                "error": f"Local repository analysis failed: {exc}",
                "warnings": [],
                "errors": [str(exc)],
                "confidence": "low",
            }

        git_state = await self._git_state()
        github_state = await self._github_state(git_state, warnings, errors)

        relevant = list(reasoning.relevant_files[: self.max_relevant_files])
        file_evidence = await asyncio.to_thread(
            self._read_relevant_files,
            root,
            relevant,
        )

        architecture_data = architecture.to_dict()
        reasoning_data = reasoning.to_dict()
        warnings.extend(str(x) for x in reasoning.warnings)
        errors.extend(str(x) for x in reasoning.analysis_errors)

        result = RepositoryIntelligenceResult(
            success=True,
            repository_root=str(root),
            request=normalized,
            local={
                **local.to_dict(),
                "file_evidence": file_evidence,
            },
            architecture=architecture_data,
            reasoning=reasoning_data,
            git=git_state,
            github=github_state,
            relevant_files=tuple(relevant),
            warnings=tuple(dict.fromkeys(warnings)),
            errors=tuple(dict.fromkeys(errors)),
            confidence=reasoning.confidence,
        )
        self._cache[cache_key] = result
        payload = result.to_dict()
        payload["snapshot"] = dict(result.local)
        payload["snapshot"].pop("file_evidence", None)
        payload["files"] = list(payload["snapshot"].get("files", []))
        payload["cached"] = False
        logger.info(
            "[RepositoryIntelligence] Repository understood | files=%s | relevant=%s | github=%s | confidence=%s",
            local.total_files,
            len(relevant),
            bool(github_state.get("available")),
            reasoning.confidence,
        )
        return payload

    async def read_file(
        self,
        relative_path: str,
        *,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Read one repository file safely; never follows paths outside the repo."""
        root = self.repository_root
        metadata = self.repository_manager.get_file_metadata(root, relative_path)
        if metadata.is_protected:
            return {
                "success": False,
                "path": metadata.path,
                "protected": True,
                "error": "Protected repository files cannot be exposed through generic file reading.",
            }
        path = (root / relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("Requested path escapes the repository root.") from exc
        limit = max(1024, int(max_bytes or self.max_file_read_bytes))
        if metadata.size_bytes > limit:
            return {
                "success": False,
                "path": metadata.path,
                "size_bytes": metadata.size_bytes,
                "truncated": True,
                "error": f"File exceeds read limit of {limit} bytes.",
            }
        text = path.read_text(encoding="utf-8", errors="replace")
        return {
            "success": True,
            "path": metadata.path,
            "size_bytes": metadata.size_bytes,
            "sha256": metadata.sha256,
            "content": text,
        }

    def search_files(self, query: str, *, limit: int = 40) -> list[dict[str, Any]]:
        """Search repository text without executing repository code."""
        needle = str(query or "").strip().lower()
        if not needle:
            return []
        root = self.repository_root
        snapshot = self.repository_manager.inspect(root)
        results: list[dict[str, Any]] = []
        for item in snapshot.files:
            if item.is_protected or item.size_bytes > self.max_file_read_bytes:
                continue
            if item.language not in {"python", "javascript", "typescript", "markdown", "text", "json", "yaml", "toml", "sql", "shell"}:
                continue
            try:
                content = (root / item.path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if needle in content.lower() or needle in item.path.lower():
                results.append({
                    "path": item.path,
                    "language": item.language,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                })
                if len(results) >= max(1, int(limit)):
                    break
        return results

    def clear_cache(self) -> None:
        self._cache.clear()

    async def health(self) -> dict[str, Any]:
        root = self.repository_root
        healthy = root.is_dir() and self.repository_manager is not None and self.architecture_intelligence is not None
        return {
            "healthy": healthy,
            "version": self.VERSION,
            "repository_root": str(root),
            "repository_manager": self.repository_manager is not None,
            "architecture_intelligence": self.architecture_intelligence is not None,
            "github_manager": self.github_manager is not None,
            "git_manager": self.git_manager is not None,
            "read_only": True,
            "execution": False,
            "push": False,
            "deployment": False,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "type": type(self).__name__,
            "read_only": True,
            "capabilities": [
                "local_repository_inventory",
                "architecture_analysis",
                "dependency_analysis",
                "deep_repository_reasoning",
                "git_state",
                "github_metadata",
                "github_tree",
                "relevant_file_evidence",
                "safe_file_read",
                "repository_search",
            ],
            "forbidden": ["modify_files", "commit", "push", "deploy"],
        }

    async def _git_state(self) -> dict[str, Any]:
        if self.git_manager is None:
            return {"available": False, "error": "Git manager is not connected."}
        try:
            status = await self.git_manager.status()
            branch = await self.git_manager.current_branch()
            head = await self.git_manager.head_commit()
            remote = await self.git_manager.remote_url() if hasattr(self.git_manager, "remote_url") else None
            return {
                "available": True,
                "branch": self._result_value(branch),
                "head_commit": self._result_value(head),
                "status": self._serialize(status),
                "remote_url": remote,
            }
        except Exception as exc:
            logger.warning("[RepositoryIntelligence] Git inspection failed: %s", exc)
            return {"available": False, "error": str(exc)}

    async def _github_state(
        self,
        git_state: dict[str, Any],
        warnings: list[str],
        errors: list[str],
    ) -> dict[str, Any]:
        remote_url = str(git_state.get("remote_url") or "").strip()
        repository = None
        if self.github_manager is not None:
            try:
                repository = await self.github_manager.repository()
            except Exception as exc:
                warnings.append(f"GitHub identity lookup failed: {exc}")

        if repository is None and remote_url:
            repository = GitHubManager.parse_repository_url(remote_url)

        if repository is None:
            return {
                "available": False,
                "reason": "No GitHub origin could be identified.",
            }

        owner = repository.owner
        name = repository.name
        api = await asyncio.to_thread(self._github_api, owner, name)
        if not api.get("success"):
            message = api.get("error", "GitHub API unavailable.")
            warnings.append(message)
            return {
                "available": True,
                "repository": repository.to_dict(),
                "api_available": False,
                "error": message,
            }

        metadata = api.get("metadata", {})
        default_branch = metadata.get("default_branch") or repository.default_branch or "main"
        tree = await asyncio.to_thread(self._github_tree, owner, name, default_branch)
        if not tree.get("success"):
            warnings.append(tree.get("error", "GitHub tree unavailable."))

        return {
            "available": True,
            "api_available": True,
            "repository": repository.to_dict(),
            "metadata": metadata,
            "default_branch": default_branch,
            "tree": tree.get("tree", []),
            "tree_truncated": bool(tree.get("truncated", False)),
            "private": bool(metadata.get("private", False)),
        }

    def _github_api(self, owner: str, name: str) -> dict[str, Any]:
        url = f"https://api.github.com/repos/{owner}/{name}"
        return self._github_get_json(url, kind="metadata")

    def _github_tree(self, owner: str, name: str, branch: str) -> dict[str, Any]:
        url = f"https://api.github.com/repos/{owner}/{name}/git/trees/{branch}?recursive=1"
        result = self._github_get_json(url, kind="tree")
        if not result.get("success"):
            return result
        payload = result.get("payload", {})
        return {
            "success": True,
            "tree": [
                {
                    "path": item.get("path"),
                    "mode": item.get("mode"),
                    "type": item.get("type"),
                    "sha": item.get("sha"),
                    "size": item.get("size"),
                }
                for item in payload.get("tree", [])
                if isinstance(item, dict)
            ],
            "truncated": bool(payload.get("truncated", False)),
        }

    def _github_get_json(self, url: str, *, kind: str) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ARIA-Repository-Intelligence",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            request = Request(url, headers=headers, method="GET")
            with urlopen(request, timeout=self.github_timeout) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            return {"success": True, "kind": kind, "payload": payload}
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            if exc.code in {401, 403}:
                return {"success": False, "error": f"GitHub authentication/rate-limit response ({exc.code}). {detail}"}
            return {"success": False, "error": f"GitHub API returned HTTP {exc.code}. {detail}"}
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return {"success": False, "error": f"GitHub API request failed: {exc}"}

    def _read_relevant_files(self, root: Path, paths: Iterable[str]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        total_chars = 0
        for relative in paths:
            try:
                metadata = self.repository_manager.get_file_metadata(root, relative)
                if metadata.is_protected or metadata.size_bytes > self.max_file_read_bytes:
                    continue
                content = (root / relative).read_text(encoding="utf-8", errors="replace")
                remaining = self.max_total_evidence_chars - total_chars
                if remaining <= 0:
                    break
                limit = min(self.max_evidence_chars_per_file, remaining)
                truncated = len(content) > limit
                content = content[:limit]
                total_chars += len(content)
                evidence.append({
                    "path": relative,
                    "language": metadata.language,
                    "sha256": metadata.sha256,
                    "size_bytes": metadata.size_bytes,
                    "truncated": truncated,
                    "content": content,
                })
            except Exception as exc:
                logger.debug("[RepositoryIntelligence] Could not read %s: %s", relative, exc)
        return evidence

    @staticmethod
    def _requirement_text(requirement: Any, fallback: str) -> str:
        if isinstance(requirement, str):
            return requirement
        if isinstance(requirement, dict):
            values = [requirement.get(key) for key in ("objective", "goal", "summary", "request")]
            text = " ".join(str(value) for value in values if value)
            return text or fallback
        for key in ("objective", "goal", "summary", "request"):
            value = getattr(requirement, key, None)
            if value:
                return str(value)
        return fallback

    @staticmethod
    def _keywords(request: str, requirement: Any | None) -> list[str]:
        text = request
        if requirement is not None:
            text += " " + RepositoryIntelligenceService._requirement_text(requirement, "")
        tokens = re.findall(r"[A-Za-z0-9_./-]{3,}", text.lower())
        return list(dict.fromkeys(tokens))[:100]

    @staticmethod
    def _result_value(value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                pass
        return value

    @staticmethod
    def _serialize(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return dict(value.__dict__)
            except Exception:
                pass
        return str(value)
