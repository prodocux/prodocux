"""Host-injected resolver/sink ports for Cloud-safe render transport."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from ..artifacts import OpaqueArtifactResolver

ArtifactResolverPort = OpaqueArtifactResolver


@runtime_checkable
class ArtifactSinkPort(Protocol):
    """Host-owned output writer. Kernel never chooses the storage URI."""

    def create_if_absent(
        self,
        *,
        output_name: str,
        media_type: str,
        payload: bytes,
        sha256: str,
    ) -> Mapping[str, Any]:
        """Create bytes once. Same digest is a no-op; different digest conflicts."""
        ...


@runtime_checkable
class CancellationProbe(Protocol):
    def is_cancelled(self) -> bool: ...
