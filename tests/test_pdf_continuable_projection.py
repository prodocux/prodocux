from __future__ import annotations

import base64
import io
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pymupdf import Document
from pypdf import PdfWriter

from api.main import app
from prodocux_kernel.intake import (
    ProjectionValidationError,
    extract_pdf_continuable_projection,
    validate_continuable_projection,
)


def _pdf(page_count: int) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    writer.write(output)
    return output.getvalue()


def _pdf_with_tail_marker(page_count: int, marker: str) -> bytes:
    document = Document()
    for page_number in range(1, page_count + 1):
        page = document.new_page(width=200, height=200)
        page.insert_text(
            (20, 40),
            marker
            if page_number == page_count
            else f"searchable page content number {page_number}",
        )
    payload = document.tobytes()
    document.close()
    return payload


def _schema() -> dict:
    root = Path(__file__).resolve().parents[1]
    return json.loads(
        (
            root / "prodocux_kernel/schemas/prodocux_pdf_continuable_projection_v1.json"
        ).read_text(encoding="utf-8")
    )


def test_pdf_55_pages_continues_as_50_plus_5_without_gap() -> None:
    raw = _pdf_with_tail_marker(55, "TAIL_MARKER_PAGE_55 searchable content")
    first = extract_pdf_continuable_projection(raw)
    second = extract_pdf_continuable_projection(raw, cursor=first["next_cursor"])
    Draft202012Validator(_schema()).validate(first)
    Draft202012Validator(_schema()).validate(second)
    assert first["range"] == {
        "unit": "page",
        "start": 1,
        "end": 51,
        "requested_max_pages": 50,
    }
    assert first["coverage"]["disposition"] == "partial_known"
    assert second["range"] == {
        "unit": "page",
        "start": 51,
        "end": 56,
        "requested_max_pages": 50,
    }
    assert second["coverage"]["disposition"] == "complete"
    assert [page["page_number"] for page in first["pages"] + second["pages"]] == list(
        range(1, 56)
    )
    assert "TAIL_MARKER_PAGE_55" in second["pages"][-1]["text"]


def test_cursor_source_binding_and_range_validation_fail_closed() -> None:
    raw = _pdf(2)
    first = extract_pdf_continuable_projection(raw, max_pages=1)
    changed = deepcopy(first["next_cursor"])
    changed["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source_sha256"):
        extract_pdf_continuable_projection(raw, cursor=changed, max_pages=1)
    beyond = deepcopy(first["next_cursor"])
    beyond["next_page"] = 3
    with pytest.raises(ValueError, match="exceeds"):
        extract_pdf_continuable_projection(raw, cursor=beyond, max_pages=1)


def test_pdf_continuation_http_and_capability_disclosure() -> None:
    client = TestClient(app)
    raw = _pdf(55)
    request = {
        "document_filename": "large.pdf",
        "document_b64": base64.b64encode(raw).decode("ascii"),
        "max_pages": 50,
    }
    first = client.post("/v1/intake/extract-pages/continue", json=request)
    assert first.status_code == 200
    request["cursor"] = first.json()["next_cursor"]
    second = client.post("/v1/intake/extract-pages/continue", json=request)
    assert second.status_code == 200
    assert second.json()["counts"]["returned_pages"] == 5
    profiles = {
        item["format"]: item
        for item in client.get("/v1/intake/projection-capabilities").json()["profiles"]
    }
    assert profiles["pdf"]["status"] == "bounded_with_continuation"
    assert profiles["pdf"]["range_units"] == ["page"]


def test_pdf_semantics_reject_gap_and_false_coverage() -> None:
    result = extract_pdf_continuable_projection(_pdf(2), max_pages=1)
    invalid = deepcopy(result)
    invalid["pages"][0]["page_number"] = 2
    with pytest.raises(ProjectionValidationError, match="contiguous"):
        validate_continuable_projection(invalid)
    invalid = deepcopy(result)
    invalid["coverage"]["continuation_available"] = False
    with pytest.raises(ProjectionValidationError, match="continuation"):
        validate_continuable_projection(invalid)


def test_scanned_and_mixed_pdf_disclose_unperformed_ocr() -> None:
    scanned = extract_pdf_continuable_projection(_pdf(1))
    assert scanned["coverage"]["disposition"] == "partial_unknown"
    assert scanned["coverage"]["omitted_content_classes"] == [
        "ocr_required_not_performed"
    ]
    assert scanned["ocr"] == {
        "requested": False,
        "disposition": "not_performed",
        "pages_requiring_ocr": [1],
    }

    document = Document()
    page = document.new_page(width=200, height=200)
    page.insert_text((20, 40), "enough searchable text for the first page")
    document.new_page(width=200, height=200)
    mixed_raw = document.tobytes()
    document.close()
    mixed = extract_pdf_continuable_projection(mixed_raw, ocr_requested=True)
    assert mixed["coverage"]["disposition"] == "partial_unknown"
    assert mixed["ocr"]["disposition"] == "unavailable"
    assert mixed["ocr"]["pages_requiring_ocr"] == [2]


def test_pdf_inline_source_too_large_has_stable_error() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/intake/extract-pages/continue",
        json={
            "document_filename": "large.pdf",
            "document_b64": "A" * ((((10 * 1024 * 1024) + 2) // 3) * 4 + 1),
        },
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "SOURCE_TOO_LARGE"
    assert response.json()["detail"]["retryable"] is False
