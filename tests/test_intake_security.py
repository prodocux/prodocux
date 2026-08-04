from __future__ import annotations

import base64
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.path_policy import resolve_allowed_input_path
from prodocux_kernel.intake.archive import validate_office_archive


def _zip_bytes(name: str, content: bytes) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def test_document_path_is_disabled_without_allow_roots(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "private.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    monkeypatch.delenv("PRODOCUX_ALLOWED_INPUT_ROOTS", raising=False)
    response = TestClient(app).post(
        "/v1/intake/profile-table", json={"document_path": str(source)}
    )
    assert response.status_code == 400
    assert "disabled" in response.json()["detail"]


def test_document_path_must_remain_under_allow_root(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside.csv"
    allowed.mkdir()
    outside.write_text("a\n1\n", encoding="utf-8")
    monkeypatch.setenv("PRODOCUX_ALLOWED_INPUT_ROOTS", str(allowed))
    with pytest.raises(ValueError, match="outside"):
        resolve_allowed_input_path(str(outside), suffix=".csv")


def test_document_path_under_allow_root_is_accepted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "input.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    monkeypatch.setenv("PRODOCUX_ALLOWED_INPUT_ROOTS", str(allowed))
    assert resolve_allowed_input_path(str(source), suffix=".csv") == source.resolve()


def test_office_archive_rejects_unsafe_member_name() -> None:
    with pytest.raises(ValueError, match="unsafe member"):
        validate_office_archive(_zip_bytes("../escape.xml", b"x"), label="DOCX")


@pytest.mark.parametrize(
    "member_name",
    [
        "C:/Windows/evil.xml",
        "C:\\Windows\\evil.xml",
        "\\\\server\\share\\evil.xml",
    ],
)
def test_office_archive_rejects_windows_absolute_member(member_name: str) -> None:
    with pytest.raises(ValueError, match="unsafe member"):
        validate_office_archive(_zip_bytes(member_name, b"x"), label="DOCX")


def test_office_archive_rejects_extreme_compression_ratio() -> None:
    raw = _zip_bytes("word/document.xml", b"0" * (2 * 1024 * 1024))
    with pytest.raises(ValueError, match="compression ratio"):
        validate_office_archive(raw, label="DOCX")


def test_archive_failure_is_bounded_at_http_surface() -> None:
    raw = _zip_bytes("../escape.xml", b"x")
    response = TestClient(app).post(
        "/v1/intake/profile-document",
        json={
            "document_b64": base64.b64encode(raw).decode("ascii"),
            "document_filename": "unsafe.docx",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "DOCX archive contains an unsafe member name"
