"""Bounded, local-only Specialized intake experiments."""
import re
import xml.etree.ElementTree as ET
import zipfile
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath

from .structured import project_html
from .timed_text import Snapshot

LIMIT = 4 * 1024 * 1024
CONVERSION = {"rtf", "doc", "xls", "ppt"}
OCR = {"png", "jpg", "jpeg", "tiff", "pdf"}


def _path(value):
    if any(part in {"", ".", ".."} for part in value.split("/")) or re.search(r"[:\\%?#\x00-\x1f]", value):
        raise ValueError("EPUB_UNSAFE_PATH")
    return value


def _xml_text(raw):
    text = raw.decode("utf-8-sig")
    # XML comments are inert, but removing them must not join declaration tokens.
    checked = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", checked, re.IGNORECASE):
        raise ValueError("EPUB_XML_DECLARATION_REJECTED")
    return text


def _epub(raw, emit, omissions):
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 128 or sum(e.file_size for e in entries) > 2 * LIMIT:
            raise ValueError("EPUB_ARCHIVE_LIMIT")
        names = set()
        for entry in entries:
            name = _path(entry.filename.rstrip("/"))
            if name.casefold() in names or entry.flag_bits & 1 or entry.file_size > LIMIT or entry.file_size > 100 * max(entry.compress_size, 1):
                raise ValueError("EPUB_ARCHIVE_ENTRY_REJECTED")
            names.add(name.casefold())
        if archive.read("mimetype") != b"application/epub+zip":
            raise ValueError("EPUB_MIMETYPE_INVALID")
        if "meta-inf/encryption.xml" in names:
            raise ValueError("EPUB_ENCRYPTED")

        def xml(name):
            content = _xml_text(archive.read(name))
            return ET.fromstring(content)

        container = xml("META-INF/container.xml")
        roots = container.findall("./{*}rootfiles/{*}rootfile")
        if len(roots) != 1:
            raise ValueError("EPUB_PACKAGE_AMBIGUOUS")
        package_path = _path(roots[0].attrib["full-path"])
        package = xml(package_path)
        manifest = {}
        for item in package.findall("./{*}manifest/{*}item"):
            key = item.attrib["id"]
            if key in manifest:
                raise ValueError("EPUB_DUPLICATE_ITEM")
            manifest[key] = item.attrib
        spine = package.findall("./{*}spine/{*}itemref")
        if not spine or len(spine) > 64:
            raise ValueError("EPUB_SPINE_LIMIT")
        omissions.add("epub_non_spine_resources_not_projected")
        for ordinal, ref in enumerate(spine, 1):
            item = manifest[ref.attrib["idref"]]
            if item["media-type"] != "application/xhtml+xml" or ref.get("linear") == "no":
                omissions.add("epub_unsupported_or_nonlinear_spine_item")
                continue
            name = str(PurePosixPath(package_path).parent / _path(item["href"]))
            content = _xml_text(archive.read(name))
            ET.fromstring(content)
            project_html(content, lambda loc, text, ordinal=ordinal, name=name: emit([ordinal, name, loc], text), omissions)


def project(fmt, raw):
    if not 0 < len(raw) <= LIMIT:
        raise ValueError("INTAKE_SOURCE_SIZE_LIMIT")
    if fmt in CONVERSION:
        raise ValueError("ISOLATED_CONVERTER_REQUIRED")
    if fmt in OCR:
        raise ValueError("OPT_IN_OCR_BACKEND_REQUIRED")
    items, omissions = [], set()
    used = 0

    def emit(locator, text):
        nonlocal used
        used += len(text.encode("utf-8")) + len(repr(locator).encode("utf-8"))
        if len(items) >= 4096 or used > LIMIT:
            raise ValueError("INTAKE_PROJECTION_LIMIT")
        items.append({"locator": locator, "text": text})

    if fmt == "epub":
        try:
            _epub(raw, emit, omissions)
        except (KeyError, ET.ParseError, zipfile.BadZipFile, UnicodeError, NotImplementedError) as exc:
            raise ValueError("EPUB_MALFORMED") from exc
    elif fmt in {"srt", "webvtt"}:
        snapshot = Snapshot(raw, fmt)
        previous = -1
        ids = set()
        cursor = None
        while True:
            page = snapshot.read(cursor=cursor)
            for loc, _, meta in page["records"]:
                start, end = meta["start_ms"], meta["end_ms"]
                cue_id, payload = meta["cue_id"], meta["payload"]
                if start < previous:
                    raise ValueError("CUE_START_ORDER")
                if cue_id is not None and cue_id in ids:
                    raise ValueError("DUPLICATE_CUE_ID")
                ids.add(cue_id)
                if meta["settings"] or re.search(r"[<>]", payload):
                    raise ValueError("CUE_MARKUP_OR_SETTINGS_UNSUPPORTED")
                previous = start
                emit([loc.ordinal, loc.start, loc.end, start, end], payload)
            cursor = page["next"]
            if cursor is None:
                break
    else:
        raise ValueError("INTAKE_FORMAT_UNSUPPORTED")
    return {"source_sha256": sha256(raw).hexdigest(), "parser": f"prodocux_{fmt}_projection_v1",
            "items": items, "omissions": sorted(omissions)}


def resolve(fmt, raw, source_digest, parser, locator, quote_digest):
    if sha256(raw).hexdigest() != source_digest or parser != f"prodocux_{fmt}_projection_v1":
        raise ValueError("SOURCE_OR_PARSER_MISMATCH")
    for item in project(fmt, raw)["items"]:
        if item["locator"] == locator:
            quote = item["text"]
            if sha256(quote.encode("utf-8")).hexdigest() != quote_digest:
                raise ValueError("QUOTE_DIGEST_MISMATCH")
            return quote
    raise ValueError("LOCATOR_NOT_FOUND")
