from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from api.main import app
from prodocux_kernel.intake import TABLE_PROFILE_SCHEMA, profile_csv_bytes


def test_profile_csv_bytes_is_deterministic() -> None:
    raw = b"date,unit,call_time\n2026-08-02,A,06:30\n"
    first = profile_csv_bytes(raw, filename="schedule.csv")
    second = profile_csv_bytes(raw, filename="schedule.csv")
    assert first == second
    assert first["schema_version"] == TABLE_PROFILE_SCHEMA
    assert first["row_count"] == 1
    assert first["interpretation"] == "none"
    assert len(first["source"]["sha256"]) == 64


def test_profile_table_api_accepts_small_base64() -> None:
    raw = b"date,unit\n2026-08-02,A\n"
    response = TestClient(app).post(
        "/v1/intake/profile-table",
        json={
            "document_b64": base64.b64encode(raw).decode("ascii"),
            "document_filename": "schedule.csv",
        },
    )
    assert response.status_code == 200
    assert response.json()["profile"]["columns"] == ["date", "unit"]


def test_intake_capabilities_are_truthful() -> None:
    payload = TestClient(app).get("/v1/intake/capabilities").json()
    formats = {
        ext: item for item in payload["formats"] for ext in item["extensions"]
    }
    assert formats[".csv"]["status"] == "available"
    assert formats[".pptx"]["status"] == "available"
    assert formats[".r3d"]["status"] == "external_pipeline_required"
