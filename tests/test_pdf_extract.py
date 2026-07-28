"""CR-001: PDF intake kernel + pdf_extract skill."""
import json

import pytest

from prodocux_kernel.intake import pdf as intake
from prodocux_kernel.templating.mapping import MappingConfig, map_sources_to_sections
from skills.pdf_extract import pdf_extract as skill


def _sample_source_pages_text():
    return (
        "=== EU_PIF.pdf | Page 1 ===\n"
        "Product Name: Dark Perfume\n"
        "Nome commerciale DEMO PERFUME\n\n"
        "=== EU_PIF.pdf | Page 2 ===\n"
        "INCI Aqua CAS 7732-18-5 Alcohol denat.\n"
    )


def test_parse_source_pages_txt():
    pages = intake.parse_source_pages_txt(_sample_source_pages_text())
    assert len(pages) == 2
    assert pages[0]["file"] == "EU_PIF.pdf"
    assert pages[0]["page"] == 1
    assert "Nome commerciale" in pages[0]["text"]
    assert pages[1]["page"] == 2
    assert pages[1]["char_count"] == len(pages[1]["text"])


def test_normalize_pifaudit_record():
    rec = intake.normalize_page_record({
        "Document_ID": "doc.pdf",
        "Source_File": "/tmp/doc.pdf",
        "Page_Number": 3,
        "Extracted_Text": "hello",
    })
    assert rec == {"file": "doc.pdf", "page": 3, "text": "hello", "char_count": 5}


def test_build_pages_document_schema():
    pages = intake.parse_source_pages_txt(_sample_source_pages_text())
    doc = intake.build_pages_document(pages, engine="source_pages_txt")
    assert doc["schema"] == intake.PAGES_SCHEMA
    assert doc["page_count"] == 2
    assert doc["engine"] == "source_pages_txt"
    assert "kernel_version" in doc


def test_pages_for_mapping_integration():
    config = MappingConfig.from_dict({
        "template_rules": {"heading_styles": ["Heading 1"], "body_style": "Normal"},
        "sections": [
            {"id": "desc", "heading": "產品敘述", "mode": "paragraphs",
             "source_queries": ["Nome commerciale", "Product Name"]},
            {"id": "formula", "heading": "成分表", "mode": "table",
             "source_queries": ["INCI", "CAS"]},
        ],
    })
    pages = intake.pages_for_mapping(intake.parse_source_pages_txt(_sample_source_pages_text()))
    hits = map_sources_to_sections(pages, config)
    assert hits["desc"][0].page == 1
    assert hits["formula"][0].page == 2


def test_extract_pdf_pages_roundtrip(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    pdf_path = tmp_path / "two_pages.pdf"
    writer.write(str(pdf_path))

    pages, err = intake.extract_pdf_pages(pdf_path)
    assert err is None
    assert len(pages) == 2
    assert pages[0]["page"] == 1
    assert pages[0]["file"] == "two_pages.pdf"
    assert "source_path" in pages[0]


def test_extract_pdfs_envelope(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    pdf_path = tmp_path / "one.pdf"
    writer.write(str(pdf_path))

    doc = intake.extract_pdfs([pdf_path])
    assert doc["schema"] == intake.PAGES_SCHEMA
    assert doc["page_count"] == 1
    assert len(doc["source_files"]) == 1
    assert doc["source_files"][0]["sha256"]
    assert doc["engine"] == "pypdf"


def test_write_and_load_pages_json(tmp_path):
    pages = intake.parse_source_pages_txt(_sample_source_pages_text())
    doc = intake.build_pages_document(pages)
    out = tmp_path / "pages.json"
    intake.write_pages_json(doc, out)
    loaded = intake.load_pages_json(out)
    assert loaded["page_count"] == 2
    assert json.loads(out.read_text(encoding="utf-8"))["pages"][0]["page"] == 1


def test_skill_from_source_pages(tmp_path):
    src = tmp_path / "source_pages.txt"
    src.write_text(_sample_source_pages_text(), encoding="utf-8")
    out = tmp_path / "out.json"
    result = skill.extract_from_source_pages(str(src))
    assert result["ok"] is True
    skill.main(["--from-source-pages", str(src), "--out", str(out), "--json"])
    assert out.is_file()
    # --out writes the pages.json envelope (not the CLI wrapper)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == intake.PAGES_SCHEMA
    assert data["page_count"] == 2


def test_skill_missing_pdf_fails():
    result = skill.extract_from_pdfs(["/nonexistent/file.pdf"])
    assert result["ok"] is False
    assert result["document"]["errors"]
