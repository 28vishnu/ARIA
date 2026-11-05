from brain.knowledge.knowledge_taxonomy import (
    audit_source_references,
    coverage_report,
    list_catalog,
    load_taxonomy,
)


def test_versioned_taxonomy_has_twenty_domains_and_stable_topic_metadata():
    taxonomy = load_taxonomy()
    assert len(taxonomy["domains"]) == 20
    assert taxonomy["topic_count"] >= 300
    topics = list_catalog("topics")
    assert len({item["id"] for item in topics}) == len(topics)
    assert all(item["domain_id"] and item["subject_id"] and item["subdomain_id"] for item in topics)


def test_catalog_can_list_subjects_and_filter_domains():
    domains = list_catalog("domains")
    assert len(domains) == 20
    computer_science = list_catalog("subjects", domain_id="computer_science")
    assert computer_science
    assert all(item["domain_id"] == "computer_science" for item in computer_science)


def test_every_topic_source_resolves_through_the_rights_registry():
    audit = audit_source_references()
    assert audit["status"] == "ok"
    assert not audit["unregistered"]
    assert not audit["unsupported_domain_references"]


def test_coverage_for_missing_database_is_explicit_and_read_only(tmp_path):
    db = tmp_path / "not-created.sqlite3"
    report = coverage_report(db)
    assert report["exists"] is False
    assert report["domains"]
    assert not db.exists()
