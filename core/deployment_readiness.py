"""Read-only deployment configuration audit for ARIA.

This module reports configuration presence only. It never prints secret values,
contacts external services, changes the database, or deploys the application.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # PASS, WARN, FAIL
    detail: str


def _present(env: Mapping[str, str], key: str) -> bool:
    return bool(str(env.get(key, "")).strip())


def audit_environment(env: Optional[Mapping[str, str]] = None) -> list[Check]:
    """Audit key deployment settings without exposing their values."""
    values = os.environ if env is None else env
    checks: list[Check] = []

    if _present(values, "TELEGRAM_BOT_TOKEN"):
        checks.append(Check("Telegram bot token", "PASS", "TELEGRAM_BOT_TOKEN is set; value hidden."))
    else:
        checks.append(Check("Telegram bot token", "FAIL", "Set TELEGRAM_BOT_TOKEN in the deployment environment."))

    if _present(values, "ALLOWED_TELEGRAM_USER_ID"):
        checks.append(Check("Owner allowlist", "PASS", "ALLOWED_TELEGRAM_USER_ID is set; value hidden."))
    else:
        checks.append(Check("Owner allowlist", "FAIL", "Set ALLOWED_TELEGRAM_USER_ID to the authorized Telegram user ID."))

    if _present(values, "PORT"):
        try:
            port = int(str(values["PORT"]).strip())
            if 1 <= port <= 65535:
                checks.append(Check("HTTP port", "PASS", "PORT is a valid TCP port."))
            else:
                checks.append(Check("HTTP port", "FAIL", "PORT must be between 1 and 65535."))
        except (TypeError, ValueError):
            checks.append(Check("HTTP port", "FAIL", "PORT must be an integer."))
    else:
        checks.append(Check("HTTP port", "WARN", "PORT is unset; the application may use its default port."))

    db_path = str(values.get("ARIA_OPEN_KNOWLEDGE_DB", "data/aria_open_knowledge.sqlite3")).strip()
    if db_path:
        checks.append(Check("Knowledge database path", "PASS", "A database path is configured or the application default will be used."))
    else:
        checks.append(Check("Knowledge database path", "FAIL", "ARIA_OPEN_KNOWLEDGE_DB is empty."))

    if _present(values, "GEMINI_API_KEY"):
        checks.append(Check("Gemini provider", "PASS", "GEMINI_API_KEY is set; value hidden."))
    else:
        checks.append(Check("Gemini provider", "WARN", "GEMINI_API_KEY is unset; Gemini-dependent features may be unavailable."))

    if _present(values, "RENDER_EXTERNAL_URL"):
        checks.append(Check("Public service URL", "PASS", "RENDER_EXTERNAL_URL is set; value hidden."))
    else:
        checks.append(Check("Public service URL", "WARN", "RENDER_EXTERNAL_URL is unset; verify the public HTTPS URL and webhook manually."))

    return checks


def render_report(checks: Sequence[Check]) -> str:
    lines = ["ARIA deployment readiness audit (configuration only)", "=" * 48]
    for check in checks:
        lines.append(f"[{check.status}] {check.name}: {check.detail}")
    failures = sum(item.status == "FAIL" for item in checks)
    warnings = sum(item.status == "WARN" for item in checks)
    lines.append(f"\nSummary: {len(checks) - failures - warnings} passed, {warnings} warnings, {failures} failures.")
    lines.append("This audit does not test network reachability, Telegram webhook status, database existence, or live deployment health.")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Return non-zero when any FAIL or WARN is reported.")
    args = parser.parse_args(argv)
    checks = audit_environment()
    print(render_report(checks))
    if any(c.status == "FAIL" for c in checks):
        return 1
    if args.strict and any(c.status == "WARN" for c in checks):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
