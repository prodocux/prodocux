"""Kernel-owned intake materialization (Phase 1).

Ephemeral bytes cross the private hop once, then subsequent Kernel calls use
``artifact://`` identities. This store is separate from the output sink and
never shares a writable volume with Engine staging.

URI form: ``artifact://intake/{artifact_id}/{basename}`` — the path always
includes the unique ``artifact_id`` so same filenames do not collide.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .memory import assign_artifact_id

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$")
_META_SUFFIX = ".identity.json"


def default_intake_mount() -> Path:
    raw = os.environ.get("PRODOCUX_INTAKE_MOUNT", "").strip()
    if raw:
        return Path(raw)
    tmp = os.environ.get("PRODOCUX_TMP_MOUNT", "").strip()
    if tmp:
        return Path(tmp) / "intake"
    return Path("/var/lib/prodocux/tmp/intake")


def intake_artifact_uri(*, artifact_id: str, output_name: str) -> str:
    """Return a collision-safe intake URI that embeds the unique artifact_id."""
    return f"artifact://intake/{artifact_id}/{output_name}"


class IntakeMaterialStore:
    """Create-if-absent intake materials with opaque artifact:// identities."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_intake_mount()).resolve()
        self._lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)

    def materialize(
        self,
        *,
        output_name: str,
        media_type: str,
        payload: bytes,
        sha256: str | None = None,
    ) -> Mapping[str, Any]:
        if not _SAFE_NAME.fullmatch(output_name):
            raise ValueError("document_filename must be a plain basename")
        digest = hashlib.sha256(payload).hexdigest()
        if sha256 is not None and digest != sha256:
            raise ValueError("payload digest does not match declaration")
        with self._lock:
            artifact_id = assign_artifact_id(output_name, digest)
            identity = {
                "schema_version": "prodocux_opaque_artifact_v1",
                "artifact_id": artifact_id,
                "uri": intake_artifact_uri(
                    artifact_id=artifact_id, output_name=output_name
                ),
                "sha256": digest,
                "size_bytes": len(payload),
                "media_type": media_type,
            }
            payload_path = self.root / artifact_id
            meta_path = self.root / f"{artifact_id}{_META_SUFFIX}"
            if meta_path.exists() and payload_path.exists():
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
                if existing.get("sha256") == digest:
                    return existing
                raise ValueError("intake material conflicts with a different digest")
            tmp_payload = Path(str(payload_path) + ".tmp")
            tmp_meta = Path(str(meta_path) + ".tmp")
            tmp_payload.write_bytes(payload)
            tmp_meta.write_text(
                json.dumps(identity, ensure_ascii=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp_payload, payload_path)
            os.replace(tmp_meta, meta_path)
            return identity

    def resolve(self, uri: str) -> bytes:
        """OpaqueArtifactResolver: return bytes for an artifact://intake URI."""
        with self._lock:
            for meta_path in self.root.glob(f"*{_META_SUFFIX}"):
                identity = json.loads(meta_path.read_text(encoding="utf-8"))
                if identity.get("uri") == uri:
                    return (self.root / identity["artifact_id"]).read_bytes()
            # Fast path: artifact://intake/{artifact_id}/…
            if uri.startswith("artifact://intake/"):
                rest = uri[len("artifact://intake/") :]
                artifact_id = rest.split("/", 1)[0]
                found = self.get_by_id(artifact_id)
                if found is not None:
                    payload, identity = found
                    if identity.get("uri") == uri:
                        return payload
        raise KeyError(uri)

    def get_by_id(self, artifact_id: str) -> tuple[bytes, Mapping[str, Any]] | None:
        with self._lock:
            meta_path = self.root / f"{artifact_id}{_META_SUFFIX}"
            payload_path = self.root / artifact_id
            if not meta_path.exists() or not payload_path.exists():
                return None
            identity = json.loads(meta_path.read_text(encoding="utf-8"))
            return payload_path.read_bytes(), identity
