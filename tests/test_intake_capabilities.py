from __future__ import annotations

import json
from importlib.resources import files

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from api.main import app
from prodocux_kernel.intake import (
    MAX_DOCX_BYTES,
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    MAX_PRESENTATION_BYTES,
    MAX_TABLE_BYTES,
    MAX_WORKBOOK_BYTES,
)


def _payload() -> dict:
    response = TestClient(app).get("/v1/intake/capabilities")
    assert response.status_code == 200
    return response.json()


def test_capabilities_match_kernel_limits() -> None:
    payload = _payload()
    formats = {
        extension: item
        for item in payload["formats"]
        for extension in item["extensions"]
    }
    assert payload["schema_version"] == "prodocux_intake_capabilities_v1"
    assert formats[".pdf"]["max_bytes"] == MAX_PDF_BYTES
    assert formats[".pdf"]["max_pages"] == MAX_PDF_PAGES
    assert formats[".docx"]["max_bytes"] == MAX_DOCX_BYTES
    assert formats[".csv"]["max_bytes"] == MAX_TABLE_BYTES
    assert formats[".xlsx"]["max_bytes"] == MAX_WORKBOOK_BYTES
    assert formats[".pptx"]["max_bytes"] == MAX_PRESENTATION_BYTES
    assert "max_bytes" not in formats[".r3d"]


def test_capabilities_response_matches_packaged_schema() -> None:
    schema_text = (
        files("prodocux_kernel.schemas")
        .joinpath("prodocux_intake_capabilities_v1.json")
        .read_text(encoding="utf-8")
    )
    schema = json.loads(schema_text)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_payload())


def test_projection_capabilities_disclose_all_current_hard_boundaries() -> None:
    response = TestClient(app).get("/v1/intake/projection-capabilities")
    assert response.status_code == 200
    payload = response.json()
    schema = json.loads(
        files("prodocux_kernel.schemas")
        .joinpath("prodocux_projection_capabilities_v1.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    profiles = {item["format"]: item for item in payload["profiles"]}
    assert set(profiles) == {"docx", "pdf", "csv", "xlsx", "pptx", "image"}
    assert profiles["docx"]["range_units"] == ["block"]
    assert profiles["docx"]["known_uncontinuable_limits"]
    assert all(
        not item["source_admission"]["artifact_backed_source"]
        for item in profiles.values()
    )
    assert all(
        item["source_admission"]["oversized_source_disposition"] == "SOURCE_TOO_LARGE"
        for item in profiles.values()
    )
    assert all(item["source_admission"]["inline_source"] for item in profiles.values())
    assert all(not item["source_admission"]["spooled_source"] for item in profiles.values())
    assert all(
        item["status"] == "bounded_without_continuation"
        for name, item in profiles.items()
        if name not in {"docx", "pdf", "csv", "xlsx", "pptx", "image"}
    )
    assert profiles["pdf"]["range_units"] == ["page"]
    assert profiles["pdf"]["endpoint"] == "/v1/intake/extract-pages/continue"
    assert profiles["csv"]["endpoint"] == "/v1/intake/profile-table/continue"
    assert profiles["xlsx"]["endpoint"] == "/v1/intake/profile-workbook/continue"
    assert profiles["pptx"]["endpoint"] == "/v1/intake/profile-presentation/continue"
    assert profiles["image"]["endpoint"] == "/v1/intake/profile-image/tiles"
