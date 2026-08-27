"""Phase 1 Kernel intake materialize + artifact:// extract-blocks."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient


def test_materialize_then_extract_blocks_by_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("PRODOCUX_INTAKE_MOUNT", str(tmp_path / "intake"))
    monkeypatch.delenv("PRODOCUX_BEARER_TOKENS", raising=False)
    from api import main as main_mod
    from prodocux_kernel.rendering.intake_store import IntakeMaterialStore

    main_mod._INTAKE_STORE = IntakeMaterialStore(tmp_path / "intake")
    client = TestClient(main_mod.app)

    raw = b"id,label\n1,a\n"
    digest = hashlib.sha256(raw).hexdigest()
    materialized = client.post(
        "/v1/intake/materialize",
        json={
            "document_filename": "rows.csv",
            "document_b64": base64.b64encode(raw).decode("ascii"),
            "media_type": "text/csv",
            "sha256": digest,
        },
    )
    assert materialized.status_code == 200
    identity = materialized.json()
    assert identity["uri"].startswith("artifact://intake/")
    assert identity["artifact_id"] in identity["uri"]
    assert identity["sha256"] == digest

    # Same basename, different bytes → distinct URIs (no filename-only collision).
    other = client.post(
        "/v1/intake/materialize",
        json={
            "document_filename": "rows.csv",
            "document_b64": base64.b64encode(b"id,label\n2,b\n").decode("ascii"),
            "media_type": "text/csv",
        },
    )
    assert other.status_code == 200
    assert other.json()["uri"] != identity["uri"]
    assert other.json()["artifact_id"] in other.json()["uri"]

    extracted = client.post(
        "/v1/intake/extract-blocks",
        json={
            "document_filename": "rows.csv",
            "document_artifact": identity,
        },
    )
    assert extracted.status_code == 200
    body = extracted.json()
    assert "content" in body or "blocks" in body
    assert body.get("source_sha256") == digest


def test_store_derived_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PRODOCUX_DERIVED_MOUNT", str(tmp_path / "derived"))
    monkeypatch.delenv("PRODOCUX_BEARER_TOKENS", raising=False)
    from api import main as main_mod
    from prodocux_kernel.rendering.derived_store import DerivedArtifactStore

    main_mod._DERIVED_STORE = DerivedArtifactStore(tmp_path / "derived")
    client = TestClient(main_mod.app)
    raw = b'{"schema_version":"prodocux_content_blocks_v1","blocks":[]}'
    digest = hashlib.sha256(raw).hexdigest()
    response = client.post(
        "/v1/artifacts/derived",
        json={
            "output_name": "content_blocks.json",
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "media_type": "application/json",
            "sha256": digest,
        },
    )
    assert response.status_code == 200
    identity = response.json()
    assert identity["uri"].startswith("artifact://derived/")
    assert identity["artifact_id"] in identity["uri"]
    assert identity["sha256"] == digest


def test_extract_blocks_still_accepts_document_b64(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PRODOCUX_INTAKE_MOUNT", str(tmp_path / "intake"))
    monkeypatch.delenv("PRODOCUX_BEARER_TOKENS", raising=False)
    from api import main as main_mod
    from prodocux_kernel.rendering.intake_store import IntakeMaterialStore

    main_mod._INTAKE_STORE = IntakeMaterialStore(tmp_path / "intake")
    client = TestClient(main_mod.app)
    raw = b"id,label\n1,a\n"
    response = client.post(
        "/v1/intake/extract-blocks",
        json={
            "document_filename": "rows.csv",
            "document_b64": base64.b64encode(raw).decode("ascii"),
        },
    )
    assert response.status_code == 200
