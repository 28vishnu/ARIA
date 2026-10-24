from __future__ import annotations

"""Deterministic, read-only source map for ARIA's repository engineering agent.

This analyzer does not execute repository code, install dependencies, contact
network services, or modify files. Python symbols/imports are extracted using
``ast``; common JavaScript/TypeScript declarations/imports are indexed with
bounded regular expressions. Results are evidence, not proof that code is safe
or correct.
"""

import ast
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


DEFAULT_IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "dist", "build", ".next", ".cache", "coverage", "site-packages",
}
SOURCE_EXTENSIONS = {".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
CONFIG_FILES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py",
    "setup.cfg", "package.json", "cargo.toml", "go.mod", "pom.xml",
    "build.gradle", "build.gradle.kts", "gemfile", "composer.json",
}
MAX_SYMBOLS_PER_FILE = 500


class RepositoryStaticAnalyzer:
    """Build a bounded symbol/import/dependency map from a local repository."""

    VERSION = "ARIA-STATIC-ANALYZER-1.0"

    def __init__(
        self,
        repository_root: str | os.PathLike[str],
        *,
        max_files: int = 4000,
        max_file_size_bytes: int = 512 * 1024,
        ignored_directories: Optional[Iterable[str]] = None,
    ) -> None:
        self.root = Path(repository_root).expanduser().resolve()
        self.max_files = max(1, min(int(max_files), 20000))
        self.max_file_size_bytes = max(1024, min(int(max_file_size_bytes), 4 * 1024 * 1024))
        self.ignored_directories = set(ignored_directories or DEFAULT_IGNORED_DIRS)

    def analyze(self, query: str = "", *, max_files: Optional[int] = None) -> Dict[str, Any]:
        """Return deterministic source evidence; never mutates or executes files."""
        if not self.root.exists() or not self.root.is_dir():
            return {
                "success": False,
                "version": self.VERSION,
                "repository_root": str(self.root),
                "read_only": True,
                "files_scanned": 0,
                "errors": ["Repository root does not exist or is not a directory."],
            }

        limit = max(1, min(int(max_files or self.max_files), self.max_files))
        files, scan_warnings = self._discover_files(limit)
        symbols: List[Dict[str, Any]] = []
        imports: List[Dict[str, Any]] = []
        parse_errors: List[Dict[str, Any]] = []
        languages: Counter[str] = Counter()
        entry_points: List[str] = []
        manifests: List[str] = []
        all_paths = {p.relative_to(self.root).as_posix() for p in files}

        for path in files:
            rel = path.relative_to(self.root).as_posix()
            suffix = path.suffix.lower()
            languages[self._language(suffix)] += 1
            if path.name.lower() in {"main.py", "app.py", "run.py", "server.py", "index.js", "server.js", "main.ts", "app.ts"}:
                entry_points.append(rel)
            if path.name.lower() in CONFIG_FILES:
                manifests.append(rel)
            try:
                if path.stat().st_size > self.max_file_size_bytes:
                    scan_warnings.append(f"Skipped oversized source file: {rel}")
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                scan_warnings.append(f"Could not read {rel}: {type(exc).__name__}")
                continue

            if suffix in {".py", ".pyw"}:
                file_symbols, file_imports, error = self._parse_python(rel, content)
                symbols.extend(file_symbols)
                imports.extend(file_imports)
                if error:
                    parse_errors.append({"path": rel, "error": error})
            elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
                file_symbols, file_imports = self._parse_js_ts(rel, content)
                symbols.extend(file_symbols)
                imports.extend(file_imports)

        # Resolve local Python imports only against files actually present.
        local_edges = self._resolve_local_imports(imports, all_paths)
        query_terms = self._tokens(query)
        relevant_symbols = self._rank_symbols(query_terms, symbols, limit=80)
        relevant_files = self._rank_files(query_terms, files, symbols, imports, root=self.root, limit=120)
        function_names = {s["qualified_name"] for s in symbols if s["kind"] in {"function", "async_function", "method"}}
        call_edges = [edge for edge in self._call_edges(symbols) if edge["target"] in function_names]

        dependency_summary = self._dependency_summary(manifests)
        return {
            "success": True,
            "version": self.VERSION,
            "repository_root": str(self.root),
            "read_only": True,
            "code_execution_performed": False,
            "files_scanned": len(files),
            "file_limit": limit,
            "language_file_counts": dict(sorted(languages.items())),
            "entry_points": sorted(set(entry_points))[:100],
            "dependency_manifests": sorted(set(manifests))[:100],
            "dependency_summary": dependency_summary,
            "symbols": symbols[:12000],
            "imports": imports[:16000],
            "local_import_edges": local_edges[:16000],
            "call_edges": call_edges[:12000],
            "relevant_symbols": relevant_symbols,
            "relevant_files": relevant_files,
            "parse_errors": parse_errors[:300],
            "warnings": list(dict.fromkeys(scan_warnings))[:300],
            "errors": [],
        }

    def _discover_files(self, limit: int) -> Tuple[List[Path], List[str]]:
        found: List[Path] = []
        warnings: List[str] = []
        try:
            for current, dirs, filenames in os.walk(self.root, followlinks=False):
                dirs[:] = sorted(
                    d for d in dirs
                    if d not in self.ignored_directories
                    and not (Path(current) / d).is_symlink()
                )
                for filename in sorted(filenames):
                    path = Path(current) / filename
                    if path.is_symlink() or (
                        path.suffix.lower() not in SOURCE_EXTENSIONS
                        and path.name.lower() not in CONFIG_FILES
                    ):
                        continue
                    try:
                        path.resolve().relative_to(self.root)
                    except (ValueError, OSError):
                        continue
                    found.append(path)
                    if len(found) >= limit:
                        warnings.append(f"File scan reached configured limit ({limit}).")
                        return sorted(found), warnings
        except OSError as exc:
            warnings.append(f"Directory traversal stopped: {type(exc).__name__}")
        return sorted(found), warnings

    @staticmethod
    def _language(suffix: str) -> str:
        return {
            ".py": "python", ".pyw": "python", ".js": "javascript",
            ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
            ".ts": "typescript", ".tsx": "typescript",
        }.get(suffix, "unknown")

    @staticmethod
    def _parse_python(rel: str, content: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        symbols: List[Dict[str, Any]] = []
        imports: List[Dict[str, Any]] = []
        try:
            tree = ast.parse(content, filename=rel)
        except (SyntaxError, ValueError) as exc:
            return symbols, imports, f"{type(exc).__name__} at line {getattr(exc, 'lineno', None)}"

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.scope: List[str] = []
                self.call_names: Set[str] = set()

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                qualified = ".".join([rel[:-3].replace("/", ".")] + self.scope + [node.name])
                symbols.append({"path": rel, "name": node.name, "qualified_name": qualified, "kind": "class", "line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno), "calls": []})
                self.scope.append(node.name)
                for child in node.body:
                    self.visit(child)
                self.scope.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._visit_function(node, "function")

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._visit_function(node, "async_function")

            def _visit_function(self, node: Any, kind: str) -> None:
                qparts = [rel[:-3].replace("/", ".")] + self.scope + [node.name]
                qualified = ".".join(qparts)
                is_method = bool(self.scope)
                calls = sorted({
                    n.func.id if isinstance(n.func, ast.Name) else n.func.attr
                    for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
                })
                symbols.append({"path": rel, "name": node.name, "qualified_name": qualified, "kind": "method" if is_method else kind, "line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno), "calls": calls[:100]})
                self.scope.append(node.name)
                for child in node.body:
                    self.visit(child)
                self.scope.pop()

            def visit_Import(self, node: ast.Import) -> None:
                for alias in node.names:
                    imports.append({"path": rel, "module": alias.name, "name": alias.asname or alias.name, "kind": "import", "line": node.lineno})

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                module = ("." * node.level) + (node.module or "")
                for alias in node.names:
                    imports.append({"path": rel, "module": module, "name": alias.name, "alias": alias.asname, "kind": "from_import", "line": node.lineno})

        visitor = Visitor()
        visitor.visit(tree)
        return symbols[:MAX_SYMBOLS_PER_FILE], imports[:MAX_SYMBOLS_PER_FILE], None

    @staticmethod
    def _parse_js_ts(rel: str, content: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        symbols: List[Dict[str, Any]] = []
        imports: List[Dict[str, Any]] = []
        patterns = (
            ("class", re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")),
            ("function", re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")),
            ("function", re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
            ("function", re.compile(r"\bexport\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")),
        )
        for kind, pattern in patterns:
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                name = match.group(1)
                symbols.append({"path": rel, "name": name, "qualified_name": f"{rel}::{name}", "kind": kind, "line": line, "end_line": line, "calls": []})
                if len(symbols) >= MAX_SYMBOLS_PER_FILE:
                    break
        import_patterns = (
            re.compile(r"\bimport\s+(?:[^;\n]*?\s+from\s+)?['\"]([^'\"]+)['\"]"),
            re.compile(r"\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)"),
            re.compile(r"\bimport\(\s*['\"]([^'\"]+)['\"]\s*\)"),
        )
        for pattern in import_patterns:
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                imports.append({"path": rel, "module": match.group(1), "name": match.group(1), "kind": "js_import", "line": line})
                if len(imports) >= MAX_SYMBOLS_PER_FILE:
                    break
        # Deduplicate identical regex matches while preserving deterministic order.
        symbol_seen = set()
        symbols = [item for item in symbols if not ((item["path"], item["name"], item["line"], item["kind"]) in symbol_seen or symbol_seen.add((item["path"], item["name"], item["line"], item["kind"]))) ]
        import_seen = set()
        imports = [item for item in imports if not ((item["path"], item["module"], item["line"]) in import_seen or import_seen.add((item["path"], item["module"], item["line"]))) ]
        return symbols[:MAX_SYMBOLS_PER_FILE], imports[:MAX_SYMBOLS_PER_FILE]

    @staticmethod
    def _resolve_local_imports(imports: Sequence[Dict[str, Any]], paths: Set[str]) -> List[Dict[str, Any]]:
        modules = {p[:-3].replace("/", ".") for p in paths if p.endswith(".py")}
        modules.update(p[:-3].replace("/", ".") for p in paths if p.endswith(".pyw"))
        edges = []
        for item in imports:
            module = str(item.get("module", ""))
            if module.startswith("."):
                parent = str(item.get("path", "")).rsplit("/", 1)[0]
                base = parent.replace("/", ".")
                dots = len(module) - len(module.lstrip("."))
                remainder = module[dots:]
                parts = base.split(".") if base else []
                if dots > 1:
                    parts = parts[: max(0, len(parts) - dots + 1)]
                module = ".".join(parts + ([remainder] if remainder else []))
            target = module.strip(".")
            if target in modules:
                edges.append({"source": item.get("path"), "target_module": target, "line": item.get("line"), "kind": "python_local_import"})
            elif target and any(m.startswith(target + ".") for m in modules):
                edges.append({"source": item.get("path"), "target_module": target, "line": item.get("line"), "kind": "python_local_import_prefix"})
        return edges

    @staticmethod
    def _call_edges(symbols: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_name: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for symbol in symbols:
            by_name[symbol.get("name", "")].append(symbol)
        edges = []
        for symbol in symbols:
            for call in symbol.get("calls", []):
                candidates = by_name.get(call, [])
                if len(candidates) == 1:
                    edges.append({"source": symbol["qualified_name"], "target": candidates[0]["qualified_name"], "path": symbol["path"], "line": symbol["line"], "confidence": "name_match_only"})
        return edges

    @staticmethod
    def _tokens(query: str) -> List[str]:
        stop = {"the", "and", "for", "with", "from", "that", "this", "what", "where", "which", "please", "make", "help", "show", "tell", "about", "into"}
        return [t for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", query.lower()) if t not in stop][:50]

    @staticmethod
    def _rank_symbols(terms: Sequence[str], symbols: Sequence[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
        ranked = []
        for symbol in symbols:
            haystack = f"{symbol.get('name', '')} {symbol.get('qualified_name', '')} {symbol.get('path', '')}".lower()
            score = sum(4 if term == symbol.get("name", "").lower() else 2 if term in symbol.get("name", "").lower() else 1 if term in haystack else 0 for term in terms)
            if score:
                ranked.append((score, symbol))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["path"], pair[1]["line"], pair[1]["name"]))
        return [{**symbol, "relevance_score": score} for score, symbol in ranked[:limit]]

    @staticmethod
    def _rank_files(terms: Sequence[str], files: Sequence[Path], symbols: Sequence[Dict[str, Any]], imports: Sequence[Dict[str, Any]], *, root: Path, limit: int) -> List[str]:
        scores: Dict[str, int] = defaultdict(int)
        for path in files:
            rel = path.relative_to(root).as_posix()
            low = rel.lower()
            scores[rel] += sum(3 if term in Path(rel).name.lower() else 1 if term in low else 0 for term in terms)
        for symbol in symbols:
            rel = symbol["path"]
            name = symbol["name"].lower()
            scores[rel] += sum(4 if term == name else 2 if term in name else 0 for term in terms)
        for item in imports:
            rel = item["path"]
            module = str(item.get("module", "")).lower()
            scores[rel] += sum(1 for term in terms if term in module)
        ranked = sorted(((score, path) for path, score in scores.items() if score > 0), key=lambda pair: (-pair[0], pair[1]))
        return [path for _, path in ranked[:limit]]

    def _dependency_summary(self, manifests: Sequence[str]) -> Dict[str, Any]:
        result: Dict[str, Any] = {"declared": [], "manifest_errors": []}
        for rel in manifests:
            path = self.root / rel
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if path.name.lower() == "package.json":
                try:
                    data = json.loads(text)
                    for group in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                        values = data.get(group, {}) if isinstance(data, dict) else {}
                        if isinstance(values, dict):
                            result["declared"].extend({"name": name, "version": str(version), "group": group, "manifest": rel} for name, version in values.items())
                except (json.JSONDecodeError, AttributeError) as exc:
                    result["manifest_errors"].append({"path": rel, "error": type(exc).__name__})
            elif path.name.lower().startswith("requirements"):
                for line in text.splitlines():
                    cleaned = line.strip()
                    if cleaned and not cleaned.startswith(("#", "-", "http://", "https://")):
                        name = re.split(r"[<>=!~\[]", cleaned, maxsplit=1)[0].strip()
                        if name:
                            result["declared"].append({"name": name, "version": cleaned[len(name):].strip() or "unspecified", "group": "requirements", "manifest": rel})
        result["declared"] = sorted(result["declared"], key=lambda item: (item["name"].lower(), item["manifest"]))[:2000]
        return result


__all__ = ["RepositoryStaticAnalyzer"]
