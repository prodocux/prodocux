"""Verified opaque artifact byte retrieval (Phase 3).

Resolves ``artifact://intake|derived|sink|render/…`` through the appropriate
Kernel store, verifies digest and size against the declared identity, and
returns bytes only after validation.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from prodocux_kernel.artifacts import ArtifactResolutionError, validate_opaque_artifact
from prodocux_kernel.rendering.derived_store import DerivedArtifactStore
from prodocux_kernel.rendering.filesystem import FilesystemArtifactSink
from prodocux_kernel.rendering.intake_store import IntakeMaterialStore

_RETRIEVAL_URI = re.compile(
    r"^artifact://(intake|derived|sink|render)/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)?$"
)


class ArtifactRetrievalError(ValueError):
    """Opaque artifact retrieval failed closed."""


def retrieve_verified_opaque_artifact(
    identity: Mapping[str, Any],
    *,
    intake_store: IntakeMaterialStore,
    derived_store: DerivedArtifactStore,
    render_sink: FilesystemArtifactSink,
    max_bytes: int,
) -> bytes:
    errors = validate_opaque_artifact(identity)
    if errors:
        raise ArtifactRetrievalError(
            "invalid opaque artifact identity:\n" + "\n".join(errors)
        )
    uri = str(identity["uri"])
    if not _RETRIEVAL_URI.fullmatch(uri):
        raise ArtifactRetrievalError("artifact URI namespace is not retrievable")
    namespace = uri.split("/", 3)[2] if uri.startswith("artifact://") else ""
    if namespace == "intake":
        raw = intake_store.resolve(uri)
    elif namespace == "derived":
        raw = derived_store.resolve(uri)
    elif namespace in {"sink", "render"}:
        found = render_sink.get(str(identity["artifact_id"]))
        if found is None:
            raise ArtifactRetrievalError("artifact not found")
        raw, stored = found
        if str(stored.get("uri")) != uri:
            raise ArtifactRetrievalError("artifact identity URI mismatch")
    else:
        raise ArtifactRetrievalError("artifact URI namespace is not retrievable")

    if not isinstance(raw, (bytes, bytearray)):
        raise ArtifactRetrievalError("artifact store returned non-bytes")
    payload = bytes(raw)
    if len(payload) != identity["size_bytes"]:
        raise ArtifactRetrievalError("resolved artifact size mismatch")
    if len(payload) > max_bytes:
        raise ArtifactRetrievalError("artifact exceeds retrieval byte limit")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != identity["sha256"]:
        raise ArtifactRetrievalError("resolved artifact digest mismatch")
    return payload
