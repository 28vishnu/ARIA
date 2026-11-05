import tempfile
import unittest
from pathlib import Path

from brain.knowledge.knowledge_maintenance import bootstrap, database_status
from brain.knowledge.open_knowledge import import_records


class KnowledgeMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = str(self.root / "aria.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_status_reports_sources_and_provenance(self):
        import_records(self.db, [{
            "source": "wikipedia", "source_id": "1", "title": "Photosynthesis",
            "content": "Plants use sunlight to convert water and carbon dioxide into sugars.",
            "url": "https://en.wikipedia.org/wiki/Photosynthesis", "license": "CC BY-SA",
        }])
        status = database_status(self.db)
        self.assertEqual(status["total_documents"], 1)
        self.assertEqual(status["documents_by_source"]["wikipedia"], 1)
        self.assertEqual(status["records_with_license_metadata"], 1)
        self.assertEqual(status["records_with_source_urls"], 1)

    def test_bootstrap_zero_seed_does_not_require_network(self):
        result = bootstrap(db_path=self.db, topics_file=None, seed_limit=0, collect_news=False)
        self.assertEqual(result["database_after"]["total_documents"], 0)
        self.assertIsNone(result["seed"])

    def test_bootstrap_rejects_unbounded_timeout(self):
        with self.assertRaises(ValueError):
            bootstrap(db_path=self.db, topics_file=None, seed_limit=0, timeout=120)


if __name__ == "__main__":
    unittest.main()
