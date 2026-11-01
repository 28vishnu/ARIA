import asyncio
import json

from brain.knowledge.academic_sources import search_academic_sources, search_arxiv, search_openalex


class FakeResponse:
    def __init__(self, text="", payload=None):
        self.text = text
        self.payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, arxiv=None, openalex=None):
        self.arxiv = arxiv
        self.openalex = openalex
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "arxiv" in url:
            if isinstance(self.arxiv, Exception):
                raise self.arxiv
            return self.arxiv
        if isinstance(self.openalex, Exception):
            raise self.openalex
        return self.openalex


def test_arxiv_adapter_returns_dated_preprint_metadata_without_fulltext():
    payload = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>http://arxiv.org/abs/2401.00001v2</id><title> A Transformer Study </title>
      <summary>Abstract text.</summary><published>2024-01-01T00:00:00Z</published>
      <updated>2024-01-02T00:00:00Z</updated><author><name>Researcher</name></author>
      <link rel="alternate" href="https://arxiv.org/abs/2401.00001"/>
      <category term="cs.CL"/></entry></feed>"""
    client = FakeClient(arxiv=FakeResponse(payload))
    rows = asyncio.run(search_arxiv("transformer", client=client, limit=99))
    assert len(rows) == 1
    assert rows[0]["source_id"] == "2401.00001v2"
    assert rows[0]["document_type"] == "preprint"
    assert rows[0]["publication_date"].startswith("2024-01-01")
    assert "full-text reuse depends" in rows[0]["license"]
    assert client.calls[0][1]["params"]["max_results"] == 10


def test_openalex_adapter_reconstructs_abstract_and_links_source():
    payload = {"results": [{
        "id": "https://openalex.org/W123", "doi": "https://doi.org/10.1234/example",
        "title": "A Knowledge Retrieval Study", "publication_date": "2025-03-02",
        "publication_year": 2025, "abstract_inverted_index": {"Retrieval": [0], "improves": [1], "ranking.": [2]},
        "authorships": [{"author": {"display_name": "A. Author"}}],
        "type": "article", "open_access": {"is_oa": True},
    }]}
    client = FakeClient(openalex=FakeResponse(payload=payload))
    rows = asyncio.run(search_openalex("knowledge retrieval", client=client))
    assert len(rows) == 1
    assert rows[0]["url"] == "https://doi.org/10.1234/example"
    assert rows[0]["content"] == "Retrieval improves ranking."
    assert rows[0]["authors"] == ["A. Author"]


def test_provider_failure_is_reported_without_faking_results():
    client = FakeClient(arxiv=RuntimeError("offline"), openalex=RuntimeError("offline"))
    result = asyncio.run(search_academic_sources("recent transformer research", client=client))
    assert result["providers"] == {"arxiv": "unavailable", "openalex": "unavailable"}
    assert result["results"] == []
