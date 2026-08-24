from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from prodocux_kernel.rendering import (
    InMemoryArtifactSink,
    ManualCancellation,
    capabilities_document,
    deliver_output,
    execute_render_artifact,
    validate_content_blocks,
    validate_render_request,
)
from prodocux_kernel.rendering.errors import (
    ARTIFACT_CREATE_CONFLICT,
    ARTIFACT_SINK_UNAVAILABLE,
    INLINE_OUTPUT_TOO_LARGE,
    OUTPUT_NAME_INVALID,
    RENDERER_NOT_AVAILABLE,
    TEMPLATE_IDENTITY_INVALID,
    TEMPLATE_MAGIC_MISMATCH,
    TEMPLATE_NOT_SUPPORTED,
    RenderContractError,
)
from prodocux_kernel.rendering.media import assert_magic_matches_format

ROOT = Path(__file__).resolve().parents[1]
G1A = ROOT / "examples" / "contracts" / "g1a"


def _load(name: str) -> dict:
    return json.loads((G1A / name).read_text(encoding="utf-8"))


def _office_zip(marker_dir: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(f"{marker_dir}/document.xml", "<root/>")
    return buffer.getvalue()


def test_content_blocks_minimal_fixture_validates() -> None:
    validate_content_blocks(_load("content_blocks.minimal.json"))


PRODOCUX_COMMIT_A = "fa35cb05b9c4926ecd3b56dc705a1ecacc55ac30"


def test_g1a_provenance_is_frozen_to_commit_a() -> None:
    schema = ROOT / "prodocux_kernel" / "schemas" / "prodocux_content_blocks_v1.json"
    digest = hashlib.sha256(schema.read_bytes()).hexdigest()
    provenance = _load("content_blocks.minimal.provenance.json")
    assert provenance["status"] == "frozen"
    assert provenance["synthetic"] is True
    assert provenance["source_commit"] == PRODOCUX_COMMIT_A
    if "schema_digest" in provenance:
        assert provenance["schema_digest"] == digest


def test_valid_artifact_docx_request_renders_with_sink() -> None:
    request = _load("render_request.artifact.docx.json")
    validate_render_request(request)
    sink = InMemoryArtifactSink()
    status, body = execute_render_artifact(request, sink=sink)
    assert status == 200
    assert body["status"] == "completed"
    assert body["error"]["code"] != RENDERER_NOT_AVAILABLE if "error" in body else True
    assert "artifact" in body
    assert "content_b64" not in body
    assert len(body["output_sha256"]) == 64


def test_inline_csv_request_is_schema_valid() -> None:
    validate_render_request(_load("render_request.inline.csv.json"))


def test_rejects_gs_and_signed_template_locations() -> None:
    with pytest.raises(RenderContractError) as gs_exc:
        validate_render_request(_load("render_request.reject.gs.json"))
    assert gs_exc.value.code == TEMPLATE_IDENTITY_INVALID
    with pytest.raises(RenderContractError) as signed_exc:
        validate_render_request(_load("render_request.reject.signed_url.json"))
    assert signed_exc.value.code == TEMPLATE_IDENTITY_INVALID


def test_output_name_must_be_basename_with_matching_suffix() -> None:
    request = _load("render_request.inline.csv.json")
    request["output"]["output_name"] = "../secret.csv"
    with pytest.raises(RenderContractError) as exc:
        validate_render_request(request)
    assert exc.value.code == OUTPUT_NAME_INVALID


def test_capabilities_mark_all_formats_available_without_template() -> None:
    document = capabilities_document()
    assert {item["format"] for item in document["formats"]} == {
        "docx",
        "xlsx",
        "csv",
        "pptx",
        "pdf",
    }
    assert {item["status"] for item in document["formats"]} == {"available"}
    docx = next(item for item in document["formats"] if item["format"] == "docx")
    assert docx["requires_template"] is False
    assert docx["max_inline_output_bytes"] == 2 * 1024 * 1024


def test_magic_accepts_pdf_zip_office_and_csv_and_rejects_mismatches() -> None:
    assert_magic_matches_format(b"%PDF-1.4\n", "pdf")
    assert_magic_matches_format(_office_zip("word"), "docx")
    assert_magic_matches_format(_office_zip("xl"), "xlsx")
    assert_magic_matches_format(_office_zip("ppt"), "pptx")
    assert_magic_matches_format("id,label\n1,a\n".encode("utf-8"), "csv")
    with pytest.raises(RenderContractError) as exc:
        assert_magic_matches_format(_office_zip("xl"), "docx")
    assert exc.value.code == TEMPLATE_MAGIC_MISMATCH
    with pytest.raises(RenderContractError):
        assert_magic_matches_format(b"%PDF-1.4\n", "csv")


def test_sink_create_if_absent_same_digest_noop_and_conflict() -> None:
    sink = InMemoryArtifactSink()
    payload = b"rendered-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    first = sink.create_if_absent(
        output_name="summary.pdf",
        media_type="application/pdf",
        payload=payload,
        sha256=digest,
    )
    second = sink.create_if_absent(
        output_name="summary.pdf",
        media_type="application/pdf",
        payload=payload,
        sha256=digest,
    )
    assert first == second
    assert str(first["uri"]).startswith("artifact://")
    with pytest.raises(RenderContractError) as exc:
        sink.create_if_absent(
            output_name="summary.pdf",
            media_type="application/pdf",
            payload=b"other-bytes",
            sha256=hashlib.sha256(b"other-bytes").hexdigest(),
        )
    assert exc.value.code == ARTIFACT_CREATE_CONFLICT


