from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from prodocux_kernel.artifacts import (
    ArtifactResolutionError,
    OpaqueArtifactResolver,
    opaque_artifact_identity_digest,
    resolve_opaque_artifact,
    validate_opaque_artifact,
)

ROOT = Path(__file__).resolve().parents[1]


def _identity(raw: bytes = b"document") -> dict:
    return {
        "schema_version": "prodocux_opaque_artifact_v1",
        "artifact_id": "document-1",
        "uri": "artifact://run-1/input/document.docx",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }


class MemoryResolver:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values = values
        self.calls = 0

    def resolve(self, uri: str) -> bytes:
        self.calls += 1
        return self.values[uri]


def test_opaque_artifact_resolves_bytes_after_identity_checks() -> None:
    identity = _identity()
    resolver = MemoryResolver({identity["uri"]: b"document"})
    assert isinstance(resolver, OpaqueArtifactResolver)
    assert (
        resolve_opaque_artifact(
            identity,
            resolver,
            max_bytes=1024,
            allowed_media_types={identity["media_type"]},
        )
        == b"document"
    )
    assert resolver.calls == 1
    assert opaque_artifact_identity_digest(identity) == opaque_artifact_identity_digest(
        dict(reversed(list(identity.items())))
    )


def test_declared_oversize_and_media_mismatch_reject_before_resolve() -> None:
    identity = _identity()
    resolver = MemoryResolver({identity["uri"]: b"document"})
    with pytest.raises(ArtifactResolutionError, match="byte limit"):
        resolve_opaque_artifact(identity, resolver, max_bytes=1)
    with pytest.raises(ArtifactResolutionError, match="media type"):
        resolve_opaque_artifact(
            identity, resolver, max_bytes=1024, allowed_media_types={"application/pdf"}
        )
    assert resolver.calls == 0


def test_signed_network_local_and_drifted_artifacts_fail_closed() -> None:
    for uri in (
        "https://example.invalid/file?token=secret",
        "file:///tmp/document.docx",
        "C:/private/document.docx",
        "artifact://run-1/input/../secret.docx",
    ):
        identity = _identity()
        identity["uri"] = uri
        assert validate_opaque_artifact(identity), uri

    identity = _identity()
    resolver = MemoryResolver({identity["uri"]: b"Document"})
    with pytest.raises(ArtifactResolutionError, match="digest mismatch"):
        resolve_opaque_artifact(identity, resolver, max_bytes=1024)


def test_opaque_artifact_example_matches_schema() -> None:
    schema = json.loads(
        (ROOT / "prodocux_kernel/schemas/prodocux_opaque_artifact_v1.json").read_text(
            encoding="utf-8"
        )
    )
    example = json.loads(
        (ROOT / "examples/contracts/opaque_artifact_v1.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(example)
