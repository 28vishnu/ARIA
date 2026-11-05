import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from brain.knowledge.dataset_importer import main as importer_main


class IncrementalImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = str(self.root / "knowledge.sqlite3")
        self.input = self.root / "sample.txt"
        self.input.write_text("Photosynthesis converts light energy into chemical energy. " * 30, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def run_import(self, *extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = importer_main(["import", "--source", "gutenberg", "--file", str(self.input), "--db", self.db, *extra])
        return code, json.loads(output.getvalue())

    def test_skip_unchanged_after_successful_import(self):
        code, first = self.run_import()
        self.assertEqual(code, 0)
        self.assertTrue(first["manifest_recorded"])
        code, second = self.run_import("--skip-unchanged")
        self.assertEqual(code, 0)
        self.assertTrue(second["skipped"])
        self.assertEqual(second["reason"], "unchanged_input_fingerprint")

    def test_changed_input_is_imported(self):
        self.assertEqual(self.run_import()[0], 0)
        self.input.write_text("Changed source content. " * 50, encoding="utf-8")
        # Ensure the filesystem metadata fingerprint changes on coarse-timestamp filesystems.
        import os, time
        os.utime(self.input, ns=(self.input.stat().st_atime_ns, self.input.stat().st_mtime_ns + 2_000_000_000))
        code, result = self.run_import("--skip-unchanged")
        self.assertEqual(code, 0)
        self.assertFalse(result.get("skipped", False))
        self.assertTrue(result["manifest_recorded"])

    def test_first_run_is_not_skipped(self):
        code, result = self.run_import("--skip-unchanged")
        self.assertEqual(code, 0)
        self.assertFalse(result.get("skipped", False))

    def test_dry_run_does_not_skip_or_write_manifest(self):
        self.assertEqual(self.run_import()[0], 0)
        code, result = self.run_import("--skip-unchanged", "--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(result["dry_run"])
        self.assertFalse(result.get("skipped", False))


if __name__ == "__main__":
    unittest.main()
