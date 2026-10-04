"""ARIA Phase 1 — Intelligent coding-context selection.

Selects the smallest useful repository context for a code-generation request.
This component is deterministic and read-only: it never writes files or
executes repository code.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class CodingContextSelector:
    """Rank repository files using requirement, plan and impact metadata."""

    DEFAULT_MAX_FILES = 12
    DEFAULT_MAX_CHARS = 50_000
    DEFAULT_MAX_FILE_CHARS = 12_000

    SOURCE_EXTENSIONS = {
        ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".java", ".go",
        ".rs", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".php", ".rb",
        ".swift", ".kt", ".kts", ".json", ".yaml", ".yml", ".toml", ".ini",
    }

    TEST_HINTS = ("test", "tests", "spec", "__tests__")

    def __init__(self, *, max_files: int = DEFAULT_MAX_FILES, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        self.max_files = max(1, int(max_files))
        self.max_chars = max(4_000, int(max_chars))

    @staticmethod
    def _tokens(value: Any) -> set[str]:
        text = str(value or "").lower()
        return {token for token in re.findall(r"[a-zA-Z0-9_]{3,}", text) if token not in {"the", "and", "for", "with", "from", "that", "this"}}

    @staticmethod
    def _path(value: Any) -> str:
        return str(value or "").replace("\\", "/").lstrip("./")

    def _target_paths(self, requirement: dict[str, Any], plan: dict[str, Any], impact: dict[str, Any]) -> set[str]:
        paths: set[str] = set()
        for key in ("requested_files", "target_files", "affected_files", "files"):
            values = requirement.get(key, []) if isinstance(requirement, dict) else []
            if isinstance(values, (list, tuple, set)):
                paths.update(self._path(item) for item in values if item)
        for item in plan.get("changes", []) if isinstance(plan, dict) else []:
            if isinstance(item, dict) and item.get("path"):
                paths.add(self._path(item["path"]))
        for key in ("affected_modules", "direct_modules", "related_modules", "affected_files"):
            values = impact.get(key, []) if isinstance(impact, dict) else []
            if isinstance(values, (list, tuple, set)):
                paths.update(self._path(item) for item in values if item)
        return {p for p in paths if p}

    def _score(self, path: str, content: str, query_tokens: set[str], targets: set[str], plan: dict[str, Any], impact: dict[str, Any]) -> float:
        normalized = path.lower()
        stem_tokens = self._tokens(Path(path).stem)
        path_tokens = self._tokens(path)
        score = 0.0
        if path in targets:
            score += 1000.0
        for target in targets:
            target_norm = target.lower()
            if normalized == target_norm:
                score += 500.0
            elif normalized.endswith("/" + target_norm) or target_norm.endswith("/" + normalized):
                score += 250.0
        score += 12.0 * len(path_tokens & query_tokens)
        score += 8.0 * len(stem_tokens & query_tokens)
        content_tokens = self._tokens(content[:20_000])
        score += min(30.0, 2.0 * len(content_tokens & query_tokens))
        if any(hint in normalized.split("/")[-1] for hint in self.TEST_HINTS):
            score += 4.0
        for item in plan.get("tests", []) if isinstance(plan, dict) else []:
            if self._tokens(item) & path_tokens:
                score += 25.0
        return score

    def select(self, context: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(context, dict):
            return {"files": [], "selected_count": 0, "context_chars": 0}

        requirement = context.get("requirement") or {}
        plan = context.get("plan") or {}
        impact = context.get("impact_analysis") or context.get("impact") or {}
        repository = context.get("repository") or {}
        files = repository.get("files", []) if isinstance(repository, dict) else []
        if not isinstance(files, list):
            files = []

        query_text = " ".join([
            str(requirement.get("raw_text", "")) if isinstance(requirement, dict) else "",
            str(requirement.get("objective", "")) if isinstance(requirement, dict) else "",
            str(requirement.get("intent", "")) if isinstance(requirement, dict) else "",
            str(plan.get("summary", "")) if isinstance(plan, dict) else "",
        ])
        query_tokens = self._tokens(query_text)
        targets = self._target_paths(requirement, plan, impact)

        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in files:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            path = self._path(item["path"])
            suffix = Path(path).suffix.lower()
            if suffix not in self.SOURCE_EXTENSIONS:
                continue
            content = str(item.get("content") or "")
            ranked.append((self._score(path, content, query_tokens, targets, plan, impact), item))

        ranked.sort(key=lambda pair: (-pair[0], self._path(pair[1].get("path"))))

        selected: list[dict[str, Any]] = []
        total = 0
        for score, item in ranked:
            if len(selected) >= self.max_files or total >= self.max_chars:
                break
            path = self._path(item.get("path"))
            content = str(item.get("content") or "")
            remaining = self.max_chars - total
            if remaining <= 0:
                break
            limit = min(self.DEFAULT_MAX_FILE_CHARS, remaining)
            clipped = content[:limit]
            selected.append({
                "path": path,
                "content": clipped,
                "truncated": len(clipped) < len(content) or bool(item.get("truncated")),
                "relevance_score": round(score, 2),
            })
            total += len(clipped)

        return {
            "repository_root": ".",
            "selected_count": len(selected),
            "available_files": len(files),
            "context_chars": total,
            "selection": "targeted_ranked",
            "files": selected,
        }


__all__ = ["CodingContextSelector"]
