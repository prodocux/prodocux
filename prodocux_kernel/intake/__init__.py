"""Deterministic input-prep: PDF page extraction and related adapters."""

from .csv_projection import extract_csv_continuable_projection
from .docx import DOCX_PROFILE_SCHEMA, MAX_DOCX_BYTES, profile_docx, profile_docx_bytes
from .evidence import apply_evidence_injections, load_evidence_spec
from .formula import (
    extract_formula_draft_from_pages,
    formula_rows_to_draft,
    parse_formula_rows,
)
from .image import (
    IMAGE_PROFILE_SCHEMA,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    ImageOcrBackend,
    profile_image_bytes,
)
from .image_projection import extract_image_tile_projection
from .ocr import ocr_availability, ocr_pdf_page
from .pdf import (
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    PAGES_SCHEMA,
    build_pages_document,
    extract_pdf_bytes,
    extract_pdf_pages,
    extract_pdfs,
    load_pages_json,
    normalize_page_record,
    pages_for_mapping,
    parse_source_pages_txt,
    write_pages_json,
)
from .pdf_images import (
    extract_embedded_page_image,
    extract_evidence_bundle,
    extract_evidence_item,
    render_pdf_page,
)
from .pdf_projection import extract_pdf_continuable_projection
from .presentation import (
    MAX_PRESENTATION_BYTES,
    PRESENTATION_PROFILE_SCHEMA,
    profile_pptx,
    profile_pptx_bytes,
)
from .presentation_projection import extract_pptx_continuable_projection
from .projection_validate import ProjectionValidationError, validate_continuable_projection
from .table import MAX_TABLE_BYTES, TABLE_PROFILE_SCHEMA, profile_csv, profile_csv_bytes
from .workbook import (
    MAX_WORKBOOK_BYTES,
    WORKBOOK_PROFILE_SCHEMA,
    profile_xlsx,
    profile_xlsx_bytes,
)
from .workbook_projection import extract_xlsx_continuable_projection

__all__ = [
    "DOCX_PROFILE_SCHEMA",
    "IMAGE_PROFILE_SCHEMA",
    "MAX_DOCX_BYTES",
    "MAX_IMAGE_BYTES",
    "MAX_IMAGE_PIXELS",
    "MAX_PDF_BYTES",
    "MAX_PDF_PAGES",
    "MAX_PRESENTATION_BYTES",
    "MAX_TABLE_BYTES",
    "MAX_WORKBOOK_BYTES",
    "PAGES_SCHEMA",
    "PRESENTATION_PROFILE_SCHEMA",
    "ProjectionValidationError",
    "TABLE_PROFILE_SCHEMA",
    "WORKBOOK_PROFILE_SCHEMA",
    "ImageOcrBackend",
    "apply_evidence_injections",
    "build_pages_document",
    "extract_csv_continuable_projection",
    "extract_embedded_page_image",
    "extract_evidence_bundle",
    "extract_evidence_item",
    "extract_formula_draft_from_pages",
    "extract_image_tile_projection",
    "extract_pdf_bytes",
    "extract_pdf_continuable_projection",
    "extract_pdf_pages",
    "extract_pdfs",
    "extract_pptx_continuable_projection",
    "extract_xlsx_continuable_projection",
    "formula_rows_to_draft",
    "load_evidence_spec",
    "load_pages_json",
    "normalize_page_record",
    "ocr_availability",
    "ocr_pdf_page",
    "pages_for_mapping",
    "parse_formula_rows",
    "parse_source_pages_txt",
    "profile_csv",
    "profile_csv_bytes",
    "profile_docx",
    "profile_docx_bytes",
    "profile_image_bytes",
    "profile_pptx",
    "profile_pptx_bytes",
    "profile_xlsx",
    "profile_xlsx_bytes",
    "render_pdf_page",
    "write_pages_json",
    "validate_continuable_projection",
]
