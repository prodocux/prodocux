from __future__ import annotations

import base64
import json
from copy import deepcopy
from importlib.resources import files

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from api.main import app
from prodocux_kernel.intake import (
    ProjectionValidationError,
    extract_csv_continuable_projection,
    validate_continuable_projection,
)


def _csv(rows: int, columns: int = 2) -> bytes:
    header = ",".join(f"column_{index}" for index in range(columns))
    body = [
        ",".join(
            [f"row-{row}"] + [f"value-{row}-{column}" for column in range(1, columns)]
        )
        for row in range(rows)
    ]
    return ("\n".join([header, *body]) + "\n").encode()


def _schema() -> dict:
    return json.loads(
        files("prodocux_kernel.schemas")
        .joinpath("prodocux_csv_continuable_projection_v1.json")
        .read_text(encoding="utf-8")
    )


def test_csv_506_rows_continue_as_500_plus_6_with_tail_marker() -> None:
    raw = _csv(506)
    first = extract_csv_continuable_projection(raw)
    second = extract_csv_continuable_projection(raw, cursor=first["next_cursor"])
    Draft202012Validator(_schema()).validate(first)
    Draft202012Validator(_schema()).validate(second)
    assert first["range"]["start"] == 0 and first["range"]["end"] == 500
    assert second["range"]["start"] == 500 and second["range"]["end"] == 506
    assert second["rows"][-1][0] == "row-505"
    assert first["coverage"]["disposition"] == "partial_known"
    assert second["coverage"]["disposition"] == "complete"


def test_csv_cursor_binding_and_column_omission_fail_safe() -> None:
    raw = _csv(2, columns=33)
    result = extract_csv_continuable_projection(raw, max_rows=1)
    assert result["coverage"]["disposition"] == "partial_unknown"
    assert result["coverage"]["omitted_content_classes"] == ["columns_beyond_limit"]
    changed = deepcopy(result["next_cursor"])
    changed["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source_sha256"):
        extract_csv_continuable_projection(raw, cursor=changed, max_rows=1)


def test_csv_continuation_http_and_capability_disclosure() -> None:
    client = TestClient(app)
    request = {
        "document_filename": "large.csv",
        "document_b64": base64.b64encode(_csv(506)).decode(),
        "max_rows": 500,
    }
    first = client.post("/v1/intake/profile-table/continue", json=request)
    assert first.status_code == 200
    request["cursor"] = first.json()["next_cursor"]
    assert (
        client.post("/v1/intake/profile-table/continue", json=request).json()["counts"][
            "returned_rows"
        ]
        == 6
    )
    profiles = {
        item["format"]: item
        for item in client.get("/v1/intake/projection-capabilities").json()["profiles"]
    }
    assert profiles["csv"]["range_units"] == ["row"]


def test_csv_semantics_reject_count_and_next_row_drift() -> None:
    result = extract_csv_continuable_projection(_csv(2), max_rows=1)
    invalid = deepcopy(result)
    invalid["counts"]["returned_rows"] = 2
    with pytest.raises(ProjectionValidationError, match="row count"):
        validate_continuable_projection(invalid)
    invalid = deepcopy(result)
    invalid["next_cursor"]["next_row"] = 2
    with pytest.raises(ProjectionValidationError, match="next row"):
        validate_continuable_projection(invalid)


def test_header_only_csv_has_valid_zero_row_terminal_range() -> None:
    result = extract_csv_continuable_projection(b"name,value\n")
    Draft202012Validator(_schema()).validate(result)
    assert result["range"]["start"] == result["range"]["end"] == 0
    assert result["rows"] == []
    assert result["coverage"]["disposition"] == "complete"
