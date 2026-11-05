import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from brain.knowledge.open_knowledge import connect, import_records
from brain.knowledge.daily_knowledge_refresh import RUNS_TABLE, run_daily_refresh

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def make_db(path: Path) -> None:
    conn = connect(str(path))
    conn.close()
    import_records(str(path), [{
        "source": "test", "source_id": "one", "title": "One",
        "content": "A sufficiently detailed test record about a stable topic.",
        "url": "https://example.org/one", "license": "test",
    }])


def test_preview_is_read_only_and_does_not_fetch(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    with patch("brain.knowledge.daily_knowledge_refresh.collect_news_and_updates") as collect:
        result = run_daily_refresh(db, execute=False, now=NOW)
    collect.assert_not_called()
    assert result["status"] == "preview"
    assert result["network_requested"] is False
    assert result["database_writes_requested"] is False
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name=?", (RUNS_TABLE,)).fetchone() is None
    conn.close()


def test_execute_collects_and_persists_run_report(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    with patch("brain.knowledge.daily_knowledge_refresh.collect_news_and_updates", return_value={
        "feeds_checked": 2, "items_seen": 3,
        "feeds": [{"feed": "one", "status": "ok"}, {"feed": "two", "status": "ok"}],
    }) as collect:
        result = run_daily_refresh(db, execute=True, now=NOW)
    collect.assert_called_once()
    assert result["status"] == "ok"
    conn = sqlite3.connect(db)
    row = conn.execute(f"SELECT utc_day,status,report_json FROM {RUNS_TABLE}").fetchone()
    conn.close()
    assert row[0] == "2026-10-24" and row[1] == "ok"
    assert json.loads(row[2])["items_seen"] == 3


def test_second_successful_run_same_utc_day_skips_network(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    fake = {"feeds_checked": 1, "items_seen": 0, "feeds": [{"feed": "one", "status": "ok"}]}
    with patch("brain.knowledge.daily_knowledge_refresh.collect_news_and_updates", return_value=fake):
        first = run_daily_refresh(db, execute=True, now=NOW)
    assert first["status"] == "ok"
    with patch("brain.knowledge.daily_knowledge_refresh.collect_news_and_updates") as collect:
        second = run_daily_refresh(db, execute=True, now=NOW)
    collect.assert_not_called()
    assert second["status"] == "already_refreshed_today"


def test_force_allows_second_run_same_day(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    fake = {"feeds_checked": 1, "items_seen": 0, "feeds": [{"feed": "one", "status": "ok"}]}
    with patch("brain.knowledge.daily_knowledge_refresh.collect_news_and_updates", return_value=fake):
        run_daily_refresh(db, execute=True, now=NOW)
        second = run_daily_refresh(db, execute=True, force=True, now=NOW)
    assert second["status"] == "ok"


def test_failed_feed_returns_partial_and_is_recorded(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    fake = {"feeds_checked": 2, "items_seen": 1, "feeds": [
        {"feed": "one", "status": "ok"}, {"feed": "two", "status": "error", "error": "offline"}
    ]}
    with patch("brain.knowledge.daily_knowledge_refresh.collect_news_and_updates", return_value=fake):
        result = run_daily_refresh(db, execute=True, now=NOW)
    assert result["status"] == "partial"
    assert result["failed_feed_count"] == 1


def test_missing_database_is_not_created(tmp_path):
    db = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        run_daily_refresh(db)
    assert not db.exists()


def test_invalid_freshness_limit_rejected(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    with pytest.raises(ValueError):
        run_daily_refresh(db, max_age_days=0)
