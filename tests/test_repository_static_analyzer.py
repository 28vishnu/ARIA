from __future__ import annotations

import asyncio
import json
from pathlib import Path

from brain.development.repository_intelligence import RepositoryIntelligence
from brain.development.repository_static_analyzer import RepositoryStaticAnalyzer


def _make_repo(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "utils.py").write_text(
        "def calculate_total(values):\n    return sum(values)\n",
        encoding="utf-8",
    )
    (root / "pkg" / "service.py").write_text(
        "from .utils import calculate_total\n\n"
        "class BillingService:\n"
        "    def invoice_total(self, values):\n"
        "        return calculate_total(values)\n",
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^19.0.0"}, "devDependencies": {"vite": "^6"}}),
        encoding="utf-8",
    )


def test_static_analyzer_indexes_python_symbols_imports_and_dependencies(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    result = RepositoryStaticAnalyzer(tmp_path).analyze("calculate total billing")

    assert result["success"] is True
    assert result["read_only"] is True
    assert result["code_execution_performed"] is False
    assert "pkg/service.py" in result["relevant_files"]
    assert "pkg/utils.py" in result["relevant_files"]
    assert any(item["name"] == "BillingService" for item in result["symbols"])
    assert any(item["name"] == "calculate_total" for item in result["symbols"])
    assert any(item["target_module"] == "pkg.utils" for item in result["local_import_edges"])
    assert {item["name"] for item in result["dependency_summary"]["declared"]} == {"react", "vite"}


def test_static_analyzer_skips_ignored_dirs_and_reports_syntax_errors(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "untrusted").mkdir(parents=True)
    (tmp_path / "node_modules" / "untrusted" / "ignored.py").write_text("def hidden(): pass\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def unfinished(:\n    pass\n", encoding="utf-8")

    result = RepositoryStaticAnalyzer(tmp_path).analyze()

    assert result["success"] is True
    assert result["files_scanned"] == 1
    assert result["parse_errors"]
    assert all("node_modules" not in item.get("path", "") for item in result["parse_errors"])


def test_static_analyzer_missing_root_returns_structured_failure(tmp_path: Path) -> None:
    result = RepositoryStaticAnalyzer(tmp_path / "missing").analyze()

    assert result["success"] is False
    assert result["read_only"] is True
    assert result["files_scanned"] == 0
    assert result["errors"]


def test_repository_intelligence_includes_static_analysis(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    service = RepositoryIntelligence(repository_root=str(tmp_path))
    result = asyncio.run(service.inspect("calculate_total", include_git=False, include_github=False))

    assert result["success"] is True
    assert result["static_analysis"]["success"] is True
    assert result["services"]["static_analyzer"] is True
    assert "pkg/utils.py" in result["relevant_files"]
    assert service.capabilities()["symbol_index"] is True


def test_static_analyzer_does_not_modify_repository(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    RepositoryStaticAnalyzer(tmp_path).analyze("billing service")

    after = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
