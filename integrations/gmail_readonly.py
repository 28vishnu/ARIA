"""Read-only Gmail OAuth integration for ARIA.

Uses Gmail's readonly scope, stores encrypted refresh tokens in ARIA's persistent
SQLite database, and emits metadata-only alerts. It never sends, archives,
labels, deletes, or marks messages read.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from contextlib import contextmanager
from email.utils import parseaddr
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from integrations.alert_manager import AlertManager

logger = logging.getLogger("aria")
router = APIRouter(tags=["Gmail read-only integration"])
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


async def _gmail_telegram_notifier(message: str) -> bool:
    """Deliver alerts to the configured Telegram owner chat; fail closed otherwise."""
    bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
    chat_id = (os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not bot_token or not chat_id or not message.strip():
        logger.warning("Gmail alert not delivered: Telegram notifier is not configured")
        return False
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            for start in range(0, len(message), 3900):
                response = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": message[start:start + 3900], "disable_web_page_preview": True},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not payload.get("ok"):
                    return False
        return True
    except Exception:
        logger.exception("Gmail alert Telegram delivery failed")
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
        conn.execute("""CREATE TABLE IF NOT EXISTS gmail_oauth_states (
            state_hash TEXT PRIMARY KEY, created_at REAL NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS gmail_oauth_tokens (
            token_id INTEGER PRIMARY KEY CHECK(token_id=1),
            encrypted_json BLOB NOT NULL, updated_at REAL NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS gmail_seen_messages (
            message_id TEXT PRIMARY KEY, seen_at REAL NOT NULL
        )""")


def _config() -> tuple[str, str, str]:
    client_id = (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError("Set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REDIRECT_URI")
    return client_id, client_secret, redirect_uri


def _save_tokens(tokens: dict[str, Any]) -> None:
    _ensure_tables()
    cipher = _fernet()
    with _db() as conn:
        row = conn.execute("SELECT encrypted_json FROM gmail_oauth_tokens WHERE token_id=1").fetchone()
        existing: dict[str, Any] = {}
        if row:
            try:
                existing = json.loads(cipher.decrypt(row["encrypted_json"]).decode("utf-8"))
            except (InvalidToken, ValueError, json.JSONDecodeError):
                existing = {}
        merged = {**existing, **tokens, "updated_at": int(time.time())}
        encrypted = cipher.encrypt(json.dumps(merged).encode("utf-8"))
        conn.execute("INSERT INTO gmail_oauth_tokens(token_id,encrypted_json,updated_at) VALUES(1,?,?) ON CONFLICT(token_id) DO UPDATE SET encrypted_json=excluded.encrypted_json, updated_at=excluded.updated_at", (encrypted, time.time()))


def _load_tokens() -> dict[str, Any] | None:
    _ensure_tables()
    with _db() as conn:
        row = conn.execute("SELECT encrypted_json FROM gmail_oauth_tokens WHERE token_id=1").fetchone()
    if not row:
        return None
    try:
        return json.loads(_fernet().decrypt(row["encrypted_json"]).decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stored Gmail token cannot be decrypted; check encryption key and persistent disk") from exc


async def _refresh_access_token(client: httpx.AsyncClient, tokens: dict[str, Any]) -> dict[str, Any]:
    if tokens.get("access_token") and float(tokens.get("expires_at", 0)) > time.time() + 60:
        return tokens
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Gmail refresh token is missing; reconnect Gmail")
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


@router.get("/gmail/connect")
async def gmail_connect():
    """Return Google's consent URL. Protect this endpoint with ARIA owner auth."""
    try:
        client_id, _, redirect_uri = _config()
        _fernet()  # Fail early if token encryption is not configured.
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _ensure_tables()
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    with _db() as conn:
        conn.execute("DELETE FROM gmail_oauth_states WHERE created_at < ?", (time.time() - 600,))
        conn.execute("INSERT INTO gmail_oauth_states(state_hash,created_at) VALUES(?,?)", (state_hash, time.time()))
    params = {
        "client_id": client_id, "redirect_uri": redirect_uri,
        "response_type": "code", "scope": GMAIL_SCOPE,
        "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
    }
    return {"authorization_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}", "scope": GMAIL_SCOPE}


@router.get("/gmail/oauth/callback", response_class=HTMLResponse)
async def gmail_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse("<h2>Gmail connection was not completed.</h2><p>You can close this tab and try again in ARIA.</p>", status_code=400)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code or state")
    _ensure_tables()
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    with _db() as conn:
        row = conn.execute("SELECT created_at FROM gmail_oauth_states WHERE state_hash=?", (state_hash,)).fetchone()
        conn.execute("DELETE FROM gmail_oauth_states WHERE state_hash=?", (state_hash,))
    if not row or time.time() - float(row["created_at"]) > 600:
        raise HTTPException(status_code=400, detail="OAuth state is invalid or expired; start Gmail connection again")
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
        logger.exception("Gmail OAuth token exchange failed")
        raise HTTPException(status_code=502, detail="Gmail token exchange failed; check server logs and OAuth configuration") from exc
    return HTMLResponse("<h2>Gmail connected to ARIA</h2><p>Read-only access is enabled. You can close this tab.</p>")


@router.get("/gmail/status")
async def gmail_status():
    try:
        tokens = _load_tokens()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"connected": bool(tokens and tokens.get("refresh_token")), "access": "read-only", "scope": GMAIL_SCOPE}


class GmailReadOnlyIntegration:
    """Poll a small recent inbox window; only message metadata is sent to alerts."""
    def __init__(self, manager: AlertManager | None = None):
        self.manager = manager or AlertManager(notifier=_gmail_telegram_notifier)

    async def poll(self) -> dict[str, Any]:
        try:
            tokens = _load_tokens()
            if not tokens or not tokens.get("refresh_token"):
                return {"connected": False, "processed": 0}
            async with httpx.AsyncClient(timeout=20) as client:
                tokens = await _refresh_access_token(client, tokens)
                headers = {"Authorization": f"Bearer {tokens['access_token']}"}
                response = await client.get(f"{GMAIL_API}/messages", headers=headers, params={"q": "in:inbox newer_than:1d", "maxResults": 25})
                response.raise_for_status()
                messages = response.json().get("messages", []) or []
                processed = 0
                urgent_terms = ("security alert", "suspicious sign-in", "unusual activity", "account compromised", "password changed", "password reset", "2-step verification", "two-step verification")
                for item in messages:
                    message_id = str(item.get("id", ""))
                    if not message_id:
                        continue
                    with _db() as conn:
                        seen = conn.execute("SELECT 1 FROM gmail_seen_messages WHERE message_id=?", (message_id,)).fetchone()
                    if seen:
                        continue
                    detail = await client.get(f"{GMAIL_API}/messages/{message_id}", headers=headers, params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
                    detail.raise_for_status()
                    payload = detail.json()
                    header_map = {str(h.get("name", "")).lower(): str(h.get("value", "")) for h in payload.get("payload", {}).get("headers", [])}
                    subject = header_map.get("subject", "(no subject)")[:180]
                    sender = parseaddr(header_map.get("from", ""))[1] or header_map.get("from", "unknown sender")
                    sender = sender[:180]
                    snippet = str(payload.get("snippet", "")).replace("\n", " ").strip()[:240]
                    # Only a short metadata summary is sent; never fetch full message bodies.
                    body = f"From: {sender}\nSubject: {subject}" + (f"\nPreview: {snippet}" if snippet else "")
                    urgent = any(term in subject.lower() for term in urgent_terms)
                    await self.manager.enqueue_and_dispatch(
                        source="Gmail", title=subject, body=body,
                        severity="urgent" if urgent else "important",
                        dedupe_key=f"gmail:{message_id}",
                    )
                    with _db() as conn:
                        conn.execute("INSERT OR IGNORE INTO gmail_seen_messages(message_id,seen_at) VALUES(?,?)", (message_id, time.time()))
                    processed += 1
                return {"connected": True, "processed": processed}
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
            logger.warning("Gmail read-only polling failed: %s", type(exc).__name__)
            return {"connected": False, "processed": 0, "error": type(exc).__name__}


__all__ = ["router", "GmailReadOnlyIntegration", "GMAIL_SCOPE"]
