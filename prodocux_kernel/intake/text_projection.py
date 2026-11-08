"""Bounded bounded UTF-8 read operations over a authorized snapshot."""

from hashlib import sha256
from typing import Protocol

PROFILE = "prodocux_utf8_line_projection_v1"
FORMATS = frozenset({"txt", "markdown", "log", "tsv"})
MAX_BYTES = 64 * 1024
MAX_RECORDS = 512
MAX_LINE_BYTES = 8192


class Snapshot(Protocol):
    size: int
    source_sha256: str

    def read_at(self, offset: int, limit: int) -> bytes: ...


def inspect(snapshot: Snapshot, format_name: str) -> dict:
    if format_name not in FORMATS:
        raise ValueError("UNSUPPORTED_TEXT_FORMAT")
    prefix = snapshot.read_at(0, min(snapshot.size, 3))
    return {
        "parser_contract": {"name": PROFILE, "version": "1"},
        "format": format_name,
        "source_sha256": snapshot.source_sha256,
        "size_bytes": snapshot.size,
        "encoding": "utf-8",
        "bom_bytes": 3 if prefix == b"\xef\xbb\xbf" else 0,
    }


def _decode(raw: bytes, offset: int) -> str:
    data = raw.removesuffix(b"\n")
    if raw.endswith(b"\n"):
        data = data.removesuffix(b"\r")
    if b"\r" in data or b"\0" in data:
        raise ValueError("UNSUPPORTED_LINE_CONTENT")
    if len(raw) > MAX_LINE_BYTES:
        raise ValueError("LINE_EXCEEDS_BUDGET")
    return data.decode("utf-8-sig" if offset == 0 else "utf-8", errors="strict")


def _binding(snapshot, format_name):
    return {"source_sha256": snapshot.source_sha256, "format": format_name, "profile": PROFILE}


def read(snapshot: Snapshot, format_name: str, *, cursor=None,
         max_bytes=MAX_BYTES, max_records=MAX_RECORDS) -> dict:
    if format_name not in FORMATS:
        raise ValueError("UNSUPPORTED_TEXT_FORMAT")
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
        raise ValueError("INVALID_BYTE_BUDGET")
    if type(max_records) is not int or not 1 <= max_records <= MAX_RECORDS:
        raise ValueError("INVALID_RECORD_BUDGET")
    binding = _binding(snapshot, format_name)
    offset, line = 0, 1
    if cursor is not None:
        if any(cursor.get(key) != value for key, value in binding.items()):
            raise ValueError("STALE_CURSOR")
        offset, line = cursor.get("offset"), cursor.get("line")
        if (type(offset) is not int or not 0 < offset < snapshot.size
                or type(line) is not int or line < 2
                or snapshot.read_at(offset - 1, 1) != b"\n"):
            raise ValueError("INVALID_CURSOR")
    length = min(max_bytes, snapshot.size - offset)
    window = snapshot.read_at(offset, length)
    if len(window) != length:
        raise ValueError("INCOMPLETE_SNAPSHOT_READ")
    records = []
    position = 0
    while position < len(window) and len(records) < max_records:
        newline = window.find(b"\n", position)
        if newline < 0 and offset + len(window) < snapshot.size:
            if not records:
                raise ValueError("LINE_EXCEEDS_BUDGET")
            break
        end = len(window) if newline < 0 else newline + 1
        raw = window[position:end]
        text = _decode(raw, offset + position)
        locator = {**binding, "start": offset + position, "end": offset + end,
                   "line": line, "raw_sha256": sha256(raw).hexdigest()}
        record = {"locator": locator, "text": text}
        if format_name == "tsv":
            record["fields"] = text.split("\t")
        records.append(record)
        position, line = end, line + 1
    end = offset + position
    return {"records": records, "start": offset, "end": end,
            "examined_bytes": len(window), "complete": end == snapshot.size,
            "next_cursor": None if end == snapshot.size else {**binding, "offset": end, "line": line}}


def resolve(snapshot: Snapshot, format_name: str, locator: dict) -> str:
    if format_name not in FORMATS:
        raise ValueError("UNSUPPORTED_TEXT_FORMAT")
    if any(locator.get(key) != value for key, value in _binding(snapshot, format_name).items()):
        raise ValueError("STALE_LOCATOR")
    start, end = locator.get("start"), locator.get("end")
    if (type(start) is not int or type(end) is not int
            or not 0 <= start < end <= snapshot.size or end - start > MAX_LINE_BYTES
            or (start and snapshot.read_at(start - 1, 1) != b"\n")):
        raise ValueError("INVALID_LOCATOR")
    raw = snapshot.read_at(start, end - start)
    if len(raw) != end - start or sha256(raw).hexdigest() != locator.get("raw_sha256"):
        raise ValueError("SOURCE_RANGE_DIGEST_MISMATCH")
    if b"\n" in raw[:-1] or (end < snapshot.size and not raw.endswith(b"\n")):
        raise ValueError("INVALID_LOCATOR")
    return _decode(raw, start)
