import asyncio
import csv
import json
from pathlib import Path

import pytest

from brain.document.document_intelligence import DocumentIntelligence


def extract(path):
    return asyncio.run(DocumentIntelligence().extract_text(str(path)))


def test_extracts_plain_text_and_source_metadata(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("ARIA should preserve useful notes.", encoding="utf-8")
    pages = extract(path)
    assert pages[0]["page"] == 1
    assert "preserve useful notes" in pages[0]["text"]
    assert pages[0]["source"] == "notes.md"


def test_extracts_and_pretty_prints_json(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"project": "ARIA", "ready": True}), encoding="utf-8")
    pages = extract(path)
    assert '"project": "ARIA"' in pages[0]["text"]
    assert '"ready": true' in pages[0]["text"]


def test_extracts_csv_rows(tmp_path):
    path = tmp_path / "numbers.csv"
    path.write_text("name,value\nalpha,42\nbeta,7\n", encoding="utf-8")
    pages = extract(path)
    assert "alpha | 42" in pages[0]["text"]
    assert pages[0]["rows"] == 3


def test_extracts_docx_paragraphs_and_tables(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("ARIA document extraction test.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "item"
    table.cell(0, 1).text = "value"
    path = tmp_path / "sample.docx"
    document.save(path)
    pages = extract(path)
    assert "ARIA document extraction test" in pages[0]["text"]
    assert "item | value" in pages[0]["text"]


def test_extracts_pptx_slide_text(tmp_path):
    pptx = pytest.importorskip("pptx")
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "ARIA slide title"
    path = tmp_path / "sample.pptx"
    presentation.save(path)
    pages = extract(path)
    assert pages[0]["page"] == 1
    assert "ARIA slide title" in pages[0]["text"]


def test_extracts_xlsx_sheet_cells(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Metrics"
    sheet.append(["metric", "value"])
    sheet.append(["uptime", 99.9])
    path = tmp_path / "sample.xlsx"
    workbook.save(path)
    pages = extract(path)
    assert pages[0]["sheet"] == "Metrics"
    assert "uptime | 99.9" in pages[0]["text"]


def test_rejects_missing_file(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        extract(tmp_path / "missing.txt")


def test_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(b"data")
    with pytest.raises(ValueError, match="Unsupported file type"):
        extract(path)
