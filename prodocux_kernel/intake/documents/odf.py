"""Bounded read-only ODF package projection, with original XML ordinal paths."""

import io
import re
import stat
import xml.etree.ElementTree as ET
import zipfile
from pathlib import PurePosixPath

OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
STYLE = "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}"
TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
MANIFEST = "{urn:oasis:names:tc:opendocument:xmlns:manifest:1.0}"
XLINK = "{http://www.w3.org/1999/xlink}"
PRESENTATION = "{urn:oasis:names:tc:opendocument:xmlns:presentation:1.0}"
TYPES = {"odt": "text", "ods": "spreadsheet", "odp": "presentation"}
MAX_ENTRIES = 256
MAX_EXPANDED = 8 * 1024 * 1024
MAX_XML = 2 * 1024 * 1024
MAX_NODES = 20_000
MAX_DEPTH = 32
TRACKED_HISTORY = frozenset({
    TEXT + "tracked-changes", TEXT + "deletion",
    TABLE + "tracked-changes", TABLE + "deletion",
})


def _xml(package, name):
    entry = package.getinfo(name)
    if entry.file_size > MAX_XML:
        raise ValueError("ODF_XML_SIZE_LIMIT")
    with package.open(entry) as stream:
        encoded = stream.read(MAX_XML + 1)
    if len(encoded) != entry.file_size:
        raise ValueError("ODF_XML_SIZE_MISMATCH")
    raw = encoded.decode("utf-8-sig")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", raw, re.IGNORECASE):
        raise ValueError("ODF_UNSAFE_XML")
    root = ET.fromstring(raw)
    stack = [(root, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise ValueError("ODF_XML_COMPLEXITY_LIMIT")
        stack.extend((child, depth + 1) for child in node)
    return root


def _body(payload, kind, omissions):
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        entries = package.infolist()
        if len(entries) > MAX_ENTRIES or sum(e.file_size for e in entries) > MAX_EXPANDED:
            raise ValueError("ODF_ARCHIVE_LIMIT")
        seen = set()
        for entry in entries:
            name = entry.filename
            path = PurePosixPath(name)
            if (name in seen or path.is_absolute() or ".." in path.parts or "\\" in name
                    or ":" in name or entry.flag_bits & 1
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError("ODF_UNSAFE_ARCHIVE_ENTRY")
            seen.add(name)
            if entry.file_size > 200 * max(entry.compress_size, 1):
                raise ValueError("ODF_COMPRESSION_RATIO_LIMIT")
        mime = package.getinfo("mimetype")
        expected = ("application/vnd.oasis.opendocument." + kind).encode("ascii")
        if mime.file_size != len(expected) or package.read(mime) != expected:
            raise ValueError("ODF_MEDIA_TYPE_MISMATCH")
        if "META-INF/manifest.xml" in seen:
            manifest = _xml(package, "META-INF/manifest.xml")
            if any(node.tag == MANIFEST + "encryption-data" for node in manifest.iter()):
                raise ValueError("ODF_ENCRYPTED")
        if any(name.startswith(("Scripts/", "Basic/")) for name in seen):
            omissions.add("odf_scripts_not_executed")
        style_documents = []
        if "styles.xml" in seen:
            omissions.add("odf_styles_not_projected")
            style_documents.append(_xml(package, "styles.xml"))
        document = _xml(package, "content.xml")
        style_documents.append(document)
    if document.tag != OFFICE + "document-content":
        raise ValueError("ODF_INVALID_CONTENT_ROOT")
    body = document.find(f"{OFFICE}body/{OFFICE}{kind}")
    if body is None:
        raise ValueError("ODF_BODY_TYPE_MISMATCH")
    styles = {}
    for style_document in style_documents:
        for style in style_document.iter(STYLE + "style"):
            if style.get(STYLE + "family") != "table":
                continue
            name = style.get(STYLE + "name")
            properties = style.find(STYLE + "table-properties")
            display = None if properties is None else properties.get(TABLE + "display")
            if name in styles:
                raise ValueError("ODF_AMBIGUOUS_TABLE_STYLE")
            styles[name] = display
    return body, styles


def _walk(node, path, omissions):
    for index, child in enumerate(node, 1):
        child_path = (*path, index)
        if child.get(XLINK + "href") is not None:
            omissions.add("odf_linked_resources_not_loaded")
        if child.tag in TRACKED_HISTORY:
            omissions.add("odf_tracked_change_history_excluded")
            continue
        if child.tag in {OFFICE + "annotation", PRESENTATION + "notes", OFFICE + "scripts",
                         DRAW + "object", DRAW + "object-ole", DRAW + "image"}:
            omissions.add("odf_notes_or_objects_not_projected")
            continue
        yield child, child_path
        yield from _walk(child, child_path, omissions)


def _inline(node, omissions):
    pieces = [node.text or ""]
    size = len(pieces[0])
    for child in node:
        if child.get(XLINK + "href") is not None:
            omissions.add("odf_linked_resources_not_loaded")
        previous = len(pieces)
        if child.tag in TRACKED_HISTORY:
            omissions.add("odf_tracked_change_history_excluded")
        elif child.tag in {TEXT + "span", TEXT + "a"}:
            pieces.append(_inline(child, omissions))
        elif child.tag == TEXT + "s":
            count = int(child.get(TEXT + "c", "1"))
            if not 1 <= count <= 4096:
                raise ValueError("ODF_SPACE_REPEAT_LIMIT")
            pieces.append(" " * count)
        elif child.tag == TEXT + "tab":
            pieces.append("\t")
        elif child.tag == TEXT + "line-break":
            pieces.append("\n")
        else:
            omissions.add("odf_inline_content_not_projected")
        pieces.append(child.tail or "")
        size += sum(len(piece) for piece in pieces[previous:])
        if size > 65536:
            raise ValueError("ODF_TEXT_NODE_LIMIT")
    return "".join(pieces)


def _sheet_rows(node, path):
    wrappers = {TABLE + "table-rows", TABLE + "table-header-rows", TABLE + "table-row-group"}
    for index, child in enumerate(node, 1):
        if child.tag == TABLE + "table-row":
            yield child, (*path, index)
        elif child.tag in wrappers:
            yield from _sheet_rows(child, (*path, index))


def project_odf(payload, fmt, emit, omissions):
    body, styles = _body(payload, TYPES[fmt], omissions)
    omissions.add("odf_nontext_and_layout_not_projected")
    if any(node.tag in TRACKED_HISTORY for node in body.iter()):
        omissions.add("odf_tracked_change_history_excluded")
    if fmt == "ods":
        for sheet_index, sheet in enumerate(body, 1):
            if sheet.tag != TABLE + "table":
                continue
            style_name = sheet.get(TABLE + "style-name")
            display = sheet.get(TABLE + "display", styles.get(style_name))
            if display == "false":
                omissions.add("odf_hidden_sheet_excluded")
                continue
            if style_name and display != "true":
                omissions.add("odf_sheet_style_visibility_not_evaluated")
                continue
            for row, row_path in _sheet_rows(sheet, (sheet_index,)):
                if row.get(TABLE + "number-rows-repeated", "1") != "1":
                    omissions.add("odf_repeated_cells_or_rows_not_expanded")
                for index, cell in enumerate(row, 1):
                    if cell.tag == TABLE + "covered-table-cell":
                        omissions.add("odf_covered_cells_not_projected")
                    if cell.tag != TABLE + "table-cell":
                        continue
                    if cell.get(TABLE + "number-columns-repeated", "1") != "1":
                        omissions.add("odf_repeated_cells_or_rows_not_expanded")
                    if cell.get(TABLE + "formula") is not None:
                        omissions.add("odf_formulas_not_evaluated")
                    paragraphs = [_inline(p, omissions) for p in cell if p.tag == TEXT + "p"]
                    text = "\n".join(paragraphs)
                    if not text:
                        text = next((cell.get(OFFICE + attr) for attr in (
                            "string-value", "value", "date-value", "time-value", "boolean-value"
                        ) if cell.get(OFFICE + attr) is not None), "")
                    emit(["ods-cell-xml", sheet.get(TABLE + "name", ""), *row_path, index], text)
        return
    if fmt == "odp":
        for slide, page_path in _walk(body, (), omissions):
            if slide.tag == DRAW + "page":
                for item, path in _walk(slide, page_path, omissions):
                    if item.tag in {TEXT + "p", TEXT + "h"}:
                        emit(["odp-slide-text-xml", *path], _inline(item, omissions))
        return
    for item, path in _walk(body, (), omissions):
        if item.tag in {TEXT + "p", TEXT + "h"}:
            emit(["odt-paragraph-xml", *path], _inline(item, omissions))
