from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from prodocux_kernel.verification import (
    EvidenceValidationError,
    verify_evidence_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "contracts" / "evidence_bundle_request_v1.json"


def _request() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _add_evidence(request: dict, *, evidence_id: str, field_name: str, value_type: str, value, confidence: float = 0.99) -> None:
    source = copy.deepcopy(request["evidence"][0]["source_reference"])
    request["evidence"].append(
        {
            "evidence_id": evidence_id,
            "document_id": "document-a",
            "field_name": field_name,
            "value_type": value_type,
            "value": value,
            "confidence": confidence,
            "source_reference": source,
        }
    )


def test_numeric_range_result_is_deterministic() -> None:
    first = verify_evidence_bundle(_request())
    second = verify_evidence_bundle(_request())
    assert first == second
    assert first["status"] == "pass"
    assert first["results"][0]["reason_codes"] == ["VALUE_WITHIN_RANGE"]


def test_equality_mismatch_fails() -> None:
    request = _request()
    _add_evidence(
        request,
        evidence_id="ev-volume-copy",
        field_name="declared_volume_copy_ml",
        value_type="number",
        value=55,
    )
    request["checks"] = [
        {
            "check_id": "volume-equality",
            "kind": "equality",
            "evidence_ids": ["ev-volume", "ev-volume-copy"],
        }
    ]
    result = verify_evidence_bundle(request)
    assert result["status"] == "fail"
    assert result["results"][0]["reason_codes"] == ["VALUE_MISMATCH"]


def test_low_confidence_pass_becomes_review() -> None:
    request = _request()
    request["evidence"][0]["confidence"] = 0.5
    result = verify_evidence_bundle(request)
    assert result["status"] == "review"
    assert "CONFIDENCE_BELOW_MINIMUM" in result["results"][0]["reason_codes"]


def test_presence_date_and_version_checks() -> None:
    request = _request()
    request["evidence"][0].update(
        {"field_name": "effective_from", "value_type": "date", "value": "2026-01-01"}
    )
    _add_evidence(
        request,
        evidence_id="ev-date-to",
        field_name="effective_to",
        value_type="date",
        value="2026-12-31",
    )
    _add_evidence(
        request,
        evidence_id="ev-version-a",
        field_name="version_a",
        value_type="version",
        value="2.1",
    )
    _add_evidence(
        request,
        evidence_id="ev-version-b",
        field_name="version_b",
        value_type="version",
        value="2.1",
    )
    request["checks"] = [
        {"check_id": "present", "kind": "presence", "evidence_ids": ["ev-version-a"]},
        {
            "check_id": "dates",
            "kind": "date_order",
            "evidence_ids": ["ev-volume", "ev-date-to"],
        },
        {
            "check_id": "versions",
            "kind": "version_match",
            "evidence_ids": ["ev-version-a", "ev-version-b"],
        },
    ]
    result = verify_evidence_bundle(request)
    assert result["status"] == "pass"
    assert [item["status"] for item in result["results"]] == ["pass", "pass", "pass"]


def test_unknown_evidence_and_source_digest_mismatch_fail_closed() -> None:
    request = _request()
    request["checks"][0]["evidence_ids"] = ["unknown"]
    with pytest.raises(EvidenceValidationError, match="unknown evidence"):
        verify_evidence_bundle(request)

    request = _request()
    request["evidence"][0]["source_reference"]["source_sha256"] = "d" * 64
    with pytest.raises(EvidenceValidationError, match="source digest mismatch"):
        verify_evidence_bundle(request)


def test_http_endpoint_returns_schema_shaped_result() -> None:
    response = TestClient(app).post("/v1/verify/evidence-bundle", json=_request())
    assert response.status_code == 200
    assert response.json()["schema_version"] == "prodocux_evidence_bundle_result_v1"
    assert response.json()["status"] == "pass"


def test_http_endpoint_rejects_semantic_mismatch() -> None:
    request = _request()
    request["evidence"][0]["document_id"] = "unknown"
    response = TestClient(app).post("/v1/verify/evidence-bundle", json=request)
    assert response.status_code == 400
    assert "unknown document" in response.json()["detail"]
