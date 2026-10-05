from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    EngineeringEvidence,
    EngineeringSession,
    EngineeringStore,
)

logger = logging.getLogger("aria.authoritative_engineering_persistence")


class EngineeringPersistenceError(RuntimeError):
    """Raised when authoritative engineering state cannot be persisted."""


class EngineeringPersistence:
    """
    Authoritative persistence boundary for autonomous