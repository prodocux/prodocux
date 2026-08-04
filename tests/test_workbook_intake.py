from __future__ import annotations

import base64
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from api.main import app
from prodocux_kernel.intake import WORKBOOK_PROFILE_SCHEMA, profile_xlsx_bytes


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Unit A"
    sheet.append(["date", "unit", "hours"])
    sheet.append(["2026-08-02", "A", 10])
    sheet.append(["2026-08-03", "A", 12])
    sheet["D1"] = "total"
    sheet["D2"] = "=SUM(C2:C3)"
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def test_profile_xlsx_preserves_sheet_and_formula_evidence() -> None:
    profile = profile_xlsx_bytes(_workbook_bytes(), filename="schedule.xlsx")
    assert profile["schema_version"] == WORKBOOK_PROFILE_SCHEMA
    assert profile["sheet_count"] == 1
    assert profile["interpretation"] == "none"
    sheet = profile["sheets"][0]
    assert sheet["name"] == "Unit A"
    assert sheet["formula_cells"][0]["cell"] == "D2"
    assert sheet["formula_cells"][0]["formula"] == "=SUM(C2:C3)"
    assert len(profile["source"]["sha256"]) == 64


def test_profile_workbook_api_accepts_small_base64() -> None:
    response = TestClient(app).post(
        "/v1/intake/profile-workbook",
        json={
            "document_b64": base64.b64encode(_workbook_bytes()).decode("ascii"),
            "document_filename": "schedule.xlsx",
        },
    )
    assert response.status_code == 200
    assert response.json()["profile"]["sheets"][0]["name"] == "Unit A"


def test_legacy_xls_is_not_claimed_as_xlsx() -> None:
    payload = TestClient(app).get("/v1/intake/capabilities").json()
    formats = {
        ext: item for item in payload["formats"] for ext in item["extensions"]
    }
    assert formats[".xlsx"]["status"] == "available"
    assert formats[".xls"]["status"] == "planned"


def test_invalid_xlsx_returns_bounded_client_error() -> None:
    response = TestClient(app).post(
        "/v1/intake/profile-workbook",
        json={
            "document_b64": base64.b64encode(b"not-a-workbook").decode("ascii"),
            "document_filename": "broken.xlsx",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid XLSX workbook"
