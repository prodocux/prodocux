"""Audit follow-up: intake deadlock, writable local mounts, mTLS header spoofing."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from prodocux_kernel.rendering.derived_store import default_derived_mount
from prodocux_kernel.rendering.intake_store import (
    IntakeMaterialStore,
    default_intake_mount,
)


def test_missing_intake_uri_does_not_deadlock(tmp_path: Path) -> None:
    store = IntakeMaterialStore(tmp_path / "intake")
    missing = (
        "artifact://intake/"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/"
        "missing.bin"
    )
    raised = False
    try:
        store.resolve(missing)
    except KeyError:
        raised = True
    assert raised is True


def test_unconfigured_mounts_are_not_var_lib(monkeypatch) -> None:
    monkeypatch.delenv("PRODOCUX_INTAKE_MOUNT", raising=False)
    monkeypatch.delenv("PRODOCUX_DERIVED_MOUNT", raising=False)
    monkeypatch.delenv("PRODOCUX_ARTIFACT_MOUNT", raising=False)
    monkeypatch.delenv("PRODOCUX_TMP_MOUNT", raising=False)
    assert "var/lib/prodocux" not in default_intake_mount().as_posix()
    assert "var/lib/prodocux" not in default_derived_mount().as_posix()


def test_production_mtls_rejects_client_cert_header_spoof(monkeypatch) -> None:
    monkeypatch.setenv("PRODOCUX_AUTH_PROFILE", "production_mtls")
    monkeypatch.setenv("PRODOCUX_BEARER_TOKENS", "mtls-token")
    from api import main as main_mod

    client = TestClient(main_mod.app)
    spoofed = client.get(
        "/v1/version",
        headers={
            "Authorization": "Bearer mtls-token",
            "X-Client-Cert": "-----BEGIN CERTIFICATE-----fake",
        },
    )
    assert spoofed.status_code == 401
    assert spoofed.json()["code"] == "AUTH_MTLS_REQUIRED"


def test_production_mtls_rejects_untrusted_peer(monkeypatch) -> None:
    monkeypatch.setenv("PRODOCUX_AUTH_PROFILE", "production_mtls")
    monkeypatch.setenv("PRODOCUX_BEARER_TOKENS", "mtls-token")
    monkeypatch.setenv("PRODOCUX_MTLS_TRUSTED_PEERS", "203.0.113.10")
    from api import main as main_mod

    client = TestClient(main_mod.app)
    denied = client.get(
        "/v1/version",
        headers={
            "Authorization": "Bearer mtls-token",
            "SSL_CLIENT_VERIFY": "SUCCESS",
        },
    )
    assert denied.status_code == 401
    assert denied.json()["code"] == "AUTH_MTLS_REQUIRED"
