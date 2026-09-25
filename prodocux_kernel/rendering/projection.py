"""Deterministic, source-bound continuation for document block projections."""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..intake.archive import validate_office_archive
from ..intake.docx import MAX_DOCX_BYTES
from .errors import (
    CONTINUATION_INVALID,
    CONTINUATION_NOT_SUPPORTED,
    CONTINUATION_SOURCE_MISMATCH,
    REQUEST_INVALID,
    RenderContractError,
)
from .extract import (
    MAX_BLOCKS,
    MAX_COLS,
    MAX_PARAGRAPHS,
    MAX_ROWS,
    MAX_TEXT,
    flatten_text_items,
)
from .validate import validate_content_blocks, validate_continuable_projection_result

CONTENT_SCHEMA = "prodocux_content_blocks_v1"
PARSER_CONTRACT = "prodocux_docx_block_projection_v1"
CURSOR_VERSION = "prodocux_projection_cursor_v1"


def _validate_cursor(cursor: Mapping[str, Any], *, source_sha256: str) -> int:
    required = {
        "schema_version",
        "source_sha256",
        "format",
        "parser_contract_name",
        "parser_contract_version",
        "next_block",
    }
    if set(cursor) != required:
        raise RenderContractError(
            CONTINUATION_INVALID, "continuation cursor shape is invalid"
        )
    if cursor.get("schema_version") != CURSOR_VERSION:
        raise RenderContractError(
            CONTINUATION_INVALID, "continuation cursor version is unsupported"
        )
    if cursor.get("source_sha256") != source_sha256:
        raise RenderContractError(
            CONTINUATION_SOURCE_MISMATCH, "continuation source digest changed"
        )
    if (
        cursor.get("format") != "docx"
        or cursor.get("parser_contract_name") != PARSER_CONTRACT
        or cursor.get("parser_contract_version") != "1"
    ):
        raise RenderContractError(
            CONTINUATION_INVALID, "continuation cursor parser binding is invalid"
        )
    next_block = cursor.get("next_block")
    if (
        not isinstance(next_block, int)
        or isinstance(next_block, bool)
        or next_block < 1
    ):
        raise RenderContractError(
            CONTINUATION_INVALID, "continuation block offset is invalid"
        )
    return next_block


@dataclass
class _Disclosure:
    omitted: set[str] = field(default_factory=set)
    warnings: set[str] = field(default_factory=set)
    unknown_scope: bool = False

    def clip(self, text: str, content_class: str) -> str:
        sanitized = text.replace("\x00", "").strip()
        if len(sanitized) > MAX_TEXT:
            self.omitted.add(content_class)
            self.warnings.add("TEXT_CLIPPED_TO_KERNEL_LIMIT")
            self.unknown_scope = True
        return sanitized[:MAX_TEXT]


_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _has_projectable_xml_text(root: ElementTree.Element) -> bool:
    text_tags = {f"{{{_WORD_NS}}}t", f"{{{_WORD_NS}}}instrText"}
    structural_tags = {
        f"{{{_WORD_NS}}}tbl",
        f"{{{_WORD_NS}}}drawing",
        f"{{{_WORD_NS}}}pict",
    }
    return any(
        element.tag in structural_tags
        or (element.tag in text_tags and (element.text or "").strip())
        for element in root.iter()
    )


def _detect_non_body_content(payload: bytes, disclosure: _Disclosure) -> None:
    """Disclose meaningful DOCX story parts excluded from this parser scope."""
    categories: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            category: str | None = None
            if name.startswith("word/header"):
                category = "headers"
            elif name.startswith("word/footer"):
                category = "footers"
            elif name == "word/comments.xml":
                category = "comments"
            elif name == "word/footnotes.xml":
                category = "footnotes"
            elif name == "word/endnotes.xml":
                category = "endnotes"
            if category is None:
                continue
            root = ElementTree.fromstring(archive.read(name))
            if category in {"footnotes", "endnotes"}:
                note_tag = f"{{{_WORD_NS}}}{category[:-1]}"
                id_key = f"{{{_WORD_NS}}}id"
                meaningful = any(
                    note.get(id_key) not in {"-1", "0"}
                    and _has_projectable_xml_text(note)
                    for note in root.iter(note_tag)
                )
            else:
                meaningful = _has_projectable_xml_text(root)
            if meaningful:
                categories.add(category)
    for category in categories:
        disclosure.omitted.add(f"docx_{category}")
        disclosure.warnings.add(f"DOCX_{category.upper()}_NOT_PROJECTED")
    if categories:
        disclosure.unknown_scope = True


