"""JSON Schema + semantic validation for A0 render contracts."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from ..artifacts import validate_opaque_artifact
from .errors import (
    CONTENT_BLOCKS_INVALID,
    DELIVERY_MODE_INVALID,
    FORMAT_NOT_SUPPORTED,
    INLINE_TEMPLATE_TOO_LARGE,
    REQUEST_INVALID,
    TEMPLATE_IDENTITY_INVALID,
    RenderContractError,
)
from .limits import FORMAT_MAX_BYTES, validate_output_name

_FORBIDDEN_URI_MARKERS = (
    "gs://",
    "http://",
    "https://",
    "file:",
    "x-goog-signature",
    "x-amz-signature",
)


def _schema(name: str) -> dict[str, Any]:
    return json.loads(
        (resources.files("prodocux_kernel.schemas") / name).read_text(encoding="utf-8")
    )


def _validate(schema: Mapping[str, Any], instance: Mapping[str, Any], code: str) -> None:
    errors = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(
            Draft202012Validator(schema).iter_errors(instance),
            key=lambda item: list(item.path),
        )
    ]
    if errors:
        raise RenderContractError(code, errors[0][:1024])


def _reject_forbidden_locations(payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=True).casefold()
    for marker in _FORBIDDEN_URI_MARKERS:
        if marker in encoded:
            raise RenderContractError(
                TEMPLATE_IDENTITY_INVALID,
                "render request must not carry storage URLs, paths, or signed URIs",
            )
    dumped = json.dumps(payload)
    if "template_path" in dumped or "output_path" in dumped or "output_uri" in dumped:
        raise RenderContractError(
            REQUEST_INVALID,
            "render request must not include path or output URI fields",
        )


def validate_content_blocks(document: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate(_schema("prodocux_content_blocks_v1.json"), document, CONTENT_BLOCKS_INVALID)
    return document


def validate_render_request(request: Mapping[str, Any]) -> Mapping[str, Any]:
    _reject_forbidden_locations(request)
    _validate(_schema("prodocux_render_request_v1.json"), request, REQUEST_INVALID)
    target = str(request.get("target_format", ""))
    if target not in FORMAT_MAX_BYTES:
        raise RenderContractError(FORMAT_NOT_SUPPORTED, "target_format is not supported")
    validate_content_blocks(request["content"])
    output = request["output"]
    validate_output_name(str(output["output_name"]), target)
    if output["delivery_mode"] not in {"artifact", "inline"}:
        raise RenderContractError(DELIVERY_MODE_INVALID, "delivery_mode is not supported")
    template = request.get("template")
    if template:
        if "artifact" in template:
            identity = template["artifact"]
            errors = validate_opaque_artifact(identity)
            if errors:
                raise RenderContractError(TEMPLATE_IDENTITY_INVALID, errors[0][:1024])
            uri = str(identity.get("uri", ""))
            if not uri.startswith("artifact://"):
                raise RenderContractError(
                    TEMPLATE_IDENTITY_INVALID,
                    "template identity URI must be artifact://",
                )
        if "inline_b64" in template:
            try:
                raw = base64.b64decode(str(template["inline_b64"]), validate=True)
            except Exception as exc:
                raise RenderContractError(REQUEST_INVALID, "inline template is not valid base64") from exc
            if len(raw) > FORMAT_MAX_BYTES[target]:
                raise RenderContractError(
                    INLINE_TEMPLATE_TOO_LARGE,
                    "inline template exceeds format byte limit",
                )
    return request


def validate_render_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate(_schema("prodocux_render_result_v1.json"), result, REQUEST_INVALID)
    return result


def validate_render_capabilities(document: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate(_schema("prodocux_render_capabilities_v1.json"), document, REQUEST_INVALID)
    return document