def test_inline_ceiling_and_cancel_before_sink() -> None:
    huge = b"a" * (2 * 1024 * 1024 + 1)
    with pytest.raises(RenderContractError) as too_large:
        deliver_output(
            payload=huge,
            media_type="text/csv",
            output_name="records.csv",
            delivery_mode="inline",
            sink=None,
        )
    assert too_large.value.code == INLINE_OUTPUT_TOO_LARGE

    sink = InMemoryArtifactSink()
    cancel = ManualCancellation(cancelled=True)
    with pytest.raises(RenderContractError) as cancelled:
        deliver_output(
            payload=b"ok",
            media_type="application/pdf",
            output_name="summary.pdf",
            delivery_mode="artifact",
            sink=sink,
            cancellation=cancel,
        )
    assert cancelled.value.code == "CANCELLED"
    assert "summary.pdf" not in sink._store


def test_http_routes_capabilities_validate_and_live_render() -> None:
    client = TestClient(app)
    caps = client.get("/v1/render/capabilities")
    assert caps.status_code == 200
    assert caps.json()["schema_version"] == "prodocux_render_capabilities_v1"
    assert {item["status"] for item in caps.json()["formats"]} == {"available"}

    valid_blocks = client.post(
        "/v1/content-blocks/validate", json=_load("content_blocks.minimal.json")
    )
    assert valid_blocks.status_code == 200
    assert valid_blocks.json()["valid"] is True

    rendered = client.post(
        "/v1/render/artifact", json=_load("render_request.artifact.docx.json")
    )
    assert rendered.status_code == 200
    assert rendered.json()["status"] == "completed"
    assert rendered.json()["artifact"]["uri"].startswith("artifact://")

    live_alias = client.post("/v1/render", json=_load("render_request.inline.csv.json"))
    assert live_alias.status_code == 200
    assert live_alias.json()["status"] == "completed"
    assert live_alias.json()["content_b64"]

    stale = client.post("/v1/render", json={"template_path": "C:/secret.docx"})
    assert stale.status_code == 501


def test_template_field_is_rejected_this_release() -> None:
    request = _load("render_request.artifact.docx.json")
    request = dict(request)
    request["template"] = {
        "artifact": {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": "tpl-synthetic-docx",
            "uri": "artifact://g1a/templates/summary.docx",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "size_bytes": 0,
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
    }
    with pytest.raises(RenderContractError) as exc:
        validate_render_request(request)
    assert exc.value.code == TEMPLATE_NOT_SUPPORTED


def test_artifact_delivery_without_sink_fails_closed() -> None:
    request = _load("render_request.artifact.docx.json")
    status, body = execute_render_artifact(request, sink=None)
    assert status == 503
    assert body["error"]["code"] == ARTIFACT_SINK_UNAVAILABLE


def _artifact_csv_request(output_name: str) -> dict:
    request = json.loads(json.dumps(_load("render_request.inline.csv.json")))
    request["output"]["delivery_mode"] = "artifact"
    request["output"]["output_name"] = output_name
    return request


def test_http_artifact_bytes_are_retrievable_by_identity() -> None:
    client = TestClient(app)
    rendered = client.post(
        "/v1/render/artifact", json=_artifact_csv_request("retrievable.csv")
    )
    assert rendered.status_code == 200
    body = rendered.json()
    assert body["status"] == "completed"
    identity = body["artifact"]
    artifact_id = identity["artifact_id"]
    fetched = client.get(f"/v1/render/artifacts/{artifact_id}")
    assert fetched.status_code == 200
    digest = hashlib.sha256(fetched.content).hexdigest()
    assert digest == body["output_sha256"]
    assert digest == identity["sha256"]
    assert fetched.headers["x-prodocux-sha256"] == digest
    assert fetched.headers["x-prodocux-artifact-uri"] == identity["uri"]


def test_http_sink_keeps_identity_after_later_requests() -> None:
    client = TestClient(app)
    first = client.post(
        "/v1/render/artifact", json=_artifact_csv_request("keep-first.csv")
    )
    assert first.status_code == 200
    later = client.post(
        "/v1/render/artifact", json=_artifact_csv_request("keep-later.csv")
    )
    assert later.status_code == 200
    first_id = first.json()["artifact"]["artifact_id"]
    fetched = client.get(f"/v1/render/artifacts/{first_id}")
    assert fetched.status_code == 200
    assert hashlib.sha256(fetched.content).hexdigest() == first.json()["output_sha256"]
