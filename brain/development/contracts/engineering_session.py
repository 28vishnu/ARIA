"""Compatibility exports for ARIA's authoritative engineering session.

The authoritative implementation lives in ``brain.development.engineering_session``.
This module intentionally contains no second session implementation.
"""

from __future__ import annotations

from ..engineering_session import (
    EngineeringSession,
    SessionTransition,
    AuthoritativeEngineeringSession,
)

__all__ = [
    "EngineeringSession",
    "SessionTransition",
    "AuthoritativeEngineeringSession",
]
