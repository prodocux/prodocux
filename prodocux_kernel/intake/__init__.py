"""Deterministic input-prep: PDF page extraction and related adapters."""

from .evidence import apply_evidence_injections, load_evidence_spec
from .formula import extract_formula_draft_from_pages, formula_rows_to_draft, parse_formula_rows
from .image import (
    IMAGE_PROFILE_SCHEMA,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    ImageOcrBackend,
    profile_image_bytes,
)
from .ocr import ocr_availability, ocr_pdf_page
from .pdf import (
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    PAGES_SCHEMA,
    build_pages_document,
    extract_pdf_pages,
    extract_pdf_bytes,
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
from .table import MAX_TABLE_BYTES, TABLE_PROFILE_SCHEMA, profile_csv, profile_csv_bytes
from .workbook import (
    MAX_WORKBOOK_BYTES,
    WORKBOOK_PROFILE_SCHEMA,
    profile_xlsx,
    profile_xlsx_bytes,
)
from .docx import DOCX_PROFILE_SCHEMA, MAX_DOCX_BYTES, profile_docx, profile_docx_bytes
from .presentation import (
    MAX_PRESENTATION_BYTES,
    PRESENTATION_PROFILE_SCHEMA,
    profile_pptx,
    profile_pptx_bytes,
)

__all__ = [
    "PAGES_SCHEMA",
    "MAX_PDF_BYTES",
    "MAX_IMAGE_BYTES",
    "MAX_IMAGE_PIXELS",
    "IMAGE_PROFILE_SCHEMA",
    "ImageOcrBackend",
    "MAX_PDF_PAGES",
    "apply_evidence_injections",
    "build_pages_document",
    "extract_embedded_page_image",
    "extract_evidence_bundle",
    "extract_evidence_item",
    "extract_formula_draft_from_pages",
    "extract_pdf_pages",
    "extract_pdf_bytes",
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
    "MAX_TABLE_BYTES",
    "TABLE_PROFILE_SCHEMA",
    "profile_csv",
    "profile_csv_bytes",
    "profile_image_bytes",
    "MAX_WORKBOOK_BYTES",
    "WORKBOOK_PROFILE_SCHEMA",
    "profile_xlsx",
    "profile_xlsx_bytes",
    "DOCX_PROFILE_SCHEMA",
    "MAX_DOCX_BYTES",
    "profile_docx",
    "profile_docx_bytes",
    "MAX_PRESENTATION_BYTES",
    "PRESENTATION_PROFILE_SCHEMA",
    "profile_pptx",
    "profile_pptx_bytes",
]
