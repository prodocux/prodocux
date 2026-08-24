"""Format ceilings, media types, and output-name rules."""

from __future__ import annotations

import re

from ..intake.docx import MAX_DOCX_BYTES
from ..intake.pdf import MAX_PDF_BYTES
from ..intake.presentation import MAX_PRESENTATION_BYTES
from ..intake.table import MAX_TABLE_BYTES
from ..intake.workbook import MAX_WORKBOOK_BYTES
from .errors import OUTPUT_NAME_INVALID, RenderContractError

INLINE_OUTPUT_MAX_BYTES = 2 * 1024 * 1024
OUTPUT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$")

FORMAT_EXTENSIONS = {
    "docx": ".docx",
    "xlsx": ".xlsx",
    "csv": ".csv",
    "pptx": ".pptx",
    "pdf": ".pdf",
}

FORMAT_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}

FORMAT_MAX_BYTES = {
    "docx": MAX_DOCX_BYTES,
    "xlsx": MAX_WORKBOOK_BYTES,
    "csv": MAX_TABLE_BYTES,
    "pptx": MAX_PRESENTATION_BYTES,
    "pdf": MAX_PDF_BYTES,
}


def validate_output_name(name: str, target_format: str) -> str:
    if not OUTPUT_NAME_PATTERN.fullmatch(name):
        raise RenderContractError(
            OUTPUT_NAME_INVALID,
            "output_name must be a plain basename with an allowed character set",
        )
    if "/" in name or "\\" in name or ".." in name:
        raise RenderContractError(OUTPUT_NAME_INVALID, "output_name must be a basename")
    expected = FORMAT_EXTENSIONS[target_format]
    if not name.lower().endswith(expected):
        raise RenderContractError(
            OUTPUT_NAME_INVALID,
            "output_name extension must match target_format",
        )
    return name
