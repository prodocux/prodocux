"""Output delivery helpers (inline vs host sink). No renderer is invoked here."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from typing import Any

from .errors import (
    ARTIFACT_SINK_UNAVAILABLE,
    CANCELLED,
    INLINE_OUTPUT_TOO_LARGE,
    RenderContractError,
)
from .limits import INLINE_OUTPUT_MAX_BYTES
from .ports import ArtifactSinkPort, CancellationProbe


def deliver_output(
    *,
    payload: bytes,
    media_type: str,
    output_name: str,
    delivery_mode: str,
    sink: ArtifactSinkPort | None,
    cancellation: CancellationProbe | None = None,
) -> dict[str, Any]:
    """Deliver already-rendered bytes. Used by A1+ and A0 sink/cancel tests."""
    digest = hashlib.sha256(payload).hexdigest()
    if cancellation is not None and cancellation.is_cancelled():
        raise RenderContractError(CANCELLED, "render was cancelled before output delivery")
    if delivery_mode == "inline":
        if len(payload) > INLINE_OUTPUT_MAX_BYTES:
            raise RenderContractError(
                INLINE_OUTPUT_TOO_LARGE,
                "inline output exceeds decoded byte ceiling",
            )
        return {
            "delivery_mode": "inline",
            "content_b64": base64.b64encode(payload).decode("ascii"),
            "media_type": media_type,
            "output_sha256": digest,
            "size_bytes": len(payload),
        }
    if sink is None:
        raise RenderContractError(
            ARTIFACT_SINK_UNAVAILABLE,
            "artifact delivery requires a host-injected sink",
        )
    identity = sink.create_if_absent(
        output_name=output_name,
        media_type=media_type,
        payload=payload,
        sha256=digest,
    )
    return {
        "delivery_mode": "artifact",
        "artifact": dict(identity),
        "media_type": media_type,
        "output_sha256": digest,
        "size_bytes": len(payload),
    }
