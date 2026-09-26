"""Bounded deterministic PDF page-range projection."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from prodocux_kernel.intake.errors import SourceTooLargeError
from prodocux_kernel.intake.pdf import (
    MAX_PDF_BYTES,
    MAX_PDF_PAGE_CHARS,
    MAX_PDF_PAGES,
    MAX_PDF_TOTAL_CHARS,
)
from prodocux_kernel.intake.projection_validate import validate_continuable_projection

PARSER_CONTRACT_NAME = "prodocux_pdf_page_projection_v1"
PARSER_CONTRACT_VERSION = "1"


def extract_pdf_continuable_projection(
    payload: bytes,
    *,
    cursor: Mapping[str, Any] | None = None,
    max_pages: int = MAX_PDF_PAGES,
    ocr_min_chars: int = 20,
    ocr_requested: bool = False,
) -> dict[str, Any]:
    if not payload:
        raise ValueError("document payload is empty")
    if len(payload) > MAX_PDF_BYTES:
        raise SourceTooLargeError("document exceeds PDF inline intake limit")
    if not 1 <= max_pages <= MAX_PDF_PAGES:
        raise ValueError("max_pages must be between 1 and 50")
    source_sha256 = hashlib.sha256(payload).hexdigest()
    start_page = 1
    if cursor is not None:
        expected = {
            "schema_version": "prodocux_projection_cursor_v1",
            "source_sha256": source_sha256,
            "parser_contract_name": PARSER_CONTRACT_NAME,
            "parser_contract_version": PARSER_CONTRACT_VERSION,
        }
        for name, value in expected.items():
            if cursor.get(name) != value:
                raise ValueError(f"cursor {name} does not match source projection")
        start_page = cursor.get("next_page")
        if (
            not isinstance(start_page, int)
            or isinstance(start_page, bool)
            or start_page < 1
        ):
            raise ValueError("cursor next_page must be a positive integer")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(payload))
        total_pages = len(reader.pages)
    except Exception as exc:
        raise ValueError("invalid PDF document") from exc
    if start_page > total_pages:
        raise ValueError("cursor next_page exceeds PDF page count")
    end_page = min(start_page + max_pages, total_pages + 1)
    pages: list[dict[str, Any]] = []
    total_chars = 0
    omissions: list[str] = []
    for page_number in range(start_page, end_page):
        try:
            text = reader.pages[page_number - 1].extract_text() or ""
        except Exception:
            text = ""
        remaining = max(0, MAX_PDF_TOTAL_CHARS - total_chars)
        allowed = min(MAX_PDF_PAGE_CHARS, remaining)
        if len(text) > allowed:
            text = text[:allowed]
            if "page_text_beyond_limit" not in omissions:
                omissions.append("page_text_beyond_limit")
        total_chars += len(text)
        pages.append(
            {
                "page_number": page_number,
                "text": text,
                "ocr_required": len(text.strip()) < ocr_min_chars,
            }
        )
    next_cursor = None
    if end_page <= total_pages:
        next_cursor = {
            "schema_version": "prodocux_projection_cursor_v1",
            "source_sha256": source_sha256,
            "parser_contract_name": PARSER_CONTRACT_NAME,
            "parser_contract_version": PARSER_CONTRACT_VERSION,
            "next_page": end_page,
        }
    ocr_pages = [page["page_number"] for page in pages if page["ocr_required"]]
    if ocr_pages:
        omissions.append("ocr_required_not_performed")
    if omissions:
        disposition = "partial_unknown"
    elif next_cursor is not None:
        disposition = "partial_known"
    else:
        disposition = "complete"
    result = {
        "schema_version": "prodocux_pdf_continuable_projection_v1",
        "source_sha256": source_sha256,
        "parser_contract": {
            "name": PARSER_CONTRACT_NAME,
            "version": PARSER_CONTRACT_VERSION,
        },
        "range": {
            "unit": "page",
            "start": start_page,
            "end": end_page,
            "requested_max_pages": max_pages,
        },
        "pages": pages,
        "next_cursor": deepcopy(next_cursor),
        "ocr": {
            "requested": ocr_requested,
            "disposition": "unavailable" if ocr_requested else "not_performed",
            "pages_requiring_ocr": ocr_pages,
        },
        "coverage": {
            "disposition": disposition,
            "known_total_pages": total_pages,
            "continuation_available": next_cursor is not None,
            "omitted_content_classes": omissions,
        },
        "counts": {
            "returned_pages": len(pages),
            "returned_characters": total_chars,
        },
    }
    validate_continuable_projection(result)
    return result
