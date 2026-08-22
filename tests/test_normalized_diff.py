from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from api.main import app
from prodocux_kernel.verification import (
    NormalizedDiffError,
    compare_normalized_profiles,
)

ROOT = Path(__file__).resolve().parents[1]


def _request() -> dict:
    return json.loads(
        (ROOT / "examples/contracts/normalized_diff_request_v1.json").read_text(
            encoding="utf-8"
        )
    )


def _locator(source_sha256: str) -> dict:
    return {
        "schema_version": "prodocux_source_reference_v1",
        "source_sha256": source_sha256,
        "media_type": "application/pdf",
        "locator": {"kind": "pdf_page", "page": 1},
        "snippet": "size",
        "extraction": {
            "method": "native_text",
            "extractor_id": "fixture",
            "extractor_version": "1",
        },
        "truncated": False,
    }


def test_diff_is_deterministic_typed_and_source_linked() -> None:
    request = _request()
    request["before"]["locators"] = {"/size": _locator("a" * 64)}
    request["after"]["locators"] = {"/size": _locator("b" * 64)}
    first = compare_normalized_profiles(request)
    second = compare_normalized_profiles(copy.deepcopy(request))
    assert first == second
    assert first["status"] == "changed"
    assert first["changes"] == [
        {
            "path": "/size",
            "kind": "changed",
            "reason_code": "VALUE_CHANGED",
            "before_value": 50,
            "after_value": 60,
            "before_locator": request["before"]["locators"]["/size"],
            "after_locator": request["after"]["locators"]["/size"],
        }
    ]


def test_normalization_added_removed_and_type_changes() -> None:
    request = _request()
    request["string_normalization"] = "collapse_whitespace"
    request["before"]["values"] = {"text": "  Alpha   Beta ", "old": True, "typed": 1}
    request["after"]["values"] = {"text": "Alpha Beta", "new": False, "typed": "1"}
    result = compare_normalized_profiles(request)
    assert [(item["path"], item["kind"]) for item in result["changes"]] == [
        ("/new", "added"),
        ("/old", "removed"),
        ("/typed", "type_changed"),
    ]

    request["before"]["values"] = {"nullable": None}
    request["after"]["values"] = {"nullable": "value"}
    nullable = compare_normalized_profiles(request)["changes"][0]
    assert "before_value" in nullable and nullable["before_value"] is None


def test_diff_bounds_truncation_and_locator_drift_fail_closed() -> None:
    request = _request()
    request["max_changes"] = 1
    request["before"]["values"] = {"a": 1, "b": 2}
    request["after"]["values"] = {"a": 3, "b": 4}
    result = compare_normalized_profiles(request)
    assert result["total_changes"] == 2
    assert len(result["changes"]) == 1
    assert result["truncated"] is True

    request = _request()
    request["before"]["locators"] = {"/size": _locator("b" * 64)}
    with pytest.raises(NormalizedDiffError, match="digest"):
        compare_normalized_profiles(request)


def test_keyed_table_rows_ignore_order_and_report_stable_logical_paths() -> None:
    request = _request()
    request["array_key_fields"] = {"/rows": "id"}
    request["before"]["values"] = {
        "rows": [{"id": "A", "value": 1}, {"id": "B", "value": 2}]
    }
    request["after"]["values"] = {
        "rows": [{"id": "B", "value": 3}, {"id": "A", "value": 1}]
    }
    result = compare_normalized_profiles(request)
    assert [(item["path"], item["reason_code"]) for item in result["changes"]] == [
        ("/rows/@B/value", "VALUE_CHANGED")
    ]

    request["after"]["values"]["rows"].append({"id": "B", "value": 4})
    with pytest.raises(NormalizedDiffError, match="duplicate key"):
        compare_normalized_profiles(request)

    request = _request()
    request["before"]["values"] = {"too_long": "x" * 4097}
    with pytest.raises(NormalizedDiffError, match="string"):
        compare_normalized_profiles(request)


def test_diff_api_and_contract_examples() -> None:
    response = TestClient(app).post("/v1/compare/normalized-profiles", json=_request())
    assert response.status_code == 200
    result = response.json()
    assert result["changes"][0]["path"] == "/size"

    source_schema = json.loads(
        (ROOT / "prodocux_kernel/schemas/prodocux_source_reference_v1.json").read_text(
            encoding="utf-8"
        )
    )
    registry = Registry().with_resource(
        source_schema["$id"], Resource.from_contents(source_schema)
    )
    for filename, value in (
        ("prodocux_normalized_diff_request_v1.json", _request()),
        ("prodocux_normalized_diff_result_v1.json", result),
    ):
        schema = json.loads(
            (ROOT / "prodocux_kernel/schemas" / filename).read_text(encoding="utf-8")
        )
        Draft202012Validator(schema, registry=registry).validate(value)
    assert result == json.loads(
        (ROOT / "examples/contracts/normalized_diff_result_v1.json").read_text(
            encoding="utf-8"
        )
    )


def test_diff_api_rejects_unknown_fields() -> None:
    request = _request()
    request["business_impact"] = "publish"
    response = TestClient(app).post("/v1/compare/normalized-profiles", json=request)
    assert response.status_code == 422
