"""Deterministic tabular intake primitives (no semantic interpretation)."""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
from typing import Any

TABLE_PROFILE_SCHEMA = "prodocux_table_profile_v1"
MAX_TABLE_BYTES = 8 * 1024 * 1024


def parse_csv_records(text: str, *, contract_version: str) -> list[list[str]]:
    if contract_version == "1":
        return list(csv.reader(text.splitlines()))
    if contract_version == "2":
        # newline="" preserves embedded LF, CRLF and CR in quoted fields.
        return list(csv.reader(io.StringIO(text, newline=""), strict=True))
    raise ValueError("unsupported CSV parser contract version")


def profile_csv_bytes(
    raw: bytes, *, filename: str, contract_version: str = "1",
) -> dict[str, Any]:
    """Return a language-neutral CSV profile with source provenance."""
    if len(raw) > MAX_TABLE_BYTES:
        raise ValueError(f"CSV exceeds {MAX_TABLE_BYTES} bytes")
    text = raw.decode("utf-8-sig")
    rows = parse_csv_records(text, contract_version=contract_version)
    columns = rows[0] if rows else []
    data_rows = rows[1:]
    return {
        "schema_version": f"prodocux_table_profile_v{contract_version}",
        "source": {
            "name": Path(filename).name,
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "columns": columns,
        "row_count": len(data_rows),
        "preview": [dict(zip(columns, row)) for row in data_rows[:10]],
        "interpretation": "none",
    }


def profile_csv(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    return profile_csv_bytes(source.read_bytes(), filename=source.name)
