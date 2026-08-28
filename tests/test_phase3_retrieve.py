"""Phase 3 Kernel verified opaque artifact retrieval."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient


def test_retrieve_intake_materialized_bytes(tmp_path: Path, monkeypatch) -> None:
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
    identity = materialized.json()

    retrieved = client.post(
        "/v1/artifacts/retrieve",
        json={
            "schema_version": "prodocux_artifact_retrieve_v1",
            "request_id": "req-retrieve-1",
            "artifact": identity,
        },
    )
    assert retrieved.status_code == 200
    body = retrieved.json()
    assert body["schema_version"] == "prodocux_artifact_content_v1"
    assert body["artifact"] == identity
    assert body["sha256"] == digest
    assert body["size_bytes"] == len(raw)
    assert base64.b64decode(body["content_b64"]) == raw


def test_retrieve_derived_artifact_bytes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PRODOCUX_DERIVED_MOUNT", str(tmp_path / "derived"))
    monkeypatch.delenv("PRODOCUX_BEARER_TOKENS", raising=False)
    from api import main as main_mod
    from prodocux_kernel.rendering.derived_store import DerivedArtifactStore

    main_mod._DERIVED_STORE = DerivedArtifactStore(tmp_path / "derived")
    client = TestClient(main_mod.app)
    raw = b'{"schema_version":"prodocux_content_blocks_v1","blocks":[]}'
    digest = hashlib.sha256(raw).hexdigest()
    stored = client.post(
        "/v1/artifacts/derived",
        json={
            "output_name": "content_blocks.json",
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "media_type": "application/json",
            "sha256": digest,
        },
    )
    identity = stored.json()

    retrieved = client.post(
        "/v1/artifacts/retrieve",
        json={
            "schema_version": "prodocux_artifact_retrieve_v1",
            "request_id": "req-retrieve-2",
            "artifact": identity,
        },
    )
    assert retrieved.status_code == 200
    body = retrieved.json()
    assert base64.b64decode(body["content_b64"]) == raw


def test_retrieve_rejects_digest_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PRODOCUX_DERIVED_MOUNT", str(tmp_path / "derived"))
    monkeypatch.delenv("PRODOCUX_BEARER_TOKENS", raising=False)
    from api import main as main_mod
    from prodocux_kernel.rendering.derived_store import DerivedArtifactStore

    main_mod._DERIVED_STORE = DerivedArtifactStore(tmp_path / "derived")
    client = TestClient(main_mod.app)
    raw = b"payload"
    stored = client.post(
        "/v1/artifacts/derived",
        json={
            "output_name": "payload.bin",
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "media_type": "application/octet-stream",
        },
    )
    identity = stored.json()
    bad = dict(identity)
    bad["sha256"] = "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"

    retrieved = client.post(
        "/v1/artifacts/retrieve",
        json={
            "schema_version": "prodocux_artifact_retrieve_v1",
            "request_id": "req-retrieve-3",
            "artifact": bad,
        },
    )
    assert retrieved.status_code == 404
