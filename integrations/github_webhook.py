"""Authenticated, read-only GitHub webhook ingestion for ARIA alerts."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from integrations.alert_manager import AlertManager
from integrations.alert_runtime import telegram_notifier

logger = logging.getLogger("aria")
router = APIRouter()


def _manager() -> AlertManager:
    return AlertManager(notifier=telegram_notifier)


def _verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _summarize_event(event: str, payload: dict[str, Any]) -> tuple[str, str, str] | None:
    repo = payload.get("repository") or {}
    repo_name = str(repo.get("full_name") or "unknown repository")[:200]
    if event == "workflow_run":
        run = payload.get("workflow_run") or {}
        conclusion = str(run.get("conclusion") or run.get("status") or "updated")
        workflow = str(run.get("name") or "GitHub Actions workflow")[:200]
        url = str(run.get("html_url") or "")[:500]
        urgent = conclusion in {"failure", "timed_out", "action_required"}
        severity = "urgent" if urgent else "important"
        return (f"GitHub Actions: {workflow} — {conclusion}", f"Repository: {repo_name}\nWorkflow: {workflow}\nResult: {conclusion}\n{url}".strip(), severity)

    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        action = str(payload.get("action") or "updated")[:60]
        title = str(pr.get("title") or "Pull request")[:250]
        url = str(pr.get("html_url") or "")[:500]
        return (f"Pull request {action}: {title}", f"Repository: {repo_name}\nAction: {action}\n{url}".strip(), "important")

    if event == "push":
        commits = payload.get("commits") or []
        branch = str((payload.get("ref") or "").removeprefix("refs/heads/"))[:150]
        head = payload.get("head_commit") or {}
        title = str(head.get("message") or f"{len(commits)} commit(s) pushed")[:250]
        url = str(head.get("url") or payload.get("compare") or "")[:500]
        return (f"Push to {branch or 'repository'}: {title}", f"Repository: {repo_name}\nBranch: {branch or 'unknown'}\nCommits: {len(commits)}\n{url}".strip(), "important")

    if event == "release" and str(payload.get("action")) == "published":
        release = payload.get("release") or {}
        tag = str(release.get("tag_name") or "release")[:100]
        url = str(release.get("html_url") or "")[:500]
        return (f"GitHub release published: {tag}", f"Repository: {repo_name}\nRelease: {tag}\n{url}".strip(), "important")

    if event == "repository_vulnerability_alert":
        action = str(payload.get("action") or "updated")[:60]
        return (f"GitHub dependency security alert: {action}", f"Repository: {repo_name}\nAction: {action}\nReview the repository's Security tab in GitHub.", "urgent")

    return None


@router.post("/github-webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
):
    secret = (os.getenv("GITHUB_WEBHOOK_SECRET") or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="GitHub webhook is not configured")

    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload too large")
    if not _verify_signature(secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")
    if not x_github_delivery or len(x_github_delivery) > 200:
        raise HTTPException(status_code=400, detail="Missing or invalid GitHub delivery ID")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")

    event = (x_github_event or "").strip().lower()
    summary = _summarize_event(event, payload)
    if summary is None:
        return {"ok": True, "ignored": True, "event": event}

    title, message, severity = summary
    try:
        alert, created, delivered = await _manager().enqueue_and_dispatch(
            source="github",
            title=title,
            body=message,
            severity=severity,
            dedupe_key=f"github-delivery:{x_github_delivery}",
        )
    except Exception:
        logger.exception("Could not enqueue GitHub webhook alert")
        raise HTTPException(status_code=503, detail="Could not persist GitHub alert")

    return {
        "ok": True,
        "created": created,
        "severity": alert.severity,
        "delivery": "sent" if delivered else ("queued" if alert.severity == "urgent" else "digest"),
    }