def _detect_body_omissions(document: Any, disclosure: _Disclosure) -> None:
    from docx.oxml.ns import qn

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p") and child.xpath(".//w:drawing | .//w:pict"):
            disclosure.omitted.add("embedded_graphics")
            disclosure.warnings.add("EMBEDDED_GRAPHICS_NOT_PROJECTED")
            disclosure.unknown_scope = True
        elif child.tag not in {qn("w:p"), qn("w:tbl"), qn("w:sectPr")}:
            disclosure.omitted.add("unsupported_docx_body_elements")
            disclosure.warnings.add("UNSUPPORTED_DOCX_BODY_ELEMENT_NOT_PROJECTED")
            disclosure.unknown_scope = True


def _block_metrics(block: Mapping[str, Any]) -> tuple[int, int]:
    """Return projected table-row and UTF-8 text-byte counts for one block."""
    kind = block.get("type")
    if kind == "heading":
        texts = [str(block.get("text") or "")]
        rows = 0
    elif kind == "paragraphs":
        texts = [str(value) for value in block.get("paragraphs") or []]
        rows = 0
    elif kind == "table":
        table_rows = (block.get("table") or {}).get("rows") or []
        texts = [str(cell) for row in table_rows for cell in row]
        rows = len(table_rows)
    else:
        texts = []
        rows = 0
    return rows, sum(len(text.encode("utf-8")) for text in texts)


def _docx_blocks(payload: bytes, disclosure: _Disclosure) -> Iterator[dict[str, Any]]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    validate_office_archive(
        payload, label="DOCX", invalid_message="invalid DOCX document"
    )
    document = Document(io.BytesIO(payload))
    _detect_non_body_content(payload, disclosure)
    _detect_body_omissions(document, disclosure)
    sequence = 0
    pending: list[str] = []

    def identifier(prefix: str) -> str:
        nonlocal sequence
        sequence += 1
        return f"{prefix}{sequence}"

    def paragraph_block() -> dict[str, Any] | None:
        if not pending:
            return None
        block = {
            "id": identifier("p"),
            "type": "paragraphs",
            "paragraphs": list(pending),
        }
        pending.clear()
        return block

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            text = disclosure.clip(paragraph.text, "paragraph_text_beyond_limit")
            if not text:
                continue
            style = paragraph.style.name if paragraph.style is not None else ""
            if style.casefold().startswith("heading"):
                block = paragraph_block()
                if block is not None:
                    yield block
                digits = "".join(char for char in style if char.isdigit())
                level = max(1, min(6, int(digits))) if digits else 1
                yield {
                    "id": identifier("h"),
                    "type": "heading",
                    "level": level,
                    "text": text,
                }
            else:
                if len(pending) >= MAX_PARAGRAPHS:
                    block = paragraph_block()
                    if block is not None:
                        yield block
                pending.append(text)
        elif child.tag == qn("w:tbl"):
            block = paragraph_block()
            if block is not None:
                yield block
            table = Table(child, document)
            rows: list[list[str]] = []
            if len(table.rows) > MAX_ROWS:
                disclosure.omitted.add("table_rows_beyond_limit")
                disclosure.warnings.add("TABLE_ROWS_CLIPPED_TO_KERNEL_LIMIT")
                disclosure.unknown_scope = True
            for row in table.rows[:MAX_ROWS]:
                if len(row.cells) > MAX_COLS:
                    disclosure.omitted.add("table_columns_beyond_limit")
                    disclosure.warnings.add("TABLE_COLUMNS_CLIPPED_TO_KERNEL_LIMIT")
                    disclosure.unknown_scope = True
                values = [
                    disclosure.clip(cell.text, "table_cell_text_beyond_limit")
                    for cell in row.cells[:MAX_COLS]
                ]
                while len(values) > 1 and values[-1] == "":
                    values.pop()
                rows.append(values or [""])
            if rows:
                yield {
                    "id": identifier("t"),
                    "type": "table",
                    "table": {"header_rows": 1 if len(rows) > 1 else 0, "rows": rows},
                }
    block = paragraph_block()
    if block is not None:
        yield block
    if sequence == 0:
        yield {"id": identifier("h"), "type": "heading", "level": 1, "text": "Document"}


