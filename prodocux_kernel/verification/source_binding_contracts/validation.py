"""Contract validation against independently derived runtime context.

Wire fields are never authority for authentication, parser or storage facts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent


class Invalid(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise Invalid(code)


def ijson(value, depth=0):
    require(depth <= 64, "REQUEST_INVALID")
    if isinstance(value, str):
        require(not any(0xD800 <= ord(ch) <= 0xDFFF for ch in value), "REQUEST_INVALID")
    elif isinstance(value, float):
        require(math.isfinite(value), "REQUEST_INVALID")
    elif isinstance(value, int) and not isinstance(value, bool):
        require(abs(value) <= 9007199254740991, "REQUEST_INVALID")
    elif isinstance(value, list):
        for item in value:
            ijson(item, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            ijson(key, depth + 1)
            ijson(item, depth + 1)


def parse(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "REQUEST_INVALID")
            result[k] = v
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(Invalid("REQUEST_INVALID")),
        )
        ijson(value)
        return value
    except (ValueError, UnicodeError, OverflowError, RecursionError) as e:
        raise Invalid("REQUEST_INVALID") from e


def digest(value):
    ijson(value)
    try:
        return hashlib.sha256(rfc8785.dumps(value)).hexdigest()
    except (ValueError, UnicodeError) as e:
        raise Invalid("REQUEST_INVALID") from e


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def material(value):
    return {
        k: v
        for k, v in value.items()
        if k not in ("schema_version", "request_id", "idempotency_key")
    }


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None, "REQUEST_INVALID")
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as e:
        raise Invalid("REQUEST_INVALID") from e


def load_schemas():
    schemas = {}
    for folder in ("dependencies", "schemas"):
        for p in sorted((ROOT / folder).glob("*.json")):
            value = json.loads(p.read_text(encoding="utf-8"))
            if "$id" in value:
                schemas[value["$id"]] = value
    registry = Registry()
    for key, value in schemas.items():
        registry = registry.with_resource(key, Resource.from_contents(value))
    return schemas, registry


SCHEMAS, REGISTRY = load_schemas()


def shape(schema_ref, value):
    ijson(value)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": schema_ref,
    }
    require(
        Draft202012Validator(
            schema, registry=REGISTRY, format_checker=FormatChecker()
        ).is_valid(value),
        "REQUEST_INVALID",
    )


def decimal(value, scale, declared=False):
    require(
        isinstance(scale, int) and not isinstance(scale, bool) and 0 <= scale <= 8,
        "REQUEST_INVALID",
    )
    require(
        isinstance(value, str)
        and re.fullmatch(r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,8})?", value) is not None,
        "REQUEST_INVALID" if declared else "VALUE_CONVERSION_FAILED",
    )
    fractional = value.split(".")[1] if "." in value else ""
    require(
        len(fractional) == scale,
        "REQUEST_INVALID" if declared else "VALUE_CONVERSION_FAILED",
    )
    zero = all(ch in "0.-" for ch in value)
    canonical = value[1:] if zero and value.startswith("-") else value
    require(not declared or value == canonical, "REQUEST_INVALID")
    return canonical


def kernel_request(request, context):
    if (
        isinstance(request, dict)
        and isinstance(request.get("source"), dict)
        and request["source"].get("media_type") not in (None, "application/pdf")
    ):
        raise Invalid("SOURCE_TYPE_UNSUPPORTED")
    shape("urn:pdx:draft:cr003:core:1#/$defs/request", request)
    for c in request["checks"]:
        decimal(c["declared_value"], c["scale"], True)
        q, v = c["quote_range"], c["value_range"]
        require(
            0 <= q["start"] < q["end"] and q["end"] - q["start"] <= 4096,
            "REQUEST_INVALID",
        )
        require(
            q["start"] <= v["start"] < v["end"] <= q["end"]
            and v["end"] - v["start"] <= 64,
            "REQUEST_INVALID",
        )
    require(
        len({c["check_id"] for c in request["checks"]}) == len(request["checks"]),
        "REQUEST_INVALID",
    )
    try:
        raw = base64.b64decode(request["source"]["document_b64"], validate=True)
    except ValueError as e:
        raise Invalid("REQUEST_INVALID") from e
    require(
        base64.b64encode(raw).decode() == request["source"]["document_b64"],
        "REQUEST_INVALID",
    )
    require(len(raw) <= 10485760, "SOURCE_TOO_LARGE")
    require(
        sha(raw) == request["source"]["sha256"]
        and len(raw) == request["source"]["size_bytes"],
        "SOURCE_IDENTITY_MISMATCH",
    )
    require(
        context is not None and context.get("source_sha256") == sha(raw),
        "SOURCE_IDENTITY_MISMATCH",
    )
    require(
        context.get("parser_contract") == request["parser_contract"],
        "PARSER_CONTRACT_MISMATCH",
    )
    require(
        1 <= request["page_number"] <= context["total_pages"]
        and context["page_number"] == request["page_number"],
        "PAGE_UNAVAILABLE",
    )
    text = context["text"]
    ijson(text)
    text = unicodedata.normalize("NFC", text)
    require(
        len(text) <= 50000 or context.get("quality") == "incomplete",
        "PARSER_RESOURCE_LIMIT",
    )
    require(
        sha(text.encode()) == request["expected_page_text_sha256"],
        "PAGE_PROJECTION_MISMATCH",
    )
    return text


def kernel_result(request, context):
    text = kernel_request(request, context)
    quality = context["quality"]
    require(
        quality in ("complete_native_text", "ocr_required", "incomplete"),
        "REQUEST_INVALID",
    )
    rows = []
    for c in request["checks"]:
        row = {k: c[k] for k in ("check_id", "quote_range", "value_range")}
        row["evidence"] = None
        if quality != "complete_native_text":
            row.update(
                status="review",
                reason_code="SELECTED_UNIT_OCR_REQUIRED"
                if quality == "ocr_required"
                else "SELECTED_UNIT_INCOMPLETE",
            )
        elif c["quote_range"]["end"] > len(text):
            row.update(status="fail", reason_code="RANGE_OUT_OF_BOUNDS")
        else:
            q = text[c["quote_range"]["start"] : c["quote_range"]["end"]]
            v = text[c["value_range"]["start"] : c["value_range"]["end"]]
            ev = {k: c[k] for k in ("conversion_rule", "declared_value", "scale")}
            ev.update(
                quote_sha256=sha(q.encode()),
                value_sha256=sha(v.encode()),
                derived_value=None,
            )
            row["evidence"] = ev
            if q != c["quote"]:
                row.update(status="fail", reason_code="QUOTE_MISMATCH")
            else:
                try:
                    ev["derived_value"] = decimal(v, c["scale"])
                    good = ev["derived_value"] == c["declared_value"]
                    row.update(
                        status="pass" if good else "fail",
                        reason_code="SOURCE_SPAN_VERIFIED"
                        if good
                        else "VALUE_MISMATCH",
                    )
                except Invalid:
                    row.update(status="fail", reason_code="VALUE_CONVERSION_FAILED")
        rows.append(row)
    omissions = [
        "image_content_not_evaluated",
        "unselected_document_content_not_evaluated",
    ]
    if quality != "complete_native_text":
        omissions.append(
            "ocr_required_not_performed"
            if quality == "ocr_required"
            else "page_text_beyond_limit"
        )
    src = {k: v for k, v in request["source"].items() if k != "document_b64"}
    result = {
        "source": src,
        "parser_contract": request["parser_contract"],
        "normalization": request["normalization"],
        "page_number": request["page_number"],
        "normalized_page_text_sha256": sha(text.encode()),
        "coverage": {
            "scope": "native_text_only",
            "selected_unit_status": quality,
            "document_disposition": "partial_unknown",
            "omissions": sorted(omissions),
        },
        "checks": rows,
        "overall_status": "fail"
        if any(r["status"] == "fail" for r in rows)
        else "review"
        if any(r["status"] == "review" for r in rows)
        else "pass",
    }
    result["page_identity_digest"] = digest(
        {
            k: result[k]
            for k in (
                "source",
                "parser_contract",
                "normalization",
                "page_number",
                "normalized_page_text_sha256",
            )
        }
    )
    return result


def kernel_report(report, request, context):
    shape("urn:pdx:draft:cr003:core:1#/$defs/report", report)
    require(report["request_id"] == request["request_id"], "REQUEST_INVALID")
    expected = kernel_result(request, context)
    req_material = {k: v for k, v in request.items() if k != "request_id"}
    req_material["source"] = {
        k: v for k, v in request["source"].items() if k != "document_b64"
    }
    require(
        report["semantic_request_digest"] == digest(req_material), "REQUEST_INVALID"
    )
    require(
        report["semantic_result"] == expected
        and report["semantic_result_digest"] == digest(expected),
        "REQUEST_INVALID",
    )
