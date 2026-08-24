"""Live content-block extract and 5-format render (Cloud-safe transport)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .. import __version__
from .capabilities import render_capabilities
from .delivery import deliver_output
from .errors import HTTP_STATUS, INTERNAL_SANITIZED, RenderContractError
from .extract import extract_content_blocks
from .limits import FORMAT_MEDIA_TYPES
from .ports import ArtifactSinkPort, CancellationProbe
from .validate import (
    validate_content_blocks,
    validate_render_capabilities,
    validate_render_request,
    validate_render_result,
)
from .writers import write_content_blocks


def _failed_result(
    *,
    code: str,
    message: str,
    target_format: str,
    request_id: str | None,
) -> dict[str, Any]:
    result = {
        "schema_version": "prodocux_render_result_v1",
        "status": "cancelled" if code == "CANCELLED" else "failed",
        "kernel_version": __version__,
        "renderer_id": "none",
        "renderer_version": "none",
        "target_format": target_format
        if target_format in {"docx", "xlsx", "csv", "pptx", "pdf"}
        else "pdf",
        "validation": {"passed": False, "reasons": [code]},
        "error": {"code": code, "message": message[:1024]},
    }
    if request_id:
        result["request_id"] = request_id
    if code == "TIMEOUT":
        result["status"] = "timed_out"
    return validate_render_result(result)


def execute_render_artifact(
    request: Mapping[str, Any],
    *,
    cancellation: CancellationProbe | None = None,
    sink: ArtifactSinkPort | None = None,
) -> tuple[int, dict[str, Any]]:
    """Validate, write bytes from content blocks, and deliver via sink or inline."""
    request_id = str(request.get("request_id") or "")
    target = str(request.get("target_format") or "pdf")
    try:
        validate_render_request(request)
        if cancellation is not None and cancellation.is_cancelled():
            raise RenderContractError("CANCELLED", "render was cancelled before execution")
        payload = write_content_blocks(request["content"], target)
        if cancellation is not None and cancellation.is_cancelled():
            raise RenderContractError("CANCELLED", "render was cancelled before output delivery")
        delivered = deliver_output(
            payload=payload,
            media_type=FORMAT_MEDIA_TYPES[target],
            output_name=str(request["output"]["output_name"]),
            delivery_mode=str(request["output"]["delivery_mode"]),
            sink=sink,
            cancellation=cancellation,
        )
        result: dict[str, Any] = {
            "schema_version": "prodocux_render_result_v1",
            "status": "completed",
            "kernel_version": __version__,
            "renderer_id": f"prodocux.blocks.{target}",
            "renderer_version": __version__,
            "target_format": target,
            "validation": {"passed": True, "reasons": []},
            "media_type": delivered["media_type"],
            "output_sha256": delivered["output_sha256"],
        }
        if request_id:
            result["request_id"] = request_id
        if delivered["delivery_mode"] == "inline":
            result["content_b64"] = delivered["content_b64"]
        else:
            result["artifact"] = delivered["artifact"]
        return 200, validate_render_result(result)
    except RenderContractError as exc:
        body = _failed_result(
            code=exc.code,
            message=exc.public_message,
            target_format=target,
            request_id=request_id or None,
        )
        return HTTP_STATUS.get(exc.code, 400), body
    except Exception:
        body = _failed_result(
            code=INTERNAL_SANITIZED,
            message="render failed",
            target_format=target,
            request_id=request_id or None,
        )
        return HTTP_STATUS.get(INTERNAL_SANITIZED, 500), body


def execute_extract_blocks(filename: str, payload: bytes) -> dict[str, Any]:
    """Extract product-neutral content blocks from a 5-format binary."""
    try:
        return extract_content_blocks(filename, payload)
    except RenderContractError:
        raise
    except ValueError as exc:
        raise RenderContractError("REQUEST_INVALID", str(exc)[:1024]) from exc


def content_blocks_validation_result(document: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
    try:
        validate_content_blocks(document)
    except RenderContractError as exc:
        return HTTP_STATUS.get(exc.code, 400), {
            "valid": False,
            "error": {"code": exc.code, "message": exc.public_message[:1024]},
        }
    return 200, {"valid": True, "schema_version": "prodocux_content_blocks_v1"}


def capabilities_document() -> dict[str, Any]:
    return validate_render_capabilities(render_capabilities())
