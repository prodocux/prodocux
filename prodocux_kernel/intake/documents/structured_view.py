"""Bounded capability inventory, deterministic projection and quote replay."""

import json
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from hashlib import sha256
from pathlib import Path

from .eml import project_eml
from .odf import project_odf
from .structured import MAX_TEXT_SOURCE, project_html, project_json

MEDIA = {
    ".html": "text/html", ".htm": "text/html", ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".eml": "message/rfc822",
}
MAX_ITEMS = 20_000
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_LOCATOR_BYTES = 4096
MAX_ODF_SOURCE = 4 * 1024 * 1024


def capabilities():
    return {"schema_version": "prodocux_format_capabilities_v1", "profiles": [
        {"extension": extension, "media_type_hint": media,
         "parser_contract": _contract(_format(extension)),
         "max_inline_bytes": _source_limit(_format(extension)),
         "operations": ["inspect", "project", "resolve_quote"],
         "continuation": False}
        for extension, media in MEDIA.items()
    ]}


def _format(suffix):
    return "html" if suffix == ".htm" else suffix[1:]


def _contract(fmt):
    return {"name": f"prodocux_{fmt}_projection_v1", "version": "1"}


def _source_limit(fmt):
    return MAX_ODF_SOURCE if fmt in {"odt", "ods", "odp"} else MAX_TEXT_SOURCE


def inspect(filename, payload):
    suffix = Path(filename).suffix.lower()
    if suffix not in MEDIA:
        raise ValueError("INTAKE_FORMAT_UNSUPPORTED")
    fmt = _format(suffix)
    if not payload or len(payload) > _source_limit(fmt):
        raise ValueError("INTAKE_SOURCE_SIZE_LIMIT")
    return {"format_hint": fmt, "source_sha256": sha256(payload).hexdigest(),
            "size_bytes": len(payload), "parser_contract": _contract(fmt),
            "media_type_hint": MEDIA[suffix], "payload_validated": False}


def project(filename, payload):
    source = inspect(filename, payload)
    fmt = source["format_hint"]
    omissions = set()
    items = []
    locators = set()
    output_size = 0

    def emit(locator, text):
        nonlocal output_size
        if not text.strip():
            return
        if "\0" in text:
            raise ValueError("INTAKE_NUL_TEXT")
        key = json.dumps(locator, ensure_ascii=False, separators=(",", ":"))
        key_size = len(key.encode("utf-8"))
        output_size += key_size + len(text.encode("utf-8"))
        if key_size > MAX_LOCATOR_BYTES or len(items) >= MAX_ITEMS or output_size > MAX_OUTPUT_BYTES:
            raise ValueError("INTAKE_PROJECTION_LIMIT")
        if key in locators:
            raise ValueError("INTAKE_DUPLICATE_LOCATOR")
        locators.add(key)
        items.append({"source_locator": key, "text": text, "type": locator[0]})

    metadata = {}
    try:
        if fmt == "html":
            project_html(payload.decode("utf-8-sig"), emit, omissions)
        elif fmt in {"json", "jsonl"}:
            project_json(payload, emit, lines=fmt == "jsonl")
        elif fmt in {"odt", "ods", "odp"}:
            project_odf(payload, fmt, emit, omissions)
        else:
            metadata = project_eml(payload, emit, omissions)
        if output_size + len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise ValueError("INTAKE_PROJECTION_LIMIT")
    except UnicodeError as exc:
        raise ValueError("INTAKE_INVALID_UNICODE") from exc
    except (zipfile.BadZipFile, ET.ParseError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("INTAKE_MALFORMED_SOURCE") from exc
    return {"source": {**source, "payload_validated": True}, "text_items": items,
            "coverage": {"disposition": "partial_unknown" if omissions else "complete",
                         "omitted_content_classes": sorted(omissions)},
            "metadata": metadata}


def project_admitted(filename, payload, *, eml_timeout=2.0):
    """Apply the admission deadline before a mail projection can publish."""
    if Path(filename).suffix.lower() != ".eml":
        return project(filename, payload)
    identity = inspect(filename, payload)
    if not 0 < eml_timeout <= 2:
        raise ValueError("EML_INVALID_WORKER_DEADLINE")
    worker = Path(__file__).with_name("eml_worker.py")
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(worker)],
            input=payload, capture_output=True, timeout=eml_timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("EML_PARSE_TIMEOUT") from exc
    if result.returncode:
        raise ValueError("EML_WORKER_FAILED")
    try:
        envelope = json.loads(result.stdout)
        if "error" in envelope:
            raise ValueError(envelope["error"])
        projection = envelope["projection"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("EML_WORKER_PROTOCOL_ERROR") from exc
    if projection["source"] != {**identity, "payload_validated": True}:
        raise ValueError("EML_WORKER_SOURCE_MISMATCH")
    return projection


def resolve_quote(filename, payload, *, source_sha256, parser_contract, locator,
                  quote_start, quote_end, quote_sha256):
    """Replay a trusted caller's citation against the original source bytes."""
    identity = inspect(filename, payload)
    if identity["source_sha256"] != source_sha256:
        raise ValueError("STALE_SOURCE")
    if identity["parser_contract"] != parser_contract:
        raise ValueError("PARSER_CONTRACT_MISMATCH")
    projection = project_admitted(filename, payload)
    item = next((item for item in projection["text_items"]
                 if item["source_locator"] == locator), None)
    if item is None:
        raise ValueError("LOCATOR_UNAVAILABLE")
    text = unicodedata.normalize("NFC", item["text"])
    if (type(quote_start) is not int or type(quote_end) is not int
            or not 0 <= quote_start < quote_end <= len(text)):
        raise ValueError("INVALID_QUOTE_SPAN")
    quote = text[quote_start:quote_end]
    if sha256(quote.encode("utf-8")).hexdigest() != quote_sha256:
        raise ValueError("QUOTE_DIGEST_MISMATCH")
    return quote
