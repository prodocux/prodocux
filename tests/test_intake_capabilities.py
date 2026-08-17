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
