"""Kernel-owned derived/output artifacts (Phase 1).

Used for processing outputs (e.g. extract-blocks JSON) that are not the intake
source and not necessarily the render sink path used by G1A fixtures.
URI form: ``artifact://derived/{artifact_id}/{basename}``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .memory import assign_artifact_id

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$")
_META_SUFFIX = ".identity.json"


def default_derived_mount() -> Path:
    raw = os.environ.get("PRODOCUX_DERIVED_MOUNT", "").strip()
    if raw:
        return Path(raw)
    artifacts = os.environ.get("PRODOCUX_ARTIFACT_MOUNT", "").strip()
    if artifacts:
        return Path(artifacts) / "derived"
    return Path(tempfile.gettempdir()) / "prodocux" / "derived"


def derived_artifact_uri(*, artifact_id: str, output_name: str) -> str:
    return f"artifact://derived/{artifact_id}/{output_name}"


class DerivedArtifactStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_derived_mount()).resolve()
        self._lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        *,
        output_name: str,
        media_type: str,
        payload: bytes,
        sha256: str | None = None,
    ) -> Mapping[str, Any]:
        if not _SAFE_NAME.fullmatch(output_name):
            raise ValueError("output_name must be a plain basename")
        digest = hashlib.sha256(payload).hexdigest()
        if sha256 is not None and digest != sha256:
            raise ValueError("payload digest does not match declaration")
        with self._lock:
            artifact_id = assign_artifact_id(output_name, digest)
            identity = {
                "schema_version": "prodocux_opaque_artifact_v1",
                "artifact_id": artifact_id,
                "uri": derived_artifact_uri(
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
                raise ValueError("derived artifact conflicts with a different digest")
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
        with self._lock:
            for meta_path in self.root.glob(f"*{_META_SUFFIX}"):
                identity = json.loads(meta_path.read_text(encoding="utf-8"))
                if identity.get("uri") == uri:
                    return (self.root / identity["artifact_id"]).read_bytes()
        raise KeyError(uri)
