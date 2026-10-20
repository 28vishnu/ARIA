import json

import pytest

from brain.knowledge.dataset_importer import DATASETS
from brain.knowledge.source_registry import audit_source_names, load_registry, source_policy


def test_registry_covers_all_dataset_importer_sources():
    registry = load_registry()
    assert set(DATASETS) == set(registry["sources"])


def test_each_source_has_reviewable_provenance_fields():
    for entry in load_registry()["sources"].values():
        assert entry["catalog_url"].startswith("https://")
        assert entry["license_status"]
        assert entry["license_summary"]
        assert entry["source_url_required"] is True
        assert entry["record_level_license_required"] is True


def test_source_policy_is_case_insensitive_and_unknown_is_none():
    assert source_policy("WIKIPEDIA")["attribution_required"] is True
    assert source_policy("not-a-source") is None


def test_audit_identifies_unregistered_sources():
    result = audit_source_names(["wikipedia", "future_dataset", "WIKIDATA"])
    assert result["registered"] == ["WIKIDATA", "wikipedia"]
    assert result["unregistered"] == ["future_dataset"]


def test_invalid_registry_is_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 1, "sources": {"bad": {}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing required fields"):
        load_registry(bad)
