"""Read-only Google Calendar OAuth integration for ARIA.

Reads upcoming events from the primary calendar and queues reminders. It never
creates, edits, deletes, or invites attendees to calendar events.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from integrations.alert_manager import AlertManager

logger = logging.getLogger("aria")
router = APIRouter(tags=["Google Calendar read-only integration"])
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


async def _telegram_notifier(message: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
    chat_id = (os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id or not message.strip():
        logger.warning("Calendar alert not delivered: Telegram notifier is not configured")
        return False
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            for start in range(0, len(message), 3900):
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": message[start:start + 3900], "disable_web_page_preview": True},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not payload.get("ok"):
                    return False
        return True
    except Exception:
        logger.exception("Calendar alert Telegram delivery failed")
        return False


def _db_path() -> str:
    return os.getenv("ARIA_ALERT_DB_PATH", "./aria_data/alerts.sqlite3")


def _fernet() -> Fernet:
    key = (os.getenv("ARIA_GMAIL_TOKEN_ENCRYPTION_KEY") or "").strip()
    if not key:
        raise RuntimeError("ARIA_GMAIL_TOKEN_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("ARIA_GMAIL_TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc


@contextmanager
def _db():
    import sqlite3
    from pathlib import Path
    path = _db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_tables() -> None:
    with _db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS calendar_oauth_states (state_hash TEXT PRIMARY KEY, created_at REAL NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS calendar_oauth_tokens (token_id INTEGER PRIMARY KEY CHECK(token_id=1), encrypted_json BLOB NOT NULL, updated_at REAL NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS calendar_seen_reminders (dedupe_key TEXT PRIMARY KEY, created_at REAL NOT NULL)")


def _config() -> tuple[str, str, str]:
    client_id = (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("GOOGLE_CALENDAR_REDIRECT_URI") or "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError("Set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_CALENDAR_REDIRECT_URI")
    return client_id, client_secret, redirect_uri


def _save_tokens(tokens: dict[str, Any]) -> None:
    _ensure_tables()
    cipher = _fernet()
    with _db() as conn:
        row = conn.execute("SELECT encrypted_json FROM calendar_oauth_tokens WHERE token_id=1").fetchone()
        existing: dict[str, Any] = {}
        if row:
            try:
                existing = json.loads(cipher.decrypt(row["encrypted_json"]).decode("utf-8"))
            except (InvalidToken, ValueError, json.JSONDecodeError):
                existing = {}
        merged = {**existing, **tokens, "updated_at": int(time.time())}
        encrypted = cipher.encrypt(json.dumps(merged).encode("utf-8"))
        conn.execute("INSERT INTO calendar_oauth_tokens(token_id,encrypted_json,updated_at) VALUES(1,?,?) ON CONFLICT(token_id) DO UPDATE SET encrypted_json=excluded.encrypted_json, updated_at=excluded.updated_at", (encrypted, time.time()))


def _load_tokens() -> dict[str, Any] | None:
    _ensure_tables()
    with _db() as conn:
        row = conn.execute("SELECT encrypted_json FROM calendar_oauth_tokens WHERE token_id=1").fetchone()
    if not row:
        return None
    try:
        return json.loads(_fernet().decrypt(row["encrypted_json"]).decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stored Calendar token cannot be decrypted; check encryption key and persistent disk") from exc


async def _refresh_access_token(client: httpx.AsyncClient, tokens: dict[str, Any]) -> dict[str, Any]:
    if tokens.get("access_token") and float(tokens.get("expires_at", 0)) > time.time() + 60:
        return tokens
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Calendar refresh token is missing; reconnect Google Calendar")
    client_id, client_secret, _ = _config()
    response = await client.post(GOOGLE_TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    })
    response.raise_for_status()
    payload = response.json()
    updated = {**tokens, **payload, "expires_at": time.time() + int(payload.get("expires_in", 3600))}
    _save_tokens(updated)
    return updated


@router.get("/calendar/connect")
async def calendar_connect():
    """Return Google consent URL. Protect this endpoint with ARIA owner auth."""
    try:
        client_id, _, redirect_uri = _config()
        _fernet()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _ensure_tables()
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    with _db() as conn:
        conn.execute("DELETE FROM calendar_oauth_states WHERE created_at < ?", (time.time() - 600,))
        conn.execute("INSERT INTO calendar_oauth_states(state_hash,created_at) VALUES(?,?)", (state_hash, time.time()))
    params = {
        "client_id": client_id, "redirect_uri": redirect_uri,
        "response_type": "code", "scope": CALENDAR_SCOPE,
        "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
    }
    return {"authorization_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}", "scope": CALENDAR_SCOPE}


@router.get("/calendar/oauth/callback", response_class=HTMLResponse)
async def calendar_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse("<h2>Google Calendar connection was not completed.</h2><p>You can close this tab and try again.</p>", status_code=400)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code or state")
    _ensure_tables()
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    with _db() as conn:
        row = conn.execute("SELECT created_at FROM calendar_oauth_states WHERE state_hash=?", (state_hash,)).fetchone()
        conn.execute("DELETE FROM calendar_oauth_states WHERE state_hash=?", (state_hash,))
    if not row or time.time() - float(row["created_at"]) > 600:
        raise HTTPException(status_code=400, detail="OAuth state is invalid or expired; start Calendar connection again")
    try:
        client_id, client_secret, redirect_uri = _config()
        _fernet()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(GOOGLE_TOKEN_URL, data={
                "code": code, "client_id": client_id, "client_secret": client_secret,
                "redirect_uri": redirect_uri, "grant_type": "authorization_code",
            })
            response.raise_for_status()
            payload = response.json()
        if not payload.get("access_token"):
            raise RuntimeError("Google did not return an access token")
        payload["expires_at"] = time.time() + int(payload.get("expires_in", 3600))
        _save_tokens(payload)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        logger.exception("Google Calendar OAuth token exchange failed")
        raise HTTPException(status_code=502, detail="Calendar token exchange failed; check server logs and OAuth configuration") from exc
    return HTMLResponse("<h2>Google Calendar connected to ARIA</h2><p>Read-only access is enabled. You can close this tab.</p>")


@router.get("/calendar/status")
async def calendar_status():
    try:
        tokens = _load_tokens()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"connected": bool(tokens and tokens.get("refresh_token")), "access": "read-only", "scope": CALENDAR_SCOPE}


def _event_start(event: dict[str, Any]) -> datetime | None:
    raw = event.get("start") or {}
    value = raw.get("dateTime")
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    # All-day events do not have a precise reminder time; do not alert as if they do.
    return None


class GoogleCalendarReadOnlyIntegration:
    """Poll upcoming primary-calendar events and queue one-time reminders."""
    def __init__(self, manager: AlertManager | None = None, now=None):
        self.manager = manager or AlertManager(notifier=_telegram_notifier)
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def poll(self) -> dict[str, Any]:
        try:
            tokens = _load_tokens()
            if not tokens or not tokens.get("refresh_token"):
                return {"connected": False, "processed": 0}
            now = self._now()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            now_utc = now.astimezone(timezone.utc)
            async with httpx.AsyncClient(timeout=20) as client:
                tokens = await _refresh_access_token(client, tokens)
                headers = {"Authorization": f"Bearer {tokens['access_token']}"}
                response = await client.get(
                    f"{CALENDAR_API}/calendars/primary/events", headers=headers,
                    params={
                        "timeMin": now_utc.isoformat().replace("+00:00", "Z"),
                        "timeMax": (now_utc + timedelta(hours=25)).isoformat().replace("+00:00", "Z"),
                        "singleEvents": "true", "orderBy": "startTime", "maxResults": 100,
                    },
                )
                response.raise_for_status()
                events = response.json().get("items", []) or []
                processed = 0
                for event in events:
                    event_id = str(event.get("id", "")).strip()
                    title = str(event.get("summary", "Untitled event")).strip()[:180]
                    start = _event_start(event)
                    if not event_id or start is None:
                        continue
                    minutes = (start.astimezone(timezone.utc) - now_utc).total_seconds() / 60
                    if minutes < 0 or minutes > 60:
                        continue
                    bucket = "15m" if minutes <= 15 else "60m"
                    dedupe = f"calendar:{event_id}:{bucket}"
                    with _db() as conn:
                        seen = conn.execute("SELECT 1 FROM calendar_seen_reminders WHERE dedupe_key=?", (dedupe,)).fetchone()
                    if seen:
                        continue
                    start_text = start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    lead = "within 15 minutes" if bucket == "15m" else "within about an hour"
                    await self.manager.enqueue_and_dispatch(
                        source="Google Calendar", title=f"Upcoming: {title}",
                        body=f"Starts {lead}.\nStart time: {start_text}",
                        severity="urgent", dedupe_key=dedupe,
                    )
                    with _db() as conn:
                        conn.execute("INSERT OR IGNORE INTO calendar_seen_reminders(dedupe_key,created_at) VALUES(?,?)", (dedupe, time.time()))
                    processed += 1
                return {"connected": True, "processed": processed}
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
            logger.warning("Google Calendar polling failed: %s", type(exc).__name__)
            return {"connected": False, "processed": 0, "error": type(exc).__name__}


__all__ = ["router", "GoogleCalendarReadOnlyIntegration", "CALENDAR_SCOPE"]
