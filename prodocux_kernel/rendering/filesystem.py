"""Restart-safe filesystem artifact sink (Phase 1).

Writes opaque ``artifact://`` identities under a dedicated output mount.
Never accepts caller-selected URIs, ``gs://``, or local path identities.
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

from .errors import ARTIFACT_CREATE_CONFLICT, ARTIFACT_SINK_UNAVAILABLE, RenderContractError
from .memory import assign_artifact_id

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$")
_META_SUFFIX = ".identity.json"


def default_output_mount() -> Path:
    raw = os.environ.get("PRODOCUX_ARTIFACT_MOUNT", "").strip()
    if raw:
        return Path(raw)
    return Path("/var/lib/prodocux/artifacts")


class FilesystemArtifactSink:
    """Host-injected sink backed by a bounded writable mount."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_output_mount()).resolve()
        self._lock = threading.Lock()
        self._ensure_root()

    def _ensure_root(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RenderContractError(
                ARTIFACT_SINK_UNAVAILABLE,
                "artifact mount is not writable",
            ) from exc
        if not os.access(self.root, os.W_OK):
            raise RenderContractError(
                ARTIFACT_SINK_UNAVAILABLE,
                "artifact mount is not writable",
            )

    def _payload_path(self, artifact_id: str) -> Path:
        return self.root / artifact_id

    def _meta_path(self, artifact_id: str) -> Path:
        return self.root / f"{artifact_id}{_META_SUFFIX}"

    def _name_index_path(self, output_name: str) -> Path:
        digest = hashlib.sha256(output_name.encode("utf-8")).hexdigest()
        return self.root / f"name-{digest}.idx"

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

        with self._lock:
            self._ensure_root()
            index = self._name_index_path(output_name)
            if index.exists():
                existing_id = index.read_text(encoding="utf-8").strip()
                meta_path = self._meta_path(existing_id)
                payload_path = self._payload_path(existing_id)
                if not meta_path.exists() or not payload_path.exists():
                    raise RenderContractError(
                        ARTIFACT_SINK_UNAVAILABLE,
                        "artifact index is inconsistent",
                    )
                identity = json.loads(meta_path.read_text(encoding="utf-8"))
                previous = payload_path.read_bytes()
                if hashlib.sha256(previous).hexdigest() != digest:
                    raise RenderContractError(
                        ARTIFACT_CREATE_CONFLICT,
                        "output already exists with a different digest",
                    )
                return identity

            artifact_id = assign_artifact_id(output_name, digest)
            identity = {
                "schema_version": "prodocux_opaque_artifact_v1",
                "artifact_id": artifact_id,
                "uri": f"artifact://sink/{output_name}",
                "sha256": digest,
                "size_bytes": len(payload),
                "media_type": media_type,
            }
            payload_path = self._payload_path(artifact_id)
            meta_path = self._meta_path(artifact_id)
            tmp_payload = Path(str(payload_path) + ".tmp")
            tmp_meta = Path(str(meta_path) + ".tmp")
            try:
                tmp_payload.write_bytes(payload)
                tmp_meta.write_text(
                    json.dumps(identity, ensure_ascii=True, separators=(",", ":"))
                    + "\n",
                    encoding="utf-8",
                )
                os.replace(tmp_payload, payload_path)
                os.replace(tmp_meta, meta_path)
                index.write_text(artifact_id + "\n", encoding="utf-8")
            except OSError as exc:
                for path in (tmp_payload, tmp_meta):
                    if path.exists():
                        path.unlink(missing_ok=True)
                raise RenderContractError(
                    ARTIFACT_SINK_UNAVAILABLE,
                    "artifact mount write failed",
                ) from exc
            return identity

    def get(self, artifact_id: str) -> tuple[bytes, Mapping[str, Any]] | None:
        with self._lock:
            meta_path = self._meta_path(artifact_id)
            payload_path = self._payload_path(artifact_id)
            if not meta_path.exists() or not payload_path.exists():
                return None
            identity = json.loads(meta_path.read_text(encoding="utf-8"))
            return payload_path.read_bytes(), identity

    def record_status_for(
        self,
        *,
        output_name: str,
        sha256: str,
    ) -> str:
        """Return Phase 0 filesystem sink record_status for observability tests."""
        index = self._name_index_path(output_name)
        if not index.exists():
            return "created"
        existing_id = index.read_text(encoding="utf-8").strip()
        found = self.get(existing_id)
        if found is None:
            return "created"
        _, identity = found
        if identity["sha256"] == sha256:
            return "no_op"
        return "conflict"
