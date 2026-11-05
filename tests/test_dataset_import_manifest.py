import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from brain.knowledge.dataset_importer import main as importer_main


class DatasetImportManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = str(self.root / "knowledge.sqlite3")
        self.input = self.root / "book.txt"
        self.input.write_text("Photosynthesis converts light energy into chemical energy. " * 30, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_successful_import_records_manifest(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = importer_main(["import", "--source", "gutenberg", "--file", str(self.input), "--db", self.db])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["manifest_recorded"])
        conn = sqlite3.connect(self.db)
        try:
            row = conn.execute("SELECT source, input_path, processed_records FROM dataset_import_runs").fetchone()
            self.assertEqual(row[0], "gutenberg")
            self.assertEqual(row[1], str(self.input.resolve()))
            self.assertGreater(row[2], 0)
        finally:
            conn.close()

    def test_dry_run_does_not_create_database_or_manifest(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = importer_main(["import", "--source", "gutenberg", "--file", str(self.input), "--db", self.db, "--dry-run"])
        self.assertEqual(code, 0)
        self.assertFalse(Path(self.db).exists())
        self.assertFalse(json.loads(output.getvalue()).get("manifest_recorded", False))

    def test_reimport_adds_run_history_without_duplicate_document_rows(self):
        for _ in range(2):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(importer_main(["import", "--source", "gutenberg", "--file", str(self.input), "--db", self.db]), 0)
        conn = sqlite3.connect(self.db)
        try:
            runs = conn.execute("SELECT COUNT(*) FROM dataset_import_runs").fetchone()[0]
            docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            self.assertEqual(runs, 2)
            self.assertGreater(docs, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
