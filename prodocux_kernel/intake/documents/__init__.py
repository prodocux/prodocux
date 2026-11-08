"""Inspect, bounded read and source resolution for portable text formats."""
import json
import unicodedata
from hashlib import sha256
from pathlib import Path

from ..text_projection import read as read_lines
from ..text_projection import resolve as resolve_line
from .specialized import project as project_specialized
from .structured_view import MEDIA, project_admitted
from .structured_view import inspect as inspect_structured

TEXT = {".txt": "txt", ".md": "markdown", ".markdown": "markdown", ".log": "log", ".tsv": "tsv"}
SPECIAL = {".epub": "epub", ".srt": "srt", ".vtt": "webvtt", ".webvtt": "webvtt"}
OPTIONAL = {".rtf", ".doc", ".xls", ".ppt", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
EXISTING = {".pdf", ".docx", ".xlsx", ".pptx", ".csv"}
MAX_SOURCE = 4 * 1024 * 1024


class ByteSnapshot:
    def __init__(self, payload):
        self.payload = payload
        self.size = len(payload)
        self.source_sha256 = sha256(payload).hexdigest()

    def read_at(self, offset, limit):
        return self.payload[offset:offset + limit]


def inspect_document(filename, payload):
    if Path(filename).name != filename or not filename or any(c in filename for c in ("/", chr(92), ":")):
        raise ValueError("INVALID_DOCUMENT_FILENAME")
    if not payload:
        raise ValueError("SOURCE_EMPTY")
    if len(payload) > MAX_SOURCE:
        raise ValueError("SOURCE_TOO_LARGE")
    suffix = Path(filename).suffix.lower()
    result = {"source_sha256": sha256(payload).hexdigest(), "size_bytes": len(payload),
              "extension": suffix, "payload_validated": False}
    if suffix in MEDIA:
        info = inspect_structured(filename, payload)
        return {**result, "admission": "portable", "parser_contract": info["parser_contract"],
                "max_inline_bytes": 4 * 1024 * 1024 if suffix in {".odt", ".ods", ".odp"} else 1024 * 1024}
    if suffix in TEXT:
        return {**result, "admission": "portable", "parser_contract":
                {"name": "prodocux_utf8_line_projection_v1", "version": "1"}}
    if suffix in SPECIAL:
        return {**result, "admission": "portable", "parser_contract":
                {"name": f"prodocux_{SPECIAL[suffix]}_projection_v1", "version": "1"}}
    return {**result, "admission": "existing_projection_api" if suffix in EXISTING else
            "optional_backend" if suffix in OPTIONAL else "unsupported"}


def read_document(filename, payload, *, cursor=None, max_bytes=65536, max_records=512):
    info = inspect_document(filename, payload)
    suffix = info["extension"]
    if info["admission"] != "portable":
        raise ValueError("USE_EXISTING_PROJECTION_API" if suffix in EXISTING else "OPTIONAL_BACKEND_REQUIRED"
                         if suffix in OPTIONAL else "FORMAT_UNSUPPORTED")
    if suffix in TEXT:
        page = read_lines(ByteSnapshot(payload), TEXT[suffix], cursor=cursor,
                          max_bytes=max_bytes, max_records=max_records)
        items = [{"source_locator": json.dumps(row["locator"], ensure_ascii=False, separators=(",", ":")),
                  "text": row["text"], "type": "physical_line"} for row in page["records"]]
        return {"schema_version": "prodocux_document_read_v1",
                "source": {**info, "payload_validated": True}, "parser_contract": info["parser_contract"],
                "text_items": items, "next_cursor": page["next_cursor"],
                "coverage": {"disposition": "complete" if page["complete"] else "partial_unknown",
                             "omitted_content_classes": []}, "metadata": {}}
    if cursor is not None:
        raise ValueError("FORMAT_CONTINUATION_UNSUPPORTED")
    if suffix in MEDIA:
        result = project_admitted(filename, payload)
        items, coverage, metadata = result["text_items"], result["coverage"], result["metadata"]
    else:
        result = project_specialized(SPECIAL[suffix], payload)
        items = [{"source_locator": json.dumps(row["locator"], ensure_ascii=False, separators=(",", ":")),
                  "text": row["text"], "type": "source_unit"} for row in result["items"]]
        coverage = {"disposition": "partial_unknown" if result["omissions"] else "complete",
                    "omitted_content_classes": result["omissions"]}
        metadata = {}
    if (type(max_bytes) is not int or type(max_records) is not int
            or not 1 <= max_bytes <= 2 * 1024 * 1024 or not 1 <= max_records <= 20000):
        raise ValueError("INVALID_READ_BUDGET")
    if len(items) > max_records or sum(len(item["text"].encode("utf-8")) for item in items) > max_bytes:
        raise ValueError("DOCUMENT_OUTPUT_LIMIT")
    return {"schema_version": "prodocux_document_read_v1",
            "source": {**info, "payload_validated": True}, "parser_contract": info["parser_contract"],
            "text_items": items, "next_cursor": None, "coverage": coverage, "metadata": metadata}


def resolve_document(filename, payload, *, source_sha256, parser_contract, locator,
                     quote_start, quote_end, quote_sha256):
    info = inspect_document(filename, payload)
    if source_sha256 != info["source_sha256"]:
        raise ValueError("SOURCE_MISMATCH")
    if parser_contract != info.get("parser_contract"):
        raise ValueError("PARSER_CONTRACT_MISMATCH")
    suffix = info["extension"]
    if suffix in TEXT:
        text = resolve_line(ByteSnapshot(payload), TEXT[suffix], json.loads(locator))
    else:
        result = read_document(filename, payload)
        item = next((row for row in result["text_items"] if row["source_locator"] == locator), None)
        if item is None:
            raise ValueError("LOCATOR_UNAVAILABLE")
        text = item["text"]
    text = unicodedata.normalize("NFC", text)
    if type(quote_start) is not int or type(quote_end) is not int or not 0 <= quote_start < quote_end <= len(text):
        raise ValueError("INVALID_QUOTE_RANGE")
    quote = text[quote_start:quote_end]
    if sha256(quote.encode("utf-8")).hexdigest() != quote_sha256:
        raise ValueError("QUOTE_DIGEST_MISMATCH")
    return quote


def document_capabilities():
    return {"schema_version": "prodocux_document_capabilities_v1",
            "portable_extensions": sorted(set(MEDIA) | set(TEXT) | set(SPECIAL)),
            "existing_projection_extensions": sorted(EXISTING),
            "optional_backend_extensions": sorted(OPTIONAL),
            "max_inline_bytes": MAX_SOURCE,
            "continuable_extensions": sorted(TEXT),
            "office_contract_versions": {"csv": ["1", "2"], "xlsx": ["1", "2"]},
            "network_access": False}
