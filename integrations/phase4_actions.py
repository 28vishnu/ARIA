"""Owner-authenticated integration status and explicit test-alert endpoint."""
from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from integrations.alert_manager import AlertManager
from integrations.alert_runtime import telegram_notifier
from integrations.jarvis_status import build_status

router = APIRouter(tags=["ARIA account monitoring and alerts"])


class TestAlertRequest(BaseModel):
    confirm_send: bool


@router.get("/integrations/status")
def integration_status() -> dict[str, Any]:
    """Safe status overview; provider tokens and message contents are never returned."""
    result = build_status()
    result["integrations"]["github_account"] = {
        "configured": bool(os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_PAT")),
        "note": "Configuration only; use /github/account/status to verify live authentication.",
    }
    return result


@router.post("/alerts/test")
async def send_test_alert(request: TestAlertRequest) -> dict[str, Any]:
    """Send one explicitly requested Telegram test message through the persistent queue."""
    if not request.confirm_send:
        raise HTTPException(status_code=400, detail="Set confirm_send=true to send a real test notification.")
    manager = AlertManager(notifier=telegram_notifier)
    alert, created, delivered = await manager.enqueue_and_dispatch(
        source="ARIA system",
        title="Phase 4 notification test",
        body="ARIA's authenticated notification test was requested. If you received this, Telegram delivery is working.",
        severity="urgent",
        dedupe_key=f"phase4-test:{uuid.uuid4()}",
    )
    return {
        "queued": True,
        "created": created,
        "delivered": bool(delivered),
        "alert_id": alert.alert_id,
        "status": alert.status,
        "message": "Notification delivered." if delivered else "Notification remains queued; verify Telegram configuration and server logs.",
    }


__all__ = ["router", "integration_status", "send_test_alert"]
