"""Read-only source rights/provenance registry for ARIA knowledge ingestion.

The registry is a review checklist, not legal advice. A source is not automatically
cleared for ingestion or redistribution merely because it appears here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).with_name("source_registry.json")
REQUIRED_FIELDS = {
    "display_name", "catalog_url", "license_status", "license_summary",
    "attribution_required", "redistribution_review_required",
    "commercial_use_review_required", "source_url_required",
    "record_level_license_required", "notes",
}

def load_registry(path: str | Path = REGISTRY_PATH) -> dict[str, Any]:
    """Load and validate registry JSON without modifying the knowledge database."""
    registry_path = Path(path)
    with registry_path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported or missing source registry schema_version")
    sources = data.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("Source registry must contain a non-empty 'sources' object")
    for name, entry in sources.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(entry, dict):
            raise ValueError("Each source must have a non-empty name and object entry")
        missing = REQUIRED_FIELDS - entry.keys()
        if missing:
            raise ValueError(f"Source {name!r} missing required fields: {sorted(missing)}")
        for field in ("attribution_required", "redistribution_review_required",
                      "commercial_use_review_required", "source_url_required",
                      "record_level_license_required"):
            if not isinstance(entry[field], bool):
                raise ValueError(f"Source {name!r} field {field!r} must be boolean")
        if not str(entry["catalog_url"]).startswith("https://"):
            raise ValueError(f"Source {name!r} catalog_url must use HTTPS")
    return data

def source_policy(source: str, path: str | Path = REGISTRY_PATH) -> dict[str, Any] | None:
    """Return a source policy, or None for an unregistered source."""
    name = str(source or "").strip().casefold()
    registry = load_registry(path)
    for registered_name, entry in registry["sources"].items():
        if registered_name.casefold() == name:
            return dict(entry)
    return None

def audit_source_names(source_names, path: str | Path = REGISTRY_PATH) -> dict[str, list[str]]:
    """Report registered and unregistered source names without changing records."""
    registry_names = {name.casefold() for name in load_registry(path)["sources"]}
    supplied = {str(name).strip() for name in source_names if str(name).strip()}
    registered = sorted(name for name in supplied if name.casefold() in registry_names)
    unregistered = sorted(name for name in supplied if name.casefold() not in registry_names)
    return {"registered": registered, "unregistered": unregistered}
