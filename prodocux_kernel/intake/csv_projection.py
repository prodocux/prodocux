"""Bounded deterministic CSV row-range projection."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from prodocux_kernel.intake.errors import SourceTooLargeError
from prodocux_kernel.intake.projection_validate import validate_continuable_projection
from prodocux_kernel.intake.table import MAX_TABLE_BYTES

MAX_CSV_ROWS_PER_RANGE = 500
MAX_CSV_COLUMNS = 32
PARSER_CONTRACT_NAME = "prodocux_csv_row_projection_v1"
PARSER_CONTRACT_VERSION = "1"


def extract_csv_continuable_projection(
    payload: bytes,
    *,
    cursor: Mapping[str, Any] | None = None,
    max_rows: int = MAX_CSV_ROWS_PER_RANGE,
) -> dict[str, Any]:
    if not payload:
        raise ValueError("document payload is empty")
    if len(payload) > MAX_TABLE_BYTES:
        raise SourceTooLargeError(f"CSV exceeds {MAX_TABLE_BYTES} bytes")
    if not 1 <= max_rows <= MAX_CSV_ROWS_PER_RANGE:
        raise ValueError("max_rows must be between 1 and 500")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded") from exc
    try:
        parsed = list(csv.reader(text.splitlines()))
    except csv.Error as exc:
        raise ValueError("invalid CSV document") from exc
    source_sha256 = hashlib.sha256(payload).hexdigest()
    header = parsed[0] if parsed else []
    data_rows = parsed[1:]
    start_row = 0
    if cursor is not None:
        expected = {
            "schema_version": "prodocux_projection_cursor_v1",
            "source_sha256": source_sha256,
            "parser_contract_name": PARSER_CONTRACT_NAME,
            "parser_contract_version": PARSER_CONTRACT_VERSION,
        }
        for name, value in expected.items():
            if cursor.get(name) != value:
                raise ValueError(f"cursor {name} does not match source projection")
        start_row = cursor.get("next_row")
        if (
            not isinstance(start_row, int)
            or isinstance(start_row, bool)
            or start_row < 0
        ):
            raise ValueError("cursor next_row must be a non-negative integer")
    if start_row > len(data_rows) or (start_row == len(data_rows) and data_rows):
        raise ValueError("cursor next_row exceeds CSV row count")
    end_row = min(start_row + max_rows, len(data_rows))
    omissions: list[str] = []
    if len(header) > MAX_CSV_COLUMNS or any(
        len(row) > MAX_CSV_COLUMNS for row in data_rows[start_row:end_row]
    ):
        omissions.append("columns_beyond_limit")
    columns = header[:MAX_CSV_COLUMNS]
    rows = [row[:MAX_CSV_COLUMNS] for row in data_rows[start_row:end_row]]
    next_cursor = None
    if end_row < len(data_rows):
        next_cursor = {
            "schema_version": "prodocux_projection_cursor_v1",
            "source_sha256": source_sha256,
            "parser_contract_name": PARSER_CONTRACT_NAME,
            "parser_contract_version": PARSER_CONTRACT_VERSION,
            "next_row": end_row,
        }
    disposition = (
        "partial_unknown"
        if omissions
        else "partial_known"
        if next_cursor is not None
        else "complete"
    )
    result = {
        "schema_version": "prodocux_csv_continuable_projection_v1",
        "source_sha256": source_sha256,
        "parser_contract": {
            "name": PARSER_CONTRACT_NAME,
            "version": PARSER_CONTRACT_VERSION,
        },
        "range": {
            "unit": "row",
            "start": start_row,
            "end": end_row,
            "requested_max_rows": max_rows,
        },
        "columns": columns,
        "rows": rows,
        "next_cursor": deepcopy(next_cursor),
        "coverage": {
            "disposition": disposition,
            "known_total_rows": len(data_rows),
            "continuation_available": next_cursor is not None,
            "omitted_content_classes": omissions,
        },
        "counts": {
            "returned_rows": len(rows),
            "returned_columns": len(columns),
        },
    }
    validate_continuable_projection(result)
    return result
