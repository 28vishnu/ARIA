import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path

from brain.knowledge.dataset_importer import records_for
from brain.knowledge.open_knowledge import connect, import_records, search


class DatasetImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = str(self.root / "knowledge.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_stackexchange_imports_questions_and_answers(self):
        path = self.write(
            "Posts.xml",
            '<posts><row Id="1" PostTypeId="1" Title="Gravity" Body="Gravity attracts mass."/>'
            '<row Id="2" PostTypeId="2" ParentId="1" Body="Objects with mass attract each other."/></posts>',
        )
        records = list(records_for("stackexchange", path))
        self.assertEqual(len(records), 2)
        self.assertTrue(any("Answer to Stack Exchange post 1" in r["title"] for r in records))
        import_records(self.db, records)
        self.assertTrue(search(self.db, "gravity", 5))

    def test_pubmed_xml(self):
        path = self.write(
            "pubmed.xml",
            '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID>'
            '<Article><ArticleTitle>Research on cells</ArticleTitle><Abstract>'
            '<AbstractText>Cells are the basic unit of life.</AbstractText>'
            '</Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>',
        )
        records = list(records_for("pubmed", path))
        self.assertEqual(records[0]["source_id"], "123")
        self.assertIn("basic unit", records[0]["content"])

    def test_openalex_jsonl_reconstructs_abstract(self):
        path = self.write(
            "works.jsonl",
            json.dumps({"id": "W1", "title": "Plants", "abstract_inverted_index": {"Plants": [0], "grow": [1]}}),
        )
        records = list(records_for("openalex", path))
        self.assertIn("Plants grow", records[0]["content"])

    def test_text_sources(self):
        path = self.write("book.txt", "Photosynthesis uses light to produce chemical energy. " * 100)
        records = list(records_for("gutenberg", path))
        self.assertTrue(records)
        self.assertEqual(records[0]["source"], "gutenberg")

    def test_existing_database_migration_adds_license(self):
        conn = connect(self.db)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
        conn.close()
        self.assertIn("license", columns)


if __name__ == "__main__":
    unittest.main()
