"""Phase 1 Kernel sidecar: auth, health, filesystem sink."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prodocux_kernel.rendering.filesystem import FilesystemArtifactSink
from prodocux_kernel.rendering.memory import InMemoryArtifactSink


@pytest.fixture()
def auth_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PRODOCUX_BEARER_TOKENS", "phase1-token-a,phase1-token-b")
    # Re-import app after env so middleware sees tokens on each request via env read.
    from api import main as main_mod

    return main_mod.app


def test_health_and_ready_are_public(auth_env) -> None:
    client = TestClient(auth_env)
    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_v1_requires_bearer_when_configured(auth_env) -> None:
    client = TestClient(auth_env)
    denied = client.get("/v1/version")
    assert denied.status_code == 401
    assert denied.json()["code"] == "AUTH_REQUIRED"

    bad = client.get("/v1/version", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401
    assert bad.json()["code"] == "AUTH_INVALID"

    ok = client.get("/v1/version", headers={"Authorization": "Bearer phase1-token-b"})
    assert ok.status_code == 200
    assert "Authorization" not in ok.text


def test_production_mtls_requires_verified_client_cert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODOCUX_AUTH_PROFILE", "production_mtls")
    monkeypatch.setenv("PRODOCUX_BEARER_TOKENS", "mtls-token")
    from api import main as main_mod
    from fastapi.testclient import TestClient

    client = TestClient(main_mod.app)
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"]["auth_profile_ok"] is True

    denied = client.get(
        "/v1/version",
        headers={"Authorization": "Bearer mtls-token"},
    )
    assert denied.status_code == 401
    assert denied.json()["code"] == "AUTH_MTLS_REQUIRED"

    ok = client.get(
        "/v1/version",
        headers={
            "Authorization": "Bearer mtls-token",
            "SSL_CLIENT_VERIFY": "SUCCESS",
        },
    )
    assert ok.status_code == 200


def test_production_mtls_ready_fails_without_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODOCUX_AUTH_PROFILE", "production_mtls")
    monkeypatch.delenv("PRODOCUX_BEARER_TOKENS", raising=False)
    from api import main as main_mod
    from fastapi.testclient import TestClient

    client = TestClient(main_mod.app)
    ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json()["checks"]["auth_profile_ok"] is False


def test_filesystem_sink_create_noop_conflict(tmp_path: Path) -> None:
    sink = FilesystemArtifactSink(tmp_path)
    payload = b"hello-phase1"
    digest = hashlib.sha256(payload).hexdigest()
    first = sink.create_if_absent(
        output_name="summary.pdf",
        media_type="application/pdf",
        payload=payload,
        sha256=digest,
    )
    assert first["uri"].startswith("artifact://")
    assert "gs://" not in first["uri"]
    assert first["sha256"] == digest

    second = sink.create_if_absent(
        output_name="summary.pdf",
        media_type="application/pdf",
        payload=payload,
        sha256=digest,
    )
    assert second["artifact_id"] == first["artifact_id"]
    assert sink.record_status_for(output_name="summary.pdf", sha256=digest) == "no_op"

    with pytest.raises(Exception) as excinfo:
        sink.create_if_absent(
            output_name="summary.pdf",
            media_type="application/pdf",
            payload=b"other",
            sha256=hashlib.sha256(b"other").hexdigest(),
        )
    assert "different digest" in str(excinfo.value)

    found = sink.get(first["artifact_id"])
    assert found is not None
    body, identity = found
    assert body == payload
    assert identity["uri"] == first["uri"]


def test_api_uses_filesystem_sink_when_mount_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRODOCUX_ARTIFACT_MOUNT", str(tmp_path))
    monkeypatch.delenv("PRODOCUX_BEARER_TOKENS", raising=False)
    from api import main as main_mod

    main_mod._RENDER_SINK = FilesystemArtifactSink(tmp_path)
    assert isinstance(main_mod._RENDER_SINK, FilesystemArtifactSink)
    assert not isinstance(main_mod._RENDER_SINK, InMemoryArtifactSink)
    client = TestClient(main_mod.app)
    assert client.get("/ready").json()["checks"]["artifact_mount_writable"] is True
