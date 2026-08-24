"""In-memory resolver and create-if-absent sink for contract tests."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from .errors import ARTIFACT_CREATE_CONFLICT, RenderContractError

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$")


class InMemoryArtifactResolver:
    def __init__(self, values: Mapping[str, bytes] | None = None) -> None:
        self.values = dict(values or {})

    def resolve(self, uri: str) -> bytes:
        return self.values[uri]


class ManualCancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


class InMemoryArtifactSink:
    """Host-like sink: assigns artifact:// URIs and never accepts caller URIs."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[bytes, dict[str, Any]]] = {}

    def create_if_absent(
        self,
        *,
        output_name: str,
        media_type: str,
        payload: bytes,
        sha256: str,
    ) -> Mapping[str, Any]:
        if not _SAFE_NAME.fullmatch(output_name):
            raise RenderContractError(
                ARTIFACT_CREATE_CONFLICT, "sink rejected unsafe output_name"
            )
        digest = hashlib.sha256(payload).hexdigest()
        if digest != sha256:
            raise RenderContractError(
                ARTIFACT_CREATE_CONFLICT, "payload digest does not match declaration"
            )
        existing = self._store.get(output_name)
        if existing is not None:
            previous, identity = existing
            if hashlib.sha256(previous).hexdigest() != digest:
                raise RenderContractError(
                    ARTIFACT_CREATE_CONFLICT,
                    "output already exists with a different digest",
                )
            return identity
        identity = {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": output_name.replace(".", "-")[:128],
            "uri": f"artifact://render/{output_name}",
            "sha256": digest,
            "size_bytes": len(payload),
            "media_type": media_type,
        }
        self._store[output_name] = (bytes(payload), identity)
        return identity

    def get(self, artifact_id: str) -> tuple[bytes, Mapping[str, Any]] | None:
        """Return payload and identity for a sink-assigned artifact_id."""
        for payload, identity in self._store.values():
            if identity["artifact_id"] == artifact_id:
                return payload, identity
        return None
