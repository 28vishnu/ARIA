"""Deterministic evidence metadata policy for ARIA's knowledge pipeline.

This module does not generate facts or claim that a source is true. It validates
source links, normalizes provenance/date metadata, and derives a conservative
freshness signal only when a publication/update date is available.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit
import ipaddress
import re


_DATE_FIELDS = ("published_at", "publication_date", "updated_at", "modified_at", "date")
_BLOCKED_SCHEMES = {"javascript", "data", "file", "ftp", "vbscript"}


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            # Accept a date-only value; do not guess ambiguous locale formats.
            try:
                dt = datetime.strptime(raw[:10], "%Y-%m-%d")
            except (TypeError, ValueError):
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_source_url(value: Any) -> str:
    """Return a canonical public HTTP(S) URL, or an empty string if unsafe/invalid."""
    raw = str(value or "").strip()
    if not raw or len(raw) > 4096:
        return ""
    try:
        parts = urlsplit(raw)
        scheme = parts.scheme.lower()
        if scheme in _BLOCKED_SCHEMES or scheme not in {"http", "https"}:
            return ""
        if not parts.hostname or parts.username is not None or parts.password is not None:
            return ""
        host = parts.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return ""
        try:
            address = ipaddress.ip_address(host.strip("[]"))
            if not address.is_global:
                return ""
        except ValueError:
            if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))+", host):
                return ""
        netloc = host
        try:
            port = parts.port
        except ValueError:
            return ""
        if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            netloc = f"{host}:{port}"
        path = parts.path or "/"
        return urlunsplit((scheme, netloc, path, parts.query, ""))
    except (TypeError, ValueError):
        return ""


def _freshness_for_age(age_days: float) -> tuple[float, str]:
    if age_days < -1:
        return 0.5, "future_dated"
    age = max(0.0, age_days)
    if age <= 30:
        return 1.0, "fresh"
    if age <= 90:
        return 0.8, "fresh"
    if age <= 180:
        return 0.6, "aging"
    if age <= 365:
        return 0.4, "aging"
    return 0.2, "stale"


def apply_evidence_metadata_policy(
    item: Dict[str, Any], *, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Copy and annotate a record without inventing provenance or factual claims.

    Existing explicit freshness scores are preserved unless `freshness_from_date`
    is true. Invalid external URLs are removed from the clickable citation field,
    but the evidence body is retained for the caller's existing relevance checks.
    """
    record = dict(item or {})
    now_utc = (now or datetime.now(timezone.utc))
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)

    raw_url = record.get("url") or record.get("source_url") or record.get("uri")
    if raw_url:
        normalized_url = normalize_source_url(raw_url)
        if normalized_url:
            record["url"] = normalized_url
            record.pop("source_url", None)
            record.pop("uri", None)
            record["citation_url_valid"] = True
        else:
            record["url"] = ""
            record["citation_url_valid"] = False
            record["citation_url_rejected"] = True
    else:
        record.setdefault("url", "")
        record.setdefault("citation_url_valid", False)

    date_value = None
    date_field = None
    for field in _DATE_FIELDS:
        if record.get(field):
            date_value = _parse_datetime(record[field])
            date_field = field
            if date_value is not None:
                break
    if date_value is not None:
        age_days = (now_utc - date_value).total_seconds() / 86400.0
        score, status = _freshness_for_age(age_days)
        record["source_date"] = date_value.isoformat()
        record["source_date_field"] = date_field
        record["source_age_days"] = round(age_days, 2)
        record["freshness_status"] = status
        if "freshness" not in record or record.get("freshness_from_date") is True:
            record["freshness"] = score
    elif any(record.get(field) for field in _DATE_FIELDS):
        record["freshness_status"] = "unknown_invalid_date"
    else:
        record.setdefault("freshness_status", "unknown")

    source = str(record.get("source") or "unknown").strip()
    evidence_type = str(record.get("evidence_type") or "retrieved").strip()
    record["source"] = source or "unknown"
    record["evidence_type"] = evidence_type or "retrieved"
    identity = "\n".join((record["source"].casefold(), record.get("url", ""),
                           str(record.get("title") or "").strip().casefold(),
                           re.sub(r"\s+", " ", str(record.get("content") or "").strip()).casefold()))
    record.setdefault("evidence_id", sha256(identity.encode("utf-8", "replace")).hexdigest()[:24])
    return record
