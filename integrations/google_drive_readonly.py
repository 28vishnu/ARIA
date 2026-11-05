"""Read-only Google Drive search integration for ARIA.

Supports OAuth, metadata search, and on-demand plain-text export of Google Docs.
It does not create, edit, move, share, or delete Drive files, and it does not
crawl the whole Drive in the background.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

logger = logging.getLogger("aria")
router = APIRouter(tags=["Google Drive read-only integration"])
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
MAX_DOC_CHARS = 12000


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
        conn.execute("CREATE TABLE IF NOT EXISTS drive_oauth_states (state_hash TEXT PRIMARY KEY, created_at REAL NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS drive_oauth_tokens (token_id INTEGER PRIMARY KEY CHECK(token_id=1), encrypted_json BLOB NOT NULL, updated_at REAL NOT NULL)")


def _config() -> tuple[str, str, str]:
    client_id = (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("GOOGLE_DRIVE_REDIRECT_URI") or "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError("Set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_DRIVE_REDIRECT_URI")
    return client_id, client_secret, redirect_uri


def _save_tokens(tokens: dict[str, Any]) -> None:
    _ensure_tables()
    cipher = _fernet()
    with _db() as conn:
        row = conn.execute("SELECT encrypted_json FROM drive_oauth_tokens WHERE token_id=1").fetchone()
        existing: dict[str, Any] = {}
        if row:
            try:
                existing = json.loads(cipher.decrypt(row["encrypted_json"]).decode("utf-8"))
            except (InvalidToken, ValueError, json.JSONDecodeError):
                existing = {}
        merged = {**existing, **tokens, "updated_at": int(time.time())}
        encrypted = cipher.encrypt(json.dumps(merged).encode("utf-8"))
        conn.execute("INSERT INTO drive_oauth_tokens(token_id,encrypted_json,updated_at) VALUES(1,?,?) ON CONFLICT(token_id) DO UPDATE SET encrypted_json=excluded.encrypted_json, updated_at=excluded.updated_at", (encrypted, time.time()))


def _load_tokens() -> dict[str, Any] | None:
    _ensure_tables()
    with _db() as conn:
        row = conn.execute("SELECT encrypted_json FROM drive_oauth_tokens WHERE token_id=1").fetchone()
    if not row:
        return None
    try:
        return json.loads(_fernet().decrypt(row["encrypted_json"]).decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stored Drive token cannot be decrypted; check encryption key and persistent disk") from exc


def build_drive_query(query: str) -> str:
    """Build a safely quoted Drive query for a name/full-text search."""
    term = " ".join(str(query).split()).strip()
    if not term:
        raise ValueError("Search query cannot be empty")
    if len(term) > 200:
        raise ValueError("Search query must be 200 characters or fewer")
    escaped = term.replace("\\", "\\\\").replace("'", "\\'")
    return f"trashed = false and (name contains '{escaped}' or fullText contains '{escaped}')"


@router.get("/drive/connect")
async def drive_connect():
    """Return Google consent URL. Keep this endpoint owner-authenticated."""
    try:
        client_id, _, redirect_uri = _config()
        _fernet()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _ensure_tables()
    state = secrets.token_urlsafe(32)
    with _db() as conn:
        conn.execute("DELETE FROM drive_oauth_states WHERE created_at < ?", (time.time() - 600,))
        conn.execute("INSERT INTO drive_oauth_states(state_hash,created_at) VALUES(?,?)", (hashlib.sha256(state.encode()).hexdigest(), time.time()))
    params = {
        "client_id": client_id, "redirect_uri": redirect_uri,
        "response_type": "code", "scope": DRIVE_SCOPE,
        "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
    }
    return {"authorization_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}", "scope": DRIVE_SCOPE}


@router.get("/drive/oauth/callback", response_class=HTMLResponse)
async def drive_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse("<h2>Google Drive connection was not completed.</h2><p>You can close this tab and try again.</p>", status_code=400)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code or state")
    _ensure_tables()
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    with _db() as conn:
        row = conn.execute("SELECT created_at FROM drive_oauth_states WHERE state_hash=?", (state_hash,)).fetchone()
        conn.execute("DELETE FROM drive_oauth_states WHERE state_hash=?", (state_hash,))
    if not row or time.time() - float(row["created_at"]) > 600:
        raise HTTPException(status_code=400, detail="OAuth state is invalid or expired; start Drive connection again")
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
        logger.exception("Google Drive OAuth token exchange failed")
        raise HTTPException(status_code=502, detail="Drive token exchange failed; check server logs and OAuth configuration") from exc
    return HTMLResponse("<h2>Google Drive connected to ARIA</h2><p>Read-only access is enabled. You can close this tab.</p>")


@router.get("/drive/status")
async def drive_status():
    try:
        tokens = _load_tokens()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"connected": bool(tokens and tokens.get("refresh_token")), "access": "read-only", "scope": DRIVE_SCOPE}


async def _get_access_token(client: httpx.AsyncClient, tokens: dict[str, Any]) -> dict[str, Any]:
    if tokens.get("access_token") and float(tokens.get("expires_at", 0)) > time.time() + 60:
        return tokens
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Drive refresh token is missing; reconnect Google Drive")
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


async def _authorized_client() -> tuple[httpx.AsyncClient, dict[str, Any]]:
    tokens = _load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        raise HTTPException(status_code=409, detail="Google Drive is not connected; use the authenticated /drive/connect endpoint first")
    client = httpx.AsyncClient(timeout=25)
    try:
        tokens = await _get_access_token(client, tokens)
        client.headers.update({"Authorization": f"Bearer {tokens['access_token']}"})
        return client, tokens
    except Exception:
        await client.aclose()
        raise


@router.get("/drive/search")
async def drive_search(q: str = Query(..., min_length=1, max_length=200), page_size: int = Query(10, ge=1, le=25)):
    """Search Drive metadata on demand. Keep owner-authenticated."""
    try:
        drive_q = build_drive_query(q)
        client, _ = await _authorized_client()
        async with client:
            response = await client.get(f"{DRIVE_API}/files", params={
                "q": drive_q, "pageSize": page_size,
                "orderBy": "modifiedTime desc",
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink,size,owners(displayName,emailAddress)),nextPageToken",
            })
            response.raise_for_status()
            payload = response.json()
        files = []
        for item in payload.get("files", []) or []:
            files.append({
                "id": item.get("id"), "name": item.get("name"),
                "mime_type": item.get("mimeType"), "modified_time": item.get("modifiedTime"),
                "web_view_link": item.get("webViewLink"), "size": item.get("size"),
                "owners": [owner.get("displayName") or owner.get("emailAddress") for owner in item.get("owners", []) if isinstance(owner, dict)],
            })
        return {"query": q, "count": len(files), "files": files, "has_more": bool(payload.get("nextPageToken")), "note": "Read-only metadata search; no Drive-wide background scan."}
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        logger.warning("Drive search failed with HTTP status %s", exc.response.status_code)
        raise HTTPException(status_code=502, detail="Google Drive search failed; check API enablement and OAuth permissions") from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        logger.exception("Drive search failed")
        raise HTTPException(status_code=503, detail="Google Drive search is temporarily unavailable") from exc


@router.get("/drive/file/{file_id}/text")
async def drive_google_doc_text(file_id: str):
    """Export text from a Google Doc only, on demand, with a strict size cap."""
    if not file_id or len(file_id) > 200 or any(ch.isspace() for ch in file_id):
        raise HTTPException(status_code=400, detail="Invalid Drive file ID")
    try:
        client, _ = await _authorized_client()
        async with client:
            meta_response = await client.get(f"{DRIVE_API}/files/{file_id}", params={"fields": "id,name,mimeType,modifiedTime,webViewLink"})
            meta_response.raise_for_status()
            metadata = meta_response.json()
            if metadata.get("mimeType") != GOOGLE_DOC_MIME:
                raise HTTPException(status_code=415, detail="Text export is supported only for Google Docs; other file types return metadata in /drive/search")
            export_response = await client.get(f"{DRIVE_API}/files/{file_id}/export", params={"mimeType": "text/plain"})
            export_response.raise_for_status()
            content = export_response.text
        return {"id": metadata.get("id"), "name": metadata.get("name"), "modified_time": metadata.get("modifiedTime"), "web_view_link": metadata.get("webViewLink"), "text": content[:MAX_DOC_CHARS], "truncated": len(content) > MAX_DOC_CHARS, "max_chars": MAX_DOC_CHARS}
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        logger.warning("Drive Doc export failed with HTTP status %s", exc.response.status_code)
        raise HTTPException(status_code=502, detail="Google Drive file request failed; verify file access and API permissions") from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        logger.exception("Drive Doc export failed")
        raise HTTPException(status_code=503, detail="Google Drive document retrieval is temporarily unavailable") from exc
