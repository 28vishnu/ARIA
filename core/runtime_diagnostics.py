"""Low-cost, dependency-free diagnostics for the current ARIA process.

These checks describe the local process only. They do not imply that Telegram,
web search, or other third-party services are reachable.
"""
from __future__ import annotations

import os
import platform
import sys
import time
from typing import Any

_PROCESS_STARTED = time.monotonic()


def _rss_bytes_from_proc_status() -> int | None:
    """Return Linux resident memory in bytes when /proc is available."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    # Linux reports VmRSS in kB.
                    return int(parts[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def runtime_diagnostics() -> dict[str, Any]:
    """Return measured process/runtime facts without making readiness claims."""
    rss_bytes = _rss_bytes_from_proc_status()
    uptime = max(0.0, time.monotonic() - _PROCESS_STARTED)
    return {
        "process": {
            "pid": os.getpid(),
            "uptime_seconds": round(uptime, 2),
            "uptime_source": "monotonic_clock_since_module_import",
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_basename": os.path.basename(sys.executable),
        },
        "memory": {
            "rss_bytes": rss_bytes,
            "rss_mb": round(rss_bytes / (1024 * 1024), 2) if rss_bytes is not None else None,
            "source": "/proc/self/status VmRSS" if rss_bytes is not None else "unavailable",
        },
        "limitations": [
            "Process diagnostics do not verify third-party API availability.",
            "Uptime starts when this diagnostics module is imported, not necessarily at OS process creation.",
        ],
    }
