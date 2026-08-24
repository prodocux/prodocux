"""Live render capabilities: five formats are available without a Kernel template."""

from __future__ import annotations

from .. import API_VERSION, __version__

from .limits import FORMAT_MAX_BYTES, INLINE_OUTPUT_MAX_BYTES

FORMATS = ("docx", "xlsx", "csv", "pptx", "pdf")


def render_capabilities() -> dict:
    formats = []
    for name in FORMATS:
        ceiling = FORMAT_MAX_BYTES[name]
        formats.append(
            {
                "format": name,
                "status": "available",
                "operation": "POST /v1/render/artifact",
                "requires_template": False,
                "delivery_modes": ["artifact", "inline"],
                "max_template_bytes": ceiling,
                "max_artifact_output_bytes": ceiling,
                "max_inline_output_bytes": INLINE_OUTPUT_MAX_BYTES,
                "accepts_inline_template": False,
            }
        )
    return {
        "schema_version": "prodocux_render_capabilities_v1",
        "kernel_version": __version__,
        "api_version": API_VERSION,
        "formats": formats,
    }
