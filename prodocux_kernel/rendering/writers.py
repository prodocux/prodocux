"""Deterministic 5-format writers from ``prodocux_content_blocks_v1`` (no templates required)."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping
from typing import Any

from .errors import FORMAT_NOT_SUPPORTED, RenderContractError
from .limits import FORMAT_MAX_BYTES
from .media import assert_magic_matches_format

MAX_TEXT = 8192
_SHEET_FORBIDDEN = re.compile(r'[\\/?*\[\]:]')


def write_content_blocks(content: Mapping[str, Any], target_format: str) -> bytes:
    writers = {
        "csv": _write_csv,
        "xlsx": _write_xlsx,
        "docx": _write_docx,
        "pptx": _write_pptx,
        "pdf": _write_pdf,
    }
    writer = writers.get(target_format)
    if writer is None:
        raise RenderContractError(FORMAT_NOT_SUPPORTED, "target_format is not supported")
    payload = writer(content)
    if len(payload) > FORMAT_MAX_BYTES[target_format]:
        raise RenderContractError(
            FORMAT_NOT_SUPPORTED,
            "rendered payload exceeds format byte limit",
        )
    assert_magic_matches_format(payload, target_format)
    return payload


def _clip(text: Any, limit: int = MAX_TEXT) -> str:
    return str(text or "").replace("\x00", "")[:limit]


def _blocks(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(block) for block in (content.get("blocks") or [])]


def _sheet_name(raw: str, used: set[str]) -> str:
    name = _SHEET_FORBIDDEN.sub("-", raw).strip() or "Sheet"
    name = name[:31]
    candidate = name
    index = 2
    while candidate.casefold() in {item.casefold() for item in used}:
        suffix = f"-{index}"
        candidate = f"{name[: max(1, 31 - len(suffix))]}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def _first_table_rows(content: Mapping[str, Any]) -> list[list[str]]:
    for block in _blocks(content):
        if block.get("type") in {"sheet", "table"}:
            rows = (block.get("table") or {}).get("rows") or []
            if rows:
                return [[_clip(cell) for cell in row] for row in rows]
    rows: list[list[str]] = []
    for block in _blocks(content):
        kind = block.get("type")
        if kind == "heading":
            rows.append([_clip(block.get("text"))])
        elif kind == "paragraphs":
            rows.extend([_clip(item)] for item in block.get("paragraphs") or [])
        elif kind == "key_values":
            rows.extend(
                [_clip(pair.get("label")), _clip(pair.get("value"))]
                for pair in block.get("pairs") or []
            )
        elif kind == "slide":
            rows.append([_clip(block.get("title"))])
            rows.extend([_clip(item)] for item in block.get("paragraphs") or [])
    return rows or [[_clip((content.get("document") or {}).get("title") or "Document")]]


def _write_csv(content: Mapping[str, Any]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in _first_table_rows(content):
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def _write_xlsx(content: Mapping[str, Any]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    used: set[str] = set()
    sheet_blocks = [block for block in _blocks(content) if block.get("type") == "sheet"]
    table_blocks = [block for block in _blocks(content) if block.get("type") == "table"]
    active = workbook.active
    wrote = False
    if sheet_blocks:
        for index, block in enumerate(sheet_blocks):
            worksheet = active if index == 0 else workbook.create_sheet()
            worksheet.title = _sheet_name(str(block.get("name") or "Sheet"), used)
            for row in (block.get("table") or {}).get("rows") or [[""]]:
                worksheet.append([_clip(cell) for cell in row])
            wrote = True
    for index, block in enumerate(table_blocks):
        worksheet = active if not wrote and index == 0 else workbook.create_sheet()
        worksheet.title = _sheet_name(f"Table{index + 1}", used)
        for row in (block.get("table") or {}).get("rows") or [[""]]:
            worksheet.append([_clip(cell) for cell in row])
        wrote = True
    if not wrote:
        active.title = _sheet_name("Sheet", used)
        for row in _first_table_rows(content):
            active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _write_docx(content: Mapping[str, Any]) -> bytes:
    from docx import Document

    document = Document()
    title = _clip((content.get("document") or {}).get("title") or "")
    wrote = False
    for block in _blocks(content):
        kind = block.get("type")
        if kind == "heading":
            level = int(block.get("level") or 1)
            document.add_heading(_clip(block.get("text")), level=max(1, min(level, 6)))
            wrote = True
        elif kind == "paragraphs":
            for paragraph in block.get("paragraphs") or []:
                document.add_paragraph(_clip(paragraph))
                wrote = True
        elif kind == "key_values":
            pairs = list(block.get("pairs") or [])
            if pairs:
                table = document.add_table(rows=len(pairs), cols=2)
                for row, pair in zip(table.rows, pairs):
                    row.cells[0].text = _clip(pair.get("label"))
                    row.cells[1].text = _clip(pair.get("value"))
                wrote = True
        elif kind in {"table", "sheet"}:
            rows = (block.get("table") or {}).get("rows") or []
            if not rows:
                continue
            width = max(len(row) for row in rows)
            table = document.add_table(rows=len(rows), cols=width)
            for dest, src in zip(table.rows, rows):
                for cell, value in zip(dest.cells, src):
                    cell.text = _clip(value)
            wrote = True
        elif kind == "slide":
            document.add_heading(_clip(block.get("title")), level=1)
            for paragraph in block.get("paragraphs") or []:
                document.add_paragraph(_clip(paragraph))
            wrote = True
    if not wrote:
        document.add_heading(title or "Document", level=1)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _write_pptx(content: Mapping[str, Any]) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    presentation = Presentation()
    blank = presentation.slide_layouts[6]
    title_layout = presentation.slide_layouts[0]
    wrote = False

    def add_textbox_slide(title: str, paragraphs: list[str]) -> None:
        slide = presentation.slides.add_slide(blank)
        box = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(9.0), Inches(1.2))
        frame = box.text_frame
        frame.text = title
        if frame.paragraphs:
            frame.paragraphs[0].font.size = Pt(28)
        body = slide.shapes.add_textbox(Inches(0.5), Inches(1.8), Inches(9.0), Inches(5.0))
        body_frame = body.text_frame
        body_frame.word_wrap = True
        if paragraphs:
            body_frame.text = paragraphs[0]
            for extra in paragraphs[1:]:
                body_frame.add_paragraph().text = extra
        else:
            body_frame.text = ""

    for block in _blocks(content):
        kind = block.get("type")
        if kind == "slide":
            title = _clip(block.get("title")) or "Slide"
            paragraphs = [_clip(item) for item in block.get("paragraphs") or []]
            try:
                slide = presentation.slides.add_slide(title_layout)
                slide.shapes.title.text = title
                if len(slide.placeholders) > 1 and paragraphs:
                    slide.placeholders[1].text = "\n".join(paragraphs)
            except Exception:
                add_textbox_slide(title, paragraphs)
            wrote = True
        elif kind == "heading":
            add_textbox_slide(_clip(block.get("text")), [])
            wrote = True
        elif kind == "paragraphs":
            add_textbox_slide("Document", [_clip(item) for item in block.get("paragraphs") or []])
            wrote = True
        elif kind in {"table", "sheet"}:
            rows = (block.get("table") or {}).get("rows") or []
            title = _clip(block.get("name") or "Table")
            add_textbox_slide(title, [" | ".join(_clip(cell) for cell in row) for row in rows[:20]])
            wrote = True
        elif kind == "key_values":
            lines = [
                f"{_clip(pair.get('label'))}: {_clip(pair.get('value'))}"
                for pair in block.get("pairs") or []
            ]
            add_textbox_slide("Values", lines)
            wrote = True
    if not wrote:
        add_textbox_slide(_clip((content.get("document") or {}).get("title") or "Document"), [])
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _write_pdf(content: Mapping[str, Any]) -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=595, height=842)
    cursor = 48.0

    page_bottom = 800.0
    text_width = 499.0

    def ensure_space(height: float) -> None:
        nonlocal page, cursor
        if cursor + height > page_bottom:
            page = document.new_page(width=595, height=842)
            cursor = 48.0

    def font_runs(text: str) -> list[tuple[str, str]]:
        """Keep Latin kerning while selecting a CJK-capable font only as needed."""
        runs: list[tuple[str, str]] = []
        for char in text:
            font = "china-s" if ord(char) > 127 else "helv"
            if runs and runs[-1][1] == font:
                runs[-1] = (runs[-1][0] + char, font)
            else:
                runs.append((char, font))
        return runs

    def measured_width(text: str, size: float) -> float:
        return sum(
            float(fitz.get_text_length(run, fontname=font, fontsize=size))
            for run, font in font_runs(text)
        )

    def wrap_text(payload: str, size: float) -> list[str]:
        """Wrap on whitespace when possible and on characters for CJK/long tokens."""
        lines: list[str] = []
        normalized = payload.replace("\r\n", "\n").replace("\r", "\n")
        for logical_line in normalized.split("\n"):
            current = ""
            for token in re.findall(r"\S+\s*", logical_line):
                candidate = current + token
                if measured_width(candidate.rstrip(), size) <= text_width:
                    current = candidate
                    continue
                if current.rstrip():
                    lines.append(current.rstrip())
                    current = ""
                # A single token may itself be wider than the page (URLs and CJK).
                for char in token:
                    candidate = current + char
                    if current and measured_width(candidate.rstrip(), size) > text_width:
                        lines.append(current.rstrip())
                        current = char
                    else:
                        current = candidate
            # Preserve explicit (including empty) logical lines so pagination and
            # the caller's cursor account for every line PyMuPDF will render.
            lines.append(current.rstrip())
        return lines or [""]

    def draw(text: str, *, size: float = 11, height: float = 18) -> None:
        nonlocal cursor
        payload = _clip(text)
        if not payload:
            return
        # PyMuPDF needs room for ascenders, descenders, and its textbox line
        # leading; a visually 11pt line does not fit reliably in an 18pt box.
        line_height = max(height, size * 1.8)
        for line in wrap_text(payload, size):
            ensure_space(line_height)
            x_pos = 48.0
            baseline = cursor + size * 1.25
            for run, run_font in font_runs(line):
                page.insert_text((x_pos, baseline), run, fontsize=size, fontname=run_font)
                x_pos += measured_width(run, size)
            if x_pos > 547.01:
                raise RenderContractError(FORMAT_NOT_SUPPORTED, "PDF text exceeded page boundary")
            cursor += line_height
        cursor += 4

    for block in _blocks(content):
        kind = block.get("type")
        if kind == "heading":
            draw(_clip(block.get("text")), size=16, height=28)
        elif kind == "paragraphs":
            for paragraph in block.get("paragraphs") or []:
                draw(paragraph, height=36)
        elif kind == "key_values":
            for pair in block.get("pairs") or []:
                draw(f"{_clip(pair.get('label'))}: {_clip(pair.get('value'))}")
        elif kind in {"table", "sheet"}:
            if block.get("name"):
                draw(str(block.get("name")), size=13, height=22)
            for row in (block.get("table") or {}).get("rows") or []:
                draw(" | ".join(_clip(cell) for cell in row))
        elif kind == "slide":
            draw(_clip(block.get("title")), size=16, height=28)
            for paragraph in block.get("paragraphs") or []:
                draw(paragraph, height=36)
    if cursor == 48.0:
        draw(_clip((content.get("document") or {}).get("title") or "Document"), size=16, height=28)
    payload = document.tobytes()
    document.close()
    return payload
