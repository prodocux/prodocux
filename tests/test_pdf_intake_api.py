from __future__ import annotations

import base64
from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from api.main import app
from prodocux_kernel.intake import MAX_PDF_BYTES


def _pdf_bytes(page_count: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _payload(raw: bytes, filename: str = "sample.pdf", max_pages: int = 50) -> dict:
    return {
        "document_filename": filename,
        "document_b64": base64.b64encode(raw).decode("ascii"),
        "max_pages": max_pages,
    }


def test_extract_pages_returns_frozen_contract_and_no_path() -> None:
    response = TestClient(app).post("/v1/intake/extract-pages", json=_payload(_pdf_bytes(2)))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ocr_required"
    assert body["page_count"] == 2
    assert len(body["source_sha256"]) == 64
    assert body["pages"][0] == {"page_number": 1, "text": "", "ocr_required": True}
    assert "path" not in str(body).casefold()


def test_extract_pages_rejects_paths_and_wrong_suffix() -> None:
    client = TestClient(app)
    for filename in ("../sample.pdf", "folder/sample.pdf", "sample.txt", ".."):
        response = client.post("/v1/intake/extract-pages", json=_payload(_pdf_bytes(), filename))
        assert response.status_code in {400, 422}


def test_extract_pages_rejects_malformed_base64_and_pdf() -> None:
    client = TestClient(app)
    malformed = client.post("/v1/intake/extract-pages", json={
        "document_filename": "sample.pdf", "document_b64": "%%%", "max_pages": 50,
    })
    assert malformed.status_code == 400
    invalid = client.post("/v1/intake/extract-pages", json=_payload(b"not a pdf"))
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "invalid PDF document"


def test_extract_pages_enforces_requested_page_limit() -> None:
    response = TestClient(app).post(
        "/v1/intake/extract-pages", json=_payload(_pdf_bytes(2), max_pages=1)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PDF page count exceeds requested limit"


def test_extract_pages_rejects_oversized_base64_before_decode() -> None:
    response = TestClient(app).post("/v1/intake/extract-pages", json={
        "document_filename": "large.pdf",
        "document_b64": "A" * ((((MAX_PDF_BYTES + 2) // 3) * 4) + 1),
        "max_pages": 50,
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "document_b64 exceeds PDF intake limit"


def test_extract_pages_rejects_unknown_request_fields() -> None:
    payload = _payload(_pdf_bytes())
    payload["unexpected"] = "not part of intake_request_v1"
    response = TestClient(app).post("/v1/intake/extract-pages", json=payload)
    assert response.status_code == 422
