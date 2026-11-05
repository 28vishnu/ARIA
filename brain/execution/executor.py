"""
Compatibility module for ARIA's execution engine.

The canonical Phase-3 Executor lives in:

    brain.executor.Executor

This module exists temporarily so legacy imports such as:

    from brain.execution.executor import Executor

continue to work without maintaining two independent executors.
"""

from brain.executor import Executor

__all__ = ["Executor"]