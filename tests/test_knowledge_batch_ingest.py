import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from brain.knowledge.open_knowledge import connect, import_records
from brain.knowledge.knowledge_batch_ingest import run_batch

class KnowledgeBatchIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.db = self.root / "aria.sqlite3"; self.topics = self.root / "topics.txt"
        self.topics.write_text("Alpha\nBeta\nGamma\nDelta\n", encoding="utf-8")
        connect(str(self.db)).close()
    def tearDown(self): self.temp.cleanup()
    def test_preview_does_not_call_ingestion(self):
        with patch("brain.knowledge.knowledge_batch_ingest.seed_topics") as seed:
            result = run_batch(self.db, self.topics, batch_size=2, batch_number=1)
        seed.assert_not_called(); self.assertEqual(result["status"], "planned")
        self.assertEqual(result["topics"], ["Alpha", "Beta"])
    def test_execute_ingests_only_selected_batch(self):
        with patch("brain.knowledge.knowledge_batch_ingest.seed_topics", return_value={"stored_records": 2}) as seed:
            result = run_batch(self.db, self.topics, batch_size=2, batch_number=2, execute=True)
        seed.assert_called_once(); self.assertEqual(seed.call_args.kwargs["topics"], ["Gamma", "Delta"])
        self.assertEqual(result["status"], "executed")
    def test_refuses_missing_database_without_creating_it(self):
        missing = self.root / "missing.sqlite3"
        with self.assertRaises(FileNotFoundError): run_batch(missing, self.topics)
        self.assertFalse(missing.exists())
    def test_bounds_batch_size(self):
        with self.assertRaises(ValueError): run_batch(self.db, self.topics, batch_size=101)
    def test_empty_batch_is_safe(self):
        import_records(str(self.db), [{"source":"wikipedia", "source_id":t, "title":t,
            "content":"A sufficiently short test summary.", "url":f"https://en.wikipedia.org/wiki/{t}",
            "license":"test"} for t in ["Alpha", "Beta", "Gamma", "Delta"]])
        result = run_batch(self.db, self.topics, batch_size=2, execute=True)
        self.assertEqual(result["status"], "nothing_to_ingest"); self.assertIsNone(result["ingestion"])

if __name__ == "__main__": unittest.main()
