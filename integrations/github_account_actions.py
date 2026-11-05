"""Owner-authenticated GitHub account and repository operations for ARIA.

This router must be included by main.py, whose global owner-session middleware
protects all routes here. GitHub credentials are read only from the environment
and are never returned to clients or included in error responses.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("aria.github_account_actions")
router = APIRouter(prefix="/github", tags=["GitHub account actions"])
GITHUB_API = "https://api.github.com"
API_VERSION = "2022-11-28"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


class CreateRepositoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=350)
    private: bool = True
    auto_init: bool = True
    confirm_create: bool


class GitHubAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str = "GitHub API request failed"):
        super().__init__(message)
        self.status_code = status_code


def _token() -> str:
    value = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_PAT") or "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="GitHub integration is not configured. Set a least-privilege GitHub token in the deployment environment.")
    return value


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "ARIA-JARVIS",
    }


async def _request(method: str, path: str, *, params: dict[str, Any] | None = None,
                   payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], httpx.Headers]:
    token = _token()
    if not path.startswith("/") or ".." in path.split("/"):
        raise HTTPException(status_code=400, detail="Invalid GitHub API path")
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await client.request(
                method, f"{GITHUB_API}{path}", headers=_headers(token), params=params, json=payload
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="GitHub request timed out; check the repository state before retrying.") from exc
    except httpx.HTTPError as exc:
        logger.warning("GitHub API transport error: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not reach GitHub API") from exc

    if response.status_code >= 400:
        status = response.status_code
        # Do not relay raw provider error bodies; they may contain private details.
        if status == 401:
            detail = "GitHub rejected the configured token. Replace it with a valid token."
        elif status == 403:
            detail = "GitHub denied the request. Check token permissions, organization policy, and rate limits."
        elif status == 404:
            detail = "GitHub resource was not found or is not accessible to this token."
        elif status == 409:
            detail = "GitHub reports a repository conflict. Check whether it already exists."
        elif status == 422:
            detail = "GitHub rejected the request. The repository name may already exist or a required field may be invalid."
        elif status == 429:
            detail = "GitHub rate limit reached. Retry after the rate limit resets."
        else:
            detail = f"GitHub API returned HTTP {status}."
        raise HTTPException(status_code=status if status in {401, 403, 404, 409, 422, 429} else 502, detail=detail)
    if response.status_code == 204 or not response.content:
        return {}, response.headers
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="GitHub returned an invalid response") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="GitHub returned an unexpected response")
    return data, response.headers


def _safe_repository(item: dict[str, Any]) -> dict[str, Any]:
    """Return an explicit allowlist of repository fields, never provider payloads wholesale."""
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "full_name": item.get("full_name"),
        "private": bool(item.get("private", True)),
        "html_url": item.get("html_url"),
        "clone_url": item.get("clone_url"),
        "default_branch": item.get("default_branch"),
        "description": item.get("description"),
        "updated_at": item.get("updated_at"),
        "archived": bool(item.get("archived", False)),
    }


@router.get("/account/status")
async def github_account_status() -> dict[str, Any]:
    """Verify the configured GitHub token against /user without exposing it."""
    if not any((os.getenv("GITHUB_TOKEN"), os.getenv("GH_TOKEN"), os.getenv("GITHUB_PAT"))):
        return {"configured": False, "authenticated": False, "provider": "github"}
    user, headers = await _request("GET", "/user")
    scopes = [s.strip() for s in headers.get("X-OAuth-Scopes", "").split(",") if s.strip()]
    return {
        "configured": True,
        "authenticated": True,
        "login": user.get("login"),
        "id": user.get("id"),
        "profile_url": user.get("html_url"),
        "token_scopes": scopes,
        "provider": "github",
        "note": "Scope header may be empty for fine-grained personal access tokens.",
    }


@router.get("/repositories")
async def list_repositories(
    per_page: int = Query(default=30, ge=1, le=100),
    page: int = Query(default=1, ge=1, le=1000),
    sort: str = Query(default="updated", pattern="^(created|updated|pushed|full_name)$"),
) -> dict[str, Any]:
    """List authenticated-user repositories with a bounded, sanitized response."""
    items = await _request_list("/user/repos", params={
        "visibility": "all", "affiliation": "owner,collaborator,organization_member",
        "sort": sort, "direction": "desc", "per_page": per_page, "page": page,
    })
    return {"count": len(items), "repositories": [_safe_repository(item) for item in items]}


async def _request_list(path: str, *, params: dict[str, Any]) -> list[dict[str, Any]]:
    token = _token()
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await client.get(f"{GITHUB_API}{path}", headers=_headers(token), params=params)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="GitHub request timed out") from exc
    except httpx.HTTPError as exc:
        logger.warning("GitHub list API transport error: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not reach GitHub API") from exc
    if response.status_code >= 400:
        status = response.status_code
        detail = "GitHub denied or could not complete the request. Check token permissions and rate limits."
        if status == 401:
            detail = "GitHub rejected the configured token."
        elif status == 404:
            detail = "GitHub resource was not found or is not accessible to this token."
        raise HTTPException(status_code=status if status in {401, 403, 404, 429} else 502, detail=detail)
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="GitHub returned invalid JSON") from exc
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise HTTPException(status_code=502, detail="GitHub returned an unexpected list response")
    return payload


@router.post("/repositories")
async def create_repository(request: CreateRepositoryRequest) -> dict[str, Any]:
    """Create a GitHub repository only after explicit confirmation in the request."""
    if not request.confirm_create:
        raise HTTPException(status_code=400, detail="Set confirm_create=true to explicitly authorize repository creation.")
    name = request.name.strip()
    if not _NAME_RE.fullmatch(name) or name in {".", ".."}:
        raise HTTPException(status_code=422, detail="Repository name must use letters, numbers, '.', '_' or '-' and start with a letter or number.")
    payload = {
        "name": name,
        "description": request.description.strip(),
        "private": request.private,
        "auto_init": request.auto_init,
    }
    repo, _ = await _request("POST", "/user/repos", payload=payload)
    return {"created": True, "repository": _safe_repository(repo), "message": "GitHub repository created. No local code was pushed."}


@router.get("/repositories/{owner}/{repo}/workflow-runs")
async def list_workflow_runs(
    owner: str,
    repo: str,
    per_page: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Read recent Actions runs for a repository visible to the token."""
    if not _OWNER_RE.fullmatch(owner) or not _NAME_RE.fullmatch(repo):
        raise HTTPException(status_code=422, detail="Invalid GitHub owner or repository name.")
    data, _ = await _request("GET", f"/repos/{owner}/{repo}/actions/runs", params={"per_page": per_page})
    runs = data.get("workflow_runs", [])
    if not isinstance(runs, list):
        runs = []
    safe_runs = []
    for item in runs:
        if not isinstance(item, dict):
            continue
        safe_runs.append({
            "id": item.get("id"), "name": item.get("name"), "event": item.get("event"),
            "status": item.get("status"), "conclusion": item.get("conclusion"),
            "branch": item.get("head_branch"), "html_url": item.get("html_url"),
            "created_at": item.get("created_at"), "updated_at": item.get("updated_at"),
        })
    return {"repository": f"{owner}/{repo}", "total_count": data.get("total_count", len(safe_runs)), "workflow_runs": safe_runs}


__all__ = ["router", "CreateRepositoryRequest", "github_account_status", "list_repositories", "create_repository", "list_workflow_runs"]
