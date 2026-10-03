"""
ARIA Self-Development System.

This package contains the isolated development infrastructure used by
ARIA to inspect, understand, modify, validate, test, and eventually
deploy its own source code.

Phase 1 begins with repository intelligence.

Important architectural rule:
    The development subsystem must remain isolated from ARIA's main
    cognitive pipeline wherever possible.

This allows ARIA to evolve without repeatedly modifying the core brain.
"""

from .repository_manager import RepositoryManager
from .source_analyzer import SourceAnalyzer
from .dependency_analyzer import DependencyAnalyzer

__all__ = [
    "RepositoryManager",
    "SourceAnalyzer",
    "DependencyAnalyzer",
]