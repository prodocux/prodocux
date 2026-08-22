"""Deterministic typed evidence verification with stable reason codes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from itertools import pairwise
from typing import Any

from prodocux_kernel.verification.evidence_models import (
    EvidenceBundleRequestV1,
    EvidenceBundleResultV1,
    EvidenceCheck,
    EvidenceCheckResult,
    EvidenceItem,
)


class EvidenceValidationError(ValueError):
    """The evidence bundle is structurally valid but semantically inconsistent."""


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise EvidenceValidationError(f"{label} identities must be unique")


def _validate_value_type(item: EvidenceItem) -> None:
    value = item.value
    valid = {
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "date": isinstance(value, str),
        "version": isinstance(value, str),
        "null": value is None,
    }[item.value_type]
    if not valid:
        raise EvidenceValidationError(
            f"evidence {item.evidence_id!r} value does not match {item.value_type!r}"
        )


def _parse_date(value: Any) -> date | datetime:
    if not isinstance(value, str):
        raise TypeError("date value must be a string")
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return date.fromisoformat(value)


def _presence_result(check: EvidenceCheck, items: list[EvidenceItem]) -> tuple:
    missing = [
        item
        for item in items
        if item.value is None or (isinstance(item.value, str) and not item.value.strip())
    ]
    if missing:
        return "fail", ["VALUE_MISSING"], None, missing[0].value, {
            "missing_count": len(missing)
        }
    return "pass", ["VALUE_PRESENT"], None, items[0].value, {}


def _equality_result(check: EvidenceCheck, items: list[EvidenceItem]) -> tuple:
    has_expected = "expected" in check.model_fields_set
    expected = check.expected if has_expected else items[0].value
    mismatch = next((item for item in items if item.value != expected), None)
    if mismatch is not None:
        return "fail", ["VALUE_MISMATCH"], expected, mismatch.value, {
            "compared_count": len(items)
        }
    return "pass", ["VALUES_EQUAL"], expected, items[0].value, {
        "compared_count": len(items)
    }


def _numeric_range_result(check: EvidenceCheck, items: list[EvidenceItem]) -> tuple:
    if len(items) != 1 or (check.minimum is None and check.maximum is None):
        raise EvidenceValidationError(
            f"numeric_range check {check.check_id!r} requires one evidence and a bound"
        )
    value = items[0].value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "fail", ["VALUE_NOT_NUMERIC"], None, value, {}
    if check.minimum is not None:
        below = value < check.minimum if check.minimum_inclusive else value <= check.minimum
        if below:
            return "fail", ["VALUE_BELOW_MINIMUM"], check.minimum, value, {}
    if check.maximum is not None:
        above = value > check.maximum if check.maximum_inclusive else value >= check.maximum
        if above:
            return "fail", ["VALUE_ABOVE_MAXIMUM"], check.maximum, value, {}
    expected = f"{check.minimum if check.minimum is not None else '-inf'}..{check.maximum if check.maximum is not None else 'inf'}"
    return "pass", ["VALUE_WITHIN_RANGE"], expected, value, {}


def _date_order_result(check: EvidenceCheck, items: list[EvidenceItem]) -> tuple:
    if len(items) < 2:
        raise EvidenceValidationError(
            f"date_order check {check.check_id!r} requires at least two evidence items"
        )
    try:
        parsed = [_parse_date(item.value) for item in items]
    except (TypeError, ValueError):
        return "fail", ["DATE_VALUE_INVALID"], "nondecreasing", None, {}
    if all(left <= right for left, right in pairwise(parsed)):
        return "pass", ["DATE_ORDER_VALID"], "nondecreasing", items[-1].value, {}
    return "fail", ["DATE_ORDER_INVALID"], "nondecreasing", items[-1].value, {}


def _version_match_result(check: EvidenceCheck, items: list[EvidenceItem]) -> tuple:
    if len(items) < 2 and "expected" not in check.model_fields_set:
        raise EvidenceValidationError(
            f"version_match check {check.check_id!r} requires two values or expected"
        )
    if not all(isinstance(item.value, str) for item in items):
        return "fail", ["VERSION_VALUE_INVALID"], check.expected, None, {}
    expected = check.expected if "expected" in check.model_fields_set else items[0].value
    mismatch = next((item for item in items if item.value != expected), None)
    if mismatch:
        return "fail", ["VERSION_MISMATCH"], expected, mismatch.value, {
            "compared_count": len(items)
        }
    return "pass", ["VERSIONS_MATCH"], expected, items[0].value, {
        "compared_count": len(items)
    }


_CHECKS = {
    "presence": _presence_result,
    "equality": _equality_result,
    "numeric_range": _numeric_range_result,
    "date_order": _date_order_result,
    "version_match": _version_match_result,
}


def verify_evidence_bundle(
    request: Mapping[str, Any] | EvidenceBundleRequestV1,
) -> dict[str, Any]:
    """Validate and deterministically evaluate a product-neutral evidence bundle."""

    model = (
        request
        if isinstance(request, EvidenceBundleRequestV1)
        else EvidenceBundleRequestV1.model_validate(request)
    )
    documents = {item.document_id: item for item in model.documents}
    evidence = {item.evidence_id: item for item in model.evidence}
    _unique([item.document_id for item in model.documents], "document")
    _unique([item.evidence_id for item in model.evidence], "evidence")
    _unique([item.check_id for item in model.checks], "check")

    for item in model.evidence:
        document = documents.get(item.document_id)
        if document is None:
            raise EvidenceValidationError(
                f"evidence {item.evidence_id!r} references an unknown document"
            )
        source = item.source_reference
        if source.source_sha256 != document.source_sha256:
            raise EvidenceValidationError(
                f"evidence {item.evidence_id!r} source digest mismatch"
            )
        if source.media_type != document.media_type:
            raise EvidenceValidationError(
                f"evidence {item.evidence_id!r} media type mismatch"
            )
        _validate_value_type(item)

    results: list[EvidenceCheckResult] = []
    for check in model.checks:
        try:
            items = [evidence[evidence_id] for evidence_id in check.evidence_ids]
        except KeyError as exc:
            raise EvidenceValidationError(
                f"check {check.check_id!r} references unknown evidence {exc.args[0]!r}"
            ) from exc
        status, reason_codes, expected, actual, details = _CHECKS[check.kind](
            check, items
        )
        if check.minimum_confidence is not None and any(
            item.confidence < check.minimum_confidence for item in items
        ):
            reason_codes.append("CONFIDENCE_BELOW_MINIMUM")
            details["minimum_confidence"] = check.minimum_confidence
            if status == "pass":
                status = "review"
        results.append(
            EvidenceCheckResult(
                check_id=check.check_id,
                status=status,
                reason_codes=reason_codes,
                evidence_ids=check.evidence_ids,
                expected=expected,
                actual=actual,
                details=details,
            )
        )

    statuses = {item.status for item in results}
    overall = "fail" if "fail" in statuses else "review" if "review" in statuses else "pass"
    canonical = model.model_dump(mode="json", exclude_none=False)
    result = EvidenceBundleResultV1(
        schema_version="prodocux_evidence_bundle_result_v1",
        request_id=model.request_id,
        canonical_request_sha256=_canonical_digest(canonical),
        verifier={"id": "prodocux.evidence_bundle", "version": "1"},
        rule_set=model.rule_set,
        status=overall,
        results=results,
    )
    return result.model_dump(mode="json", exclude_none=True)
