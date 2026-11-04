import base64
import hashlib
import io
import unicodedata
from copy import deepcopy

import pytest
from api.main import app
from fastapi.testclient import TestClient
from prodocux_kernel.verification.source_binding import (
    capabilities,
    verify_source_bound_evidence,
)
from prodocux_kernel.verification.source_binding_contracts import validation as v
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas


def request_for(text="Subtotal: 900.00 / Amount due: 1100.00", page=1, pages=1):
    stream = io.BytesIO()
    canvas = Canvas(stream)
    for _ in range(pages):
        if text:
            canvas.drawString(20, 700, text)
        canvas.showPage()
    canvas.save()
    raw = stream.getvalue()
    extracted = unicodedata.normalize(
        "NFC", PdfReader(io.BytesIO(raw)).pages[page - 1].extract_text() or ""
    )
    quote = "Amount due: 1100.00"
    start = extracted.find(quote)
    start = max(0, start)
    return {
        "schema_version": "prodocux_source_binding_request_draft_v1",
        "request_id": "request-runtime-001",
        "source": {
            "document_b64": base64.b64encode(raw).decode(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "media_type": "application/pdf",
        },
        "parser_contract": {"name": "prodocux_pdf_page_projection_v1", "version": "1"},
        "normalization": "unicode_nfc_preserve_whitespace_codepoint_v1",
        "page_number": page,
        "expected_page_text_sha256": v.sha(extracted.encode()),
        "checks": [
            {
                "check_id": "check-001",
                "quote_range": {"start": start, "end": start + len(quote)},
                "quote": quote,
                "value_range": {"start": start + 12, "end": start + 19},
                "conversion_rule": "ascii_decimal_exact_scale_v1",
                "declared_value": "1100.00",
                "scale": 2,
            }
        ],
    }


def test_real_source_binding_forgery_and_value():
    request = request_for()
    good = verify_source_bound_evidence(request)
    assert good["semantic_result"]["overall_status"] == "pass"
    assert "Amount due" not in str(good)
    forged = deepcopy(request)
    forged["checks"][0]["quote"] = "Amount due: 900.00"
    forged["checks"][0]["declared_value"] = "900.00"
    assert (
        verify_source_bound_evidence(forged)["semantic_result"]["checks"][0][
            "reason_code"
        ]
        == "QUOTE_MISMATCH"
    )
    wrong = deepcopy(request)
    wrong["checks"][0]["declared_value"] = "900.00"
    assert (
        verify_source_bound_evidence(wrong)["semantic_result"]["checks"][0][
            "reason_code"
        ]
        == "VALUE_MISMATCH"
    )
    subtotal = deepcopy(request)
    subtotal["checks"][0].update(
        quote="Subtotal: 900.00",
        quote_range={"start": 0, "end": 16},
        value_range={"start": 10, "end": 16},
        declared_value="900.00",
    )
    assert (
        verify_source_bound_evidence(subtotal)["semantic_result"]["overall_status"]
        == "pass"
    )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("page_number", 2, "PAGE_UNAVAILABLE"),
        ("expected_page_text_sha256", "0" * 64, "PAGE_PROJECTION_MISMATCH"),
        ("parser_contract", {"name": "wrong", "version": "1"}, "REQUEST_INVALID"),
    ],
)
def test_identity(field, value, code):
    request = request_for()
    request[field] = value
    with pytest.raises(v.Invalid, match=code):
        verify_source_bound_evidence(request)


def test_page_after_fifty_and_ocr_review():
    assert (
        verify_source_bound_evidence(request_for(page=55, pages=55))["semantic_result"][
            "overall_status"
        ]
        == "pass"
    )
    blank = verify_source_bound_evidence(request_for(text=""))
    assert blank["semantic_result"]["overall_status"] == "review"
    assert (
        "ocr_required_not_performed"
        in blank["semantic_result"]["coverage"]["omissions"]
    )


def test_http_shapes_strict_json_and_encryption(monkeypatch):
    monkeypatch.delenv("PDX_KERNEL_BEARER_TOKENS", raising=False)
    with TestClient(app) as client:
        response = client.post("/v1/verify/source-bound-evidence", json=request_for())
        assert response.status_code == 200, response.text
        v.shape("urn:pdx:draft:cr003:core:1#/$defs/report", response.json())
        response = client.post(
            "/v1/verify/source-bound-evidence",
            content='{"request_id":"a","request_id":"b"}',
        )
        assert response.status_code == 400
        v.shape("urn:pdx:draft:cr003:core:1#/$defs/error", response.json())
    v.shape("urn:pdx:draft:cr003:support:2#/$defs/capabilities", capabilities())
    request = request_for()
    writer = PdfWriter()
    writer.add_page(
        PdfReader(
            io.BytesIO(base64.b64decode(request["source"]["document_b64"]))
        ).pages[0]
    )
    writer.encrypt("secret")
    out = io.BytesIO()
    writer.write(out)
    raw = out.getvalue()
    request["source"].update(
        document_b64=base64.b64encode(raw).decode(),
        sha256=v.sha(raw),
        size_bytes=len(raw),
    )
    with pytest.raises(v.Invalid, match="SOURCE_ENCRYPTED"):
        verify_source_bound_evidence(request)


def test_packaged_schema_parity_and_jcs_rejections():
    import json
    from pathlib import Path

    package = Path(v.__file__).parent
    document = Path(__file__).resolve().parents[1] / "docs/source-bound-evidence"
    for source in (document / "schemas").glob("*.json"):
        assert (package / "schemas" / source.name).read_text(
            encoding="utf-8"
        ) == source.read_text(encoding="utf-8")
    vectors = json.loads((document / "canonical-vectors.json").read_text())
    for item in vectors["positive"]:
        assert len(v.digest(v.parse(item["raw"]))) == 64
    for item in vectors["negative"]:
        with pytest.raises(v.Invalid):
            v.digest(v.parse(item["raw"]))


def test_clipped_page_and_declared_negative_zero():
    request = request_for("Amount due: 1100.00 " + ("x" * 50000))
    raw = base64.b64decode(request["source"]["document_b64"])
    text = unicodedata.normalize(
        "NFC", PdfReader(io.BytesIO(raw)).pages[0].extract_text()
    )
    request["expected_page_text_sha256"] = v.sha(text[:50000].encode())
    result = verify_source_bound_evidence(request)["semantic_result"]
    assert (
        result["overall_status"] == "review"
        and result["coverage"]["selected_unit_status"] == "incomplete"
    )
    request = request_for()
    request["checks"][0]["declared_value"] = "-0.00"
    with pytest.raises(v.Invalid, match="REQUEST_INVALID"):
        verify_source_bound_evidence(request)
