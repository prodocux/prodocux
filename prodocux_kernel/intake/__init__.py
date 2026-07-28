"""Deterministic input-prep: PDF page extraction and related adapters."""

from .evidence import apply_evidence_injections, load_evidence_spec
from .formula import extract_formula_draft_from_pages, formula_rows_to_draft, parse_formula_rows
from .ocr import ocr_availability, ocr_pdf_page
from .pdf import (
    PAGES_SCHEMA,
    build_pages_document,
    extract_pdf_pages,
    extract_pdfs,
    load_pages_json,
    normalize_page_record,
    parse_source_pages_txt,
    pages_for_mapping,
    write_pages_json,
)
from .pdf_images import (
    extract_embedded_page_image,
    extract_evidence_bundle,
    extract_evidence_item,
    render_pdf_page,
)

__all__ = [
    "PAGES_SCHEMA",
    "apply_evidence_injections",
    "build_pages_document",
    "extract_embedded_page_image",
    "extract_evidence_bundle",
    "extract_evidence_item",
    "extract_formula_draft_from_pages",
    "extract_pdf_pages",
    "formula_rows_to_draft",
    "parse_formula_rows",
    "extract_pdfs",
    "load_evidence_spec",
    "load_pages_json",
    "normalize_page_record",
    "ocr_availability",
    "ocr_pdf_page",
    "parse_source_pages_txt",
    "pages_for_mapping",
    "render_pdf_page",
    "write_pages_json",
]
