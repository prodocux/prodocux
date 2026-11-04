"""Source-bound verification of exact spans on independently parsed PDF pages."""

from __future__ import annotations

import base64
import io
import unicodedata
from importlib.metadata import version

from pypdf import PdfReader

from prodocux_kernel import __version__

from .source_binding_contracts import validation as contract

ERROR_STATUS = {
    "REQUEST_INVALID": 400,
    "SOURCE_IDENTITY_MISMATCH": 409,
    "PARSER_CONTRACT_MISMATCH": 409,
    "PAGE_PROJECTION_MISMATCH": 409,
    "SOURCE_TOO_LARGE": 413,
    "REQUEST_TOO_LARGE": 413,
    "SOURCE_TYPE_UNSUPPORTED": 415,
    "SOURCE_UNREADABLE": 422,
    "SOURCE_ENCRYPTED": 422,
    "PAGE_UNAVAILABLE": 422,
    "PARSER_RESOURCE_LIMIT": 422,
    "VERIFIER_UNAVAILABLE": 503,
}
PARSER = {"name": "prodocux_pdf_page_projection_v1", "version": "1"}


def capabilities():
    schema = contract.SCHEMAS["urn:pdx:draft:cr003:support:2"]["$defs"]["capabilities"]
    limits = schema["properties"]["limits"]["properties"]
    return {
        "schema_version": schema["properties"]["schema_version"]["const"],
        "media_type": "application/pdf",
        "parser_contract": PARSER.copy(),
        "normalization": "unicode_nfc_preserve_whitespace_codepoint_v1",
        "conversion": "ascii_decimal_exact_scale_v1",
        "locator": "page_exact_codepoint_range",
        "ocr_supported": False,
        "search_selector_supported": False,
        "limits": {k: v["const"] for k, v in limits.items()},
    }


def verify_source_bound_evidence(request):
    """No caller-supplied parser context, text or projection is accepted."""
    if isinstance(request, dict) and isinstance(request.get("source"), dict):
        if request["source"].get("media_type") not in (None, "application/pdf"):
            raise contract.Invalid("SOURCE_TYPE_UNSUPPORTED")
        encoded = request["source"].get("document_b64")
        if isinstance(encoded, str) and len(encoded) > 13_981_016:
            raise contract.Invalid("SOURCE_TOO_LARGE")
    contract.shape("urn:pdx:draft:cr003:core:1#/$defs/request", request)
    try:
        raw = base64.b64decode(request["source"]["document_b64"], validate=True)
    except ValueError as exc:
        raise contract.Invalid("REQUEST_INVALID") from exc
    contract.require(
        base64.b64encode(raw).decode() == request["source"]["document_b64"],
        "REQUEST_INVALID",
    )
    contract.require(len(raw) <= 10485760, "SOURCE_TOO_LARGE")
    contract.require(
        len(raw) == request["source"]["size_bytes"]
        and contract.sha(raw) == request["source"]["sha256"],
        "SOURCE_IDENTITY_MISMATCH",
    )
    contract.require(request["parser_contract"] == PARSER, "PARSER_CONTRACT_MISMATCH")
    try:
        reader = PdfReader(io.BytesIO(raw))
        contract.require(not reader.is_encrypted, "SOURCE_ENCRYPTED")
        total = len(reader.pages)
        number = request["page_number"]
        contract.require(number <= total, "PAGE_UNAVAILABLE")
        # Use the same native-text parser and short-text OCR disclosure as intake.
        text = reader.pages[number - 1].extract_text() or ""
    except contract.Invalid:
        raise
    except Exception as exc:
        raise contract.Invalid("SOURCE_UNREADABLE") from exc
    text = unicodedata.normalize("NFC", text)
    contract.ijson(text)
    quality = (
        "incomplete"
        if len(text) > 50000
        else "ocr_required"
        if len(text.strip()) < 20
        else "complete_native_text"
    )
    if quality == "incomplete":
        text = text[:50000]
    context = {
        "source_sha256": contract.sha(raw),
        "parser_contract": PARSER,
        "total_pages": total,
        "page_number": number,
        "text": text,
        "quality": quality,
    }
    result = contract.kernel_result(request, context)
    material = {k: v for k, v in request.items() if k != "request_id"}
    material["source"] = {
        k: v for k, v in request["source"].items() if k != "document_b64"
    }
    report = {
        "schema_version": "prodocux_source_binding_report_draft_v1",
        "request_id": request["request_id"],
        "semantic_request_digest": contract.digest(material),
        "semantic_result": result,
        "semantic_result_digest": contract.digest(result),
        "producer": {
            "kernel_version": __version__,
            "parser_backend": "pypdf",
            "parser_backend_version": version("pypdf"),
        },
    }
    contract.kernel_report(report, request, context)
    return report
