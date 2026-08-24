"""Product-neutral render contract: extract, write, and Cloud-safe delivery."""

from .capabilities import render_capabilities
from .delivery import deliver_output
from .errors import RenderContractError
from .extract import extract_content_blocks, flatten_text_items
from .memory import InMemoryArtifactResolver, InMemoryArtifactSink, ManualCancellation
from .ports import ArtifactResolverPort, ArtifactSinkPort, CancellationProbe
from .service import (
    capabilities_document,
    content_blocks_validation_result,
    execute_extract_blocks,
    execute_render_artifact,
)
from .validate import validate_content_blocks, validate_render_request
from .writers import write_content_blocks

__all__ = [
    "ArtifactResolverPort",
    "ArtifactSinkPort",
    "CancellationProbe",
    "InMemoryArtifactResolver",
    "InMemoryArtifactSink",
    "ManualCancellation",
    "RenderContractError",
    "capabilities_document",
    "content_blocks_validation_result",
    "deliver_output",
    "execute_extract_blocks",
    "execute_render_artifact",
    "extract_content_blocks",
    "flatten_text_items",
    "render_capabilities",
    "validate_content_blocks",
    "validate_render_request",
    "write_content_blocks",
]