def extract_continuable_projection(
    filename: str,
    payload: bytes,
    *,
    cursor: Mapping[str, Any] | None = None,
    max_blocks: int = MAX_BLOCKS,
) -> dict[str, Any]:
    """Return the next deterministic DOCX block range bound to exact source bytes."""
    name = Path(filename).name
    if name != filename or name in {".", ".."}:
        raise RenderContractError(
            REQUEST_INVALID, "document_filename must be a plain basename"
        )
    if Path(name).suffix.casefold() != ".docx":
        raise RenderContractError(
            CONTINUATION_NOT_SUPPORTED,
            "continuable block projection currently supports DOCX only",
        )
    if len(payload) > MAX_DOCX_BYTES:
        raise RenderContractError(REQUEST_INVALID, "document exceeds DOCX byte limit")
    if (
        not isinstance(max_blocks, int)
        or isinstance(max_blocks, bool)
        or not 1 <= max_blocks <= MAX_BLOCKS
    ):
        raise RenderContractError(
            REQUEST_INVALID, f"max_blocks must be between 1 and {MAX_BLOCKS}"
        )

    source_sha256 = hashlib.sha256(payload).hexdigest()
    start = (
        _validate_cursor(cursor, source_sha256=source_sha256)
        if cursor is not None
        else 0
    )
    disclosure = _Disclosure()
    page: list[dict[str, Any]] = []
    has_more = False
    observed_total = 0
    processed_table_rows = 0
    processed_text_bytes = 0
    for index, block in enumerate(_docx_blocks(payload, disclosure)):
        observed_total = index + 1
        if index < start:
            rows, text_bytes = _block_metrics(block)
            processed_table_rows += rows
            processed_text_bytes += text_bytes
            continue
        if len(page) < max_blocks:
            page.append(block)
            rows, text_bytes = _block_metrics(block)
            processed_table_rows += rows
            processed_text_bytes += text_bytes
            continue
        has_more = True
        break
    if start and not page:
        raise RenderContractError(
            CONTINUATION_INVALID, "continuation cursor is beyond document end"
        )

    end = start + len(page)
    content = {
        "schema_version": CONTENT_SCHEMA,
        "document": {"title": Path(name).stem[:512] or "Document"},
        "blocks": page,
    }
    validate_content_blocks(content)
    next_cursor = None
    if has_more:
        next_cursor = {
            "schema_version": CURSOR_VERSION,
            "source_sha256": source_sha256,
            "format": "docx",
            "parser_contract_name": PARSER_CONTRACT,
            "parser_contract_version": "1",
            "next_block": end,
        }
    known_total: int | None
    if disclosure.unknown_scope:
        disposition = "partial_unknown"
        known_total = None if has_more else observed_total
    elif has_more:
        disposition = "partial_unknown"
        known_total = None
    elif disclosure.omitted:
        disposition = "partial_known"
        known_total = observed_total
    else:
        disposition = "complete"
        known_total = observed_total

    from .. import __version__

    result: dict[str, Any] = {
        "schema_version": "prodocux_continuable_projection_v1",
        "kernel_version": __version__,
        "parser_contract": {
            "name": PARSER_CONTRACT,
            "version": "1",
            "distribution": "prodocux",
            "distribution_version": __version__,
        },
        "source": {
            "sha256": source_sha256,
            "size_bytes": len(payload),
            "format": "docx",
        },
        "range": {
            "unit": "block",
            "start": start,
            "end_exclusive": end,
            "returned_blocks": len(page),
            "requested_max_blocks": max_blocks,
        },
        "coverage": {
            "disposition": disposition,
            "continuation_available": has_more,
            "known_total_blocks": known_total,
            "omitted_content_classes": sorted(disclosure.omitted),
            "warnings": sorted(disclosure.warnings),
        },
        "counts": {
            "processed_through_range_end": {
                "pages": None,
                "blocks": end,
                "table_rows": processed_table_rows,
                "text_utf8_bytes": processed_text_bytes,
            },
            "known_total": {
                "pages": None,
                "blocks": known_total,
                "table_rows": processed_table_rows if not has_more else None,
                "text_utf8_bytes": processed_text_bytes if not has_more else None,
            },
        },
        "ocr_disposition": "not_applicable",
        "content": content,
        "text_items": flatten_text_items(content),
        "next_cursor": next_cursor,
    }
    return validate_continuable_projection_result(result, request_cursor=cursor)
