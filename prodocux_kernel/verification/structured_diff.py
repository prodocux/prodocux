"""Deterministic, product-neutral comparison of bounded normalized JSON values."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from prodocux_kernel.verification.diff_models import (
    NormalizedDiffRequestV1,
    NormalizedDiffResultV1,
)

MAX_DIFF_BYTES = 1_000_000
MAX_DIFF_DEPTH = 20
MAX_DIFF_NODES = 5_000
MAX_DIFF_STRING = 4_096
MAX_DIFF_ARRAY = 500
_MISSING = object()
_SPACE = re.compile(r"\s+")


class NormalizedDiffError(ValueError):
    """Normalized diff input exceeded a bound or contained unsafe JSON."""


def _pointer(path: str, part: str | int) -> str:
    escaped = str(part).replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def _validate_json(value: Any, *, depth: int = 0, counter: list[int]) -> None:
    if depth > MAX_DIFF_DEPTH:
        raise NormalizedDiffError("normalized profile exceeds maximum depth")
    counter[0] += 1
    if counter[0] > MAX_DIFF_NODES:
        raise NormalizedDiffError("normalized profile exceeds maximum node count")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NormalizedDiffError("normalized profile contains non-finite number")
        return
    if isinstance(value, str):
        if len(value) > MAX_DIFF_STRING:
            raise NormalizedDiffError("normalized profile string exceeds limit")
        return
    if isinstance(value, list):
        if len(value) > MAX_DIFF_ARRAY:
            raise NormalizedDiffError("normalized profile array exceeds limit")
        for item in value:
            _validate_json(item, depth=depth + 1, counter=counter)
        return
    if isinstance(value, dict):
        if len(value) > 1000:
            raise NormalizedDiffError("normalized profile object exceeds key limit")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise NormalizedDiffError("normalized profile keys must be bounded text")
            _validate_json(item, depth=depth + 1, counter=counter)
        return
    raise NormalizedDiffError("normalized profile contains a non-JSON value")


def _normalized(value: Any, mode: str) -> Any:
    if not isinstance(value, str) or mode == "exact":
        return value
    if mode == "trim":
        return value.strip()
    if mode == "collapse_whitespace":
        return _SPACE.sub(" ", value).strip()
    return value.casefold()


def _same_type(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right)
    return type(left) is type(right)


def compare_normalized_profiles(
    request: NormalizedDiffRequestV1 | dict[str, Any],
) -> dict[str, Any]:
    """Return a deterministic leaf-level diff with stable reason codes."""
    parsed = (
        request
        if isinstance(request, NormalizedDiffRequestV1)
        else NormalizedDiffRequestV1.model_validate(request)
    )
    canonical = parsed.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(
        canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > MAX_DIFF_BYTES:
        raise NormalizedDiffError("normalized diff request exceeds byte limit")
    counter = [0]
    _validate_json(parsed.before.values, counter=counter)
    _validate_json(parsed.after.values, counter=counter)
    for profile in (parsed.before, parsed.after):
        if any(
            locator.source_sha256 != profile.source_sha256
            for locator in profile.locators.values()
        ):
            raise NormalizedDiffError(
                "source locator digest must match its normalized profile"
            )

    changes: list[dict[str, Any]] = []
    total_changes = 0
    used_array_key_paths: set[str] = set()

    def record(path: str, left: Any, right: Any) -> None:
        nonlocal total_changes
        total_changes += 1
        if len(changes) >= parsed.max_changes:
            return
        if left is _MISSING:
            kind, reason = "added", "VALUE_ADDED"
        elif right is _MISSING:
            kind, reason = "removed", "VALUE_REMOVED"
        elif not _same_type(left, right):
            kind, reason = "type_changed", "VALUE_TYPE_CHANGED"
        else:
            kind, reason = "changed", "VALUE_CHANGED"
        change: dict[str, Any] = {"path": path, "kind": kind, "reason_code": reason}
        if left is not _MISSING:
            change["before_value"] = left
        if right is not _MISSING:
            change["after_value"] = right
        before_locator = parsed.before.locators.get(path)
        after_locator = parsed.after.locators.get(path)
        if before_locator is not None:
            change["before_locator"] = before_locator.model_dump(
                mode="json", exclude_none=True
            )
        if after_locator is not None:
            change["after_locator"] = after_locator.model_dump(
                mode="json", exclude_none=True
            )
        changes.append(change)

    def walk(left: Any, right: Any, path: str) -> None:
        if path in parsed.array_key_fields:
            if left is _MISSING and isinstance(right, list):
                left = []
            if right is _MISSING and isinstance(left, list):
                right = []
        if left is _MISSING and isinstance(right, dict) and right:
            for key in sorted(right):
                walk(_MISSING, right[key], _pointer(path, key))
            return
        if right is _MISSING and isinstance(left, dict) and left:
            for key in sorted(left):
                walk(left[key], _MISSING, _pointer(path, key))
            return
        if left is _MISSING and isinstance(right, list) and right:
            for index, item in enumerate(right):
                walk(_MISSING, item, _pointer(path, index))
            return
        if right is _MISSING and isinstance(left, list) and left:
            for index, item in enumerate(left):
                walk(item, _MISSING, _pointer(path, index))
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                walk(left.get(key, _MISSING), right.get(key, _MISSING), _pointer(path, key))
            return
        if isinstance(left, list) and isinstance(right, list):
            key_field = parsed.array_key_fields.get(path)
            if key_field is not None:
                used_array_key_paths.add(path)

                def keyed(items: list[Any]) -> dict[tuple[str, str], tuple[str, Any]]:
                    result: dict[tuple[str, str], tuple[str, Any]] = {}
                    for item in items:
                        if not isinstance(item, dict) or key_field not in item:
                            raise NormalizedDiffError(
                                f"keyed array {path!r} requires object rows with {key_field!r}"
                            )
                        value = item[key_field]
                        if isinstance(value, bool) or not isinstance(value, (str, int)):
                            raise NormalizedDiffError(
                                f"keyed array {path!r} keys must be strings or integers"
                            )
                        typed_key = (type(value).__name__, str(value))
                        if typed_key in result:
                            raise NormalizedDiffError(
                                f"keyed array {path!r} contains duplicate key {value!r}"
                            )
                        result[typed_key] = (str(value), item)
                    return result

                left_by_key, right_by_key = keyed(left), keyed(right)
                for typed_key in sorted(set(left_by_key) | set(right_by_key)):
                    left_row = left_by_key.get(typed_key)
                    right_row = right_by_key.get(typed_key)
                    display = (left_row or right_row)[0]
                    walk(
                        left_row[1] if left_row else _MISSING,
                        right_row[1] if right_row else _MISSING,
                        _pointer(path, f"@{display}"),
                    )
                return
            for index in range(max(len(left), len(right))):
                walk(
                    left[index] if index < len(left) else _MISSING,
                    right[index] if index < len(right) else _MISSING,
                    _pointer(path, index),
                )
            return
        if (
            left is _MISSING
            or right is _MISSING
            or not _same_type(left, right)
            or _normalized(left, parsed.string_normalization)
            != _normalized(right, parsed.string_normalization)
        ):
            record(path, left, right)

    walk(parsed.before.values, parsed.after.values, "")
    unused_key_paths = set(parsed.array_key_fields) - used_array_key_paths
    if unused_key_paths:
        raise NormalizedDiffError(
            "array key paths did not resolve to paired arrays: "
            + ", ".join(sorted(unused_key_paths))
        )
    result = {
        "schema_version": "prodocux_normalized_diff_result_v1",
        "verifier_id": "prodocux.normalized_diff",
        "verifier_version": "1",
        "request_digest": hashlib.sha256(encoded).hexdigest(),
        "status": "changed" if total_changes else "identical",
        "before_document_id": parsed.before.document_id,
        "after_document_id": parsed.after.document_id,
        "before_source_sha256": parsed.before.source_sha256,
        "after_source_sha256": parsed.after.source_sha256,
        "string_normalization": parsed.string_normalization,
        "changes": changes,
        "total_changes": total_changes,
        "truncated": total_changes > len(changes),
    }
    return NormalizedDiffResultV1.model_validate(result).model_dump(
        mode="json", exclude_unset=True
    )
