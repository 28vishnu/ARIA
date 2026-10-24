"""Phase 7 integration runtime for engineering review and proactive tasks.

The runtime is deliberately conservative: engineering changes are staged in a
separate workspace, scheduled task types are allow-listed, and Telegram delivery
is only reported successful after Telegram confirms the send.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from autonomy.proactive_agent import MongoProactiveTaskStore, ProactiveAgent, ProactiveTaskStore
from brain.development.phase4_engineering_gate import EngineeringChangeGate

logger = logging.getLogger("aria.phase7")


class Phase7Runtime:
    def __init__(self, *, store: ProactiveTaskStore, agent: ProactiveAgent,
                 agent_task: asyncio.Task, engineering_gate: EngineeringChangeGate):
        self.store = store
        self.agent = agent
        self.agent_task = agent_task
        self.engineering_gate = engineering_gate

    async def shutdown(self) -> None:
        self.agent.stop()
        self.agent_task.cancel()
        try:
            await self.agent_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Proactive agent failed during shutdown")


def _registry_has(registry: Any, name: str) -> bool:
    try:
        return bool(registry.has(name))
    except Exception:
        return False


async def initialize_phase7_runtime(registry: Any, app: Any) -> Phase7Runtime:
    """Register Phase 4 gate and start Phase 5 polling with safe callbacks."""
    repo_root = Path(__file__).resolve().parent.parent
    workspace_base = Path(os.getenv("ARIA_ENGINEERING_WORKSPACE_DIR", "/tmp/aria-engineering-workspaces"))
    gate = EngineeringChangeGate(
        repo_root,
        workspace_base=workspace_base,
        max_files=int(os.getenv("ARIA_ENGINEERING_MAX_FILES", "100")),
        max_file_bytes=int(os.getenv("ARIA_ENGINEERING_MAX_FILE_BYTES", "1000000")),
        max_total_bytes=int(os.getenv("ARIA_ENGINEERING_MAX_TOTAL_BYTES", "5000000")),
    )
    registry.register("engineering_change_gate", gate)
    app.state.engineering_change_gate = gate

    # Prefer MongoDB for durable task state on hosts without persistent disks.
    # Set ARIA_PROACTIVE_STORAGE=sqlite to force local SQLite intentionally.
    storage_mode = os.getenv("ARIA_PROACTIVE_STORAGE", "mongodb" if os.getenv("MONGODB_URI") else "sqlite").strip().lower()
    if storage_mode == "mongodb":
        mongo_uri = os.getenv("MONGODB_URI", "").strip()
        if not mongo_uri:
            raise RuntimeError("ARIA_PROACTIVE_STORAGE=mongodb requires MONGODB_URI")
        mongo_db = os.getenv("ARIA_PROACTIVE_MONGO_DATABASE", "aria_db").strip() or "aria_db"
        mongo_collection = os.getenv("ARIA_PROACTIVE_MONGO_COLLECTION", "proactive_tasks").strip() or "proactive_tasks"
        store = MongoProactiveTaskStore(mongo_uri, mongo_db, mongo_collection)
        logger.info("Proactive task storage connected: MongoDB database=%s collection=%s", mongo_db, mongo_collection)
    elif storage_mode == "sqlite":
        persistent_dir = os.getenv("RENDER_PERSISTENT_DIR")
        default_db = str(Path(persistent_dir) / "aria_proactive.sqlite3") if persistent_dir else "data/aria_proactive.sqlite3"
        db_path = os.getenv("ARIA_PROACTIVE_DB_PATH", default_db)
        store = ProactiveTaskStore(db_path)
        if not persistent_dir and db_path != ":memory:":
            logger.warning(
                "Proactive task database is on the instance filesystem; tasks may be lost on Render restart. "
                "Use ARIA_PROACTIVE_STORAGE=mongodb and configure MONGODB_URI, or attach a persistent disk."
            )
    else:
        raise RuntimeError("ARIA_PROACTIVE_STORAGE must be 'mongodb' or 'sqlite'")

    config = registry.get("config") if _registry_has(registry, "config") else None
    http_client = registry.get("http_client") if _registry_has(registry, "http_client") else None
    token = str(getattr(config, "telegram_token", "") or os.getenv("TELEGRAM_TOKEN", "")).strip()
    chat_id = str(os.getenv("ARIA_PROACTIVE_CHAT_ID", os.getenv("ALLOWED_TELEGRAM_USER_ID", ""))).strip()

    async def notifier(message: str, task: dict[str, Any]) -> None:
        if not token or not chat_id or http_client is None:
            raise RuntimeError("Proactive Telegram delivery is not configured; set TELEGRAM_TOKEN and ARIA_PROACTIVE_CHAT_ID and ensure the HTTP client is available.")
        response = await http_client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": str(message)[:4000]},
            timeout=15.0,
        )
        response.raise_for_status()
        try:
            body = response.json()
        except Exception as exc:
            raise RuntimeError("Telegram returned a non-JSON response") from exc
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise RuntimeError("Telegram did not confirm message delivery")

    async def task_handler(task: dict[str, Any]) -> str:
        payload = task.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("Task payload must be an object")
        kind = str(payload.get("kind", "notification")).strip().lower()
        if kind != "notification":
            raise ValueError(f"Unsupported proactive task kind: {kind}")
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Notification task requires a non-empty payload.message")
        if not token or not chat_id or http_client is None:
            raise RuntimeError("Notification task cannot run because Telegram delivery is not configured")
        return message.strip()[:4000]

    agent = ProactiveAgent(
        store,
        task_handler,
        notifier=notifier,
        poll_interval_seconds=float(os.getenv("ARIA_PROACTIVE_POLL_SECONDS", "15")),
    )
    agent_task = asyncio.create_task(agent.run(), name="aria-proactive-agent")
    runtime = Phase7Runtime(store=store, agent=agent, agent_task=agent_task, engineering_gate=gate)
    app.state.phase7_runtime = runtime
    app.state.proactive_task_store = store
    app.state.proactive_agent = agent
    logger.info("Phase 7 integrations initialized: engineering gate registered; proactive agent running")
    return runtime
