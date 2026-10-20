import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from brain.knowledge.knowledge_coverage import build_coverage_report, load_wikipedia_titles
from brain.knowledge.open_knowledge import import_records


class KnowledgeCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "knowledge.sqlite3"
        self.topics = self.root / "topics.txt"
        self.topics.write_text(
            "# sample catalog\nPython\nPhotosynthesis\nNew Topic\npython\n", encoding="utf-8"
        )
        import_records(str(self.db), [{
            "source": "wikipedia", "source_id": "python", "title": "Python",
            "content": "Python is a programming language.",
            "url": "https://en.wikipedia.org/wiki/Python", "license": "CC BY-SA",
        }])

    def tearDown(self):
        self.temp.cleanup()

    def test_report_matches_titles_and_deduplicates_catalog(self):
        report = build_coverage_report(self.topics, self.db, batch_size=1, batch_number=1)
        self.assertEqual(report["catalog_topics"], 3)
        self.assertEqual(report["duplicate_catalog_entries_removed"], 1)
        self.assertEqual(report["covered_topics"], 1)
        self.assertEqual(report["missing_topics"], 2)
        self.assertEqual(report["batch_topics"], ["Photosynthesis"])
        self.assertTrue(report["read_only"])

    def test_batch_planning_is_deterministic(self):
        first = build_coverage_report(self.topics, self.db, batch_size=1, batch_number=1)
        second = build_coverage_report(self.topics, self.db, batch_size=1, batch_number=2)
        self.assertEqual(first["batch_topics"], ["Photosynthesis"])
        self.assertEqual(second["batch_topics"], ["New Topic"])
        self.assertIsNone(second["next_batch"])

    def test_audit_does_not_modify_database(self):
        before = self.db.read_bytes()
        build_coverage_report(self.topics, self.db)
        self.assertEqual(self.db.read_bytes(), before)

    def test_missing_database_is_not_created(self):
        missing = self.root / "missing.sqlite3"
        with self.assertRaises(FileNotFoundError):
            load_wikipedia_titles(missing)
        self.assertFalse(missing.exists())

    def test_invalid_batch_size_rejected(self):
        with self.assertRaises(ValueError):
            build_coverage_report(self.topics, self.db, batch_size=0)


if __name__ == "__main__":
    unittest.main()
