"""JSON Schema + semantic validation for A0 render contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from .errors import (
    CONTENT_BLOCKS_INVALID,
    DELIVERY_MODE_INVALID,
    FORMAT_NOT_SUPPORTED,
    REQUEST_INVALID,
    TEMPLATE_IDENTITY_INVALID,
    TEMPLATE_NOT_SUPPORTED,
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
    if request.get("template"):
        raise RenderContractError(
            TEMPLATE_NOT_SUPPORTED,
            "this kernel version does not apply templates; map Template Pack to content blocks first",
        )
    return request


def validate_render_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate(_schema("prodocux_render_result_v1.json"), result, REQUEST_INVALID)
    return result


def validate_render_capabilities(document: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate(_schema("prodocux_render_capabilities_v1.json"), document, REQUEST_INVALID)
    return document


def validate_continuable_projection_result(
    document: Mapping[str, Any],
    *,
    request_cursor: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _validate(
        _schema("prodocux_continuable_projection_v1.json"),
        document,
        REQUEST_INVALID,
    )
    validate_content_blocks(document["content"])
    range_info = document["range"]
    coverage = document["coverage"]
    blocks = document["content"]["blocks"]
    returned = range_info["returned_blocks"]
    start = range_info["start"]
    end = range_info["end_exclusive"]
    parser_name = document["parser_contract"]["name"]
    source_digest = document["source"]["sha256"]
    if request_cursor is None:
        if start != 0:
            raise RenderContractError(
                REQUEST_INVALID,
                "initial projection range must start at block zero",
            )
    elif (
        request_cursor.get("next_block") != start
        or request_cursor.get("source_sha256") != source_digest
        or request_cursor.get("parser_contract_name") != parser_name
        or request_cursor.get("parser_contract_version")
        != document["parser_contract"]["version"]
        or request_cursor.get("format") != document["source"]["format"]
    ):
        raise RenderContractError(
            REQUEST_INVALID,
            "request range descriptor is inconsistent with the projection response",
        )
    if returned != len(blocks) or end != start + returned:
        raise RenderContractError(
            REQUEST_INVALID,
            "projection range does not match returned content blocks",
        )
    if returned > range_info["requested_max_blocks"]:
        raise RenderContractError(
            REQUEST_INVALID,
            "returned projection blocks exceed the requested maximum",
        )
    continuation_available = coverage["continuation_available"]
    next_cursor = document["next_cursor"]
    if next_cursor is not None:
        _validate(
            _schema("prodocux_projection_cursor_v1.json"),
            next_cursor,
            REQUEST_INVALID,
        )
    if continuation_available != (next_cursor is not None):
        raise RenderContractError(
            REQUEST_INVALID,
            "projection continuation flag and cursor are inconsistent",
        )
    if next_cursor is not None and next_cursor["next_block"] != end:
        raise RenderContractError(
            REQUEST_INVALID,
            "projection cursor does not begin at the next block",
        )
    if next_cursor is not None and (
        next_cursor["source_sha256"] != source_digest
        or next_cursor["parser_contract_name"] != parser_name
        or next_cursor["parser_contract_version"]
        != document["parser_contract"]["version"]
        or next_cursor["format"] != document["source"]["format"]
    ):
        raise RenderContractError(
            REQUEST_INVALID,
            "next range descriptor is not bound to the response source and parser",
        )
    from .extract import flatten_text_items

    if document["text_items"] != flatten_text_items(document["content"]):
        raise RenderContractError(
            REQUEST_INVALID,
            "text_items must be the deterministic projection of content blocks",
        )
    known_total = coverage["known_total_blocks"]
    processed_counts = document["counts"]["processed_through_range_end"]
    total_counts = document["counts"]["known_total"]
    if processed_counts["blocks"] != end:
        raise RenderContractError(
            REQUEST_INVALID,
            "processed block count must end at the disclosed range boundary",
        )
    if processed_counts["pages"] is not None or total_counts["pages"] is not None:
        raise RenderContractError(
            REQUEST_INVALID,
            "DOCX projection must not invent page counts",
        )
    if continuation_available and known_total is not None and known_total < end + 1:
        raise RenderContractError(
            REQUEST_INVALID,
            "known total does not include the undisclosed continuation",
        )
    if continuation_available and (
        known_total is not None or coverage["disposition"] != "partial_unknown"
    ):
        raise RenderContractError(
            REQUEST_INVALID,
            "unknown non-final remainder must be reported as partial_unknown",
        )
    if not continuation_available and known_total != end:
        raise RenderContractError(
            REQUEST_INVALID,
            "final projection range must disclose its exact total block count",
        )
    if total_counts["blocks"] != known_total:
        raise RenderContractError(
            REQUEST_INVALID,
            "coverage and count total blocks are inconsistent",
        )
    if continuation_available and any(
        total_counts[key] is not None for key in ("table_rows", "text_utf8_bytes")
    ):
        raise RenderContractError(
            REQUEST_INVALID,
            "non-final projection cannot claim unknown aggregate totals",
        )
    if not continuation_available and any(
        total_counts[key] != processed_counts[key]
        for key in ("table_rows", "text_utf8_bytes")
    ):
        raise RenderContractError(
            REQUEST_INVALID,
            "final projection totals must match cumulative processed counts",
        )
    if coverage["disposition"] == "complete" and (
        continuation_available or coverage["omitted_content_classes"]
    ):
        raise RenderContractError(
            REQUEST_INVALID,
            "complete projection cannot have continuation or omitted content",
        )
    if not continuation_available and not coverage["omitted_content_classes"]:
        if coverage["disposition"] != "complete":
            raise RenderContractError(
                REQUEST_INVALID,
                "fully projected final range must be reported as complete",
            )
    if coverage["disposition"] == "partial_known" and (
        continuation_available or not coverage["omitted_content_classes"]
    ):
        raise RenderContractError(
            REQUEST_INVALID,
            "partial_known requires a final range with disclosed omissions",
        )
    if coverage["disposition"] == "partial_unknown" and (
        not continuation_available and not coverage["omitted_content_classes"]
    ):
        raise RenderContractError(
            REQUEST_INVALID,
            "partial_unknown requires an unknown remainder or disclosed omissions",
        )
    return dict(document)
