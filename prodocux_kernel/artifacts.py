"""Host-resolved, bounded opaque artifact bytes boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from importlib import resources
from typing import Any, Protocol, runtime_checkable

from jsonschema import Draft202012Validator

MAX_RESOLVED_ARTIFACT_BYTES = 100 * 1024 * 1024


class ArtifactResolutionError(ValueError):
    """Opaque artifact resolution failed closed."""


@runtime_checkable
class OpaqueArtifactResolver(Protocol):
    """Host-owned authorization/storage adapter returning content bytes only."""

    def resolve(self, uri: str) -> bytes: ...


def validate_opaque_artifact(identity: Mapping[str, Any]) -> list[str]:
    schema = json.loads(
        (
            resources.files("prodocux_kernel.schemas")
            / "prodocux_opaque_artifact_v1.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(
            validator.iter_errors(identity), key=lambda item: list(item.path)
        )
    ]


def resolve_opaque_artifact(
    identity: Mapping[str, Any],
    resolver: OpaqueArtifactResolver,
    *,
    max_bytes: int,
    allowed_media_types: set[str] | None = None,
) -> bytes:
    """Resolve only after metadata checks, then verify exact size and SHA-256."""
    errors = validate_opaque_artifact(identity)
    if errors:
        raise ArtifactResolutionError(
            "invalid opaque artifact identity:\n" + "\n".join(errors)
        )
    if max_bytes < 1 or max_bytes > MAX_RESOLVED_ARTIFACT_BYTES:
        raise ArtifactResolutionError("artifact byte limit is invalid")
    if identity["size_bytes"] > max_bytes:
        raise ArtifactResolutionError("artifact exceeds operation byte limit")
    if allowed_media_types is not None and identity["media_type"] not in allowed_media_types:
        raise ArtifactResolutionError("artifact media type is not allowed")
    raw = resolver.resolve(str(identity["uri"]))
    if not isinstance(raw, (bytes, bytearray)):
        raise ArtifactResolutionError("artifact resolver must return bytes")
    value = bytes(raw)
    if len(value) != identity["size_bytes"]:
        raise ArtifactResolutionError("resolved artifact size mismatch")
    if hashlib.sha256(value).hexdigest() != identity["sha256"]:
        raise ArtifactResolutionError("resolved artifact digest mismatch")
    return value


def opaque_artifact_identity_digest(identity: Mapping[str, Any]) -> str:
    """Return a stable identity digest without resolving content."""
    errors = validate_opaque_artifact(identity)
    if errors:
        raise ArtifactResolutionError(
            "invalid opaque artifact identity:\n" + "\n".join(errors)
        )
    encoded = json.dumps(
        identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
