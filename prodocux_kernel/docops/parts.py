"""docops/parts: deterministic operations on the .docx zip layer (OOXML parts).

Low-level OOXML part fixes, generalized into the kernel. Fully deterministic,
no LLM calls.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Union

PathLike = Union[str, Path]


def rewrite_docx_parts(docx_path: PathLike, transform: Callable[[str, bytes], bytes]) -> None:
    """Rewrite each zip part inside a .docx one by one; transform(part_name, data) -> data.

    Overwrites atomically (temp + move) to avoid leaving a half-written file.
    """
    docx_path = Path(docx_path)
    fd, tmp_name = tempfile.mkstemp(suffix=".docx", dir=str(docx_path.parent))
    os.close(fd)
    Path(tmp_name).unlink(missing_ok=True)
    with zipfile.ZipFile(docx_path, "r") as zin, zipfile.ZipFile(tmp_name, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            zout.writestr(item, transform(item.filename, data))
    shutil.move(tmp_name, docx_path)


def enable_update_fields_on_open(docx_path: PathLike) -> None:
    """Inject <w:updateFields w:val="true"/> into settings.xml so Word auto-updates TOC/page-number fields on open."""
    def transform(name: str, data: bytes) -> bytes:
        if name != "word/settings.xml":
            return data
        text = data.decode("utf-8", errors="ignore")
        if "w:updateFields" not in text:
            text = text.replace("</w:settings>", '<w:updateFields w:val="true"/></w:settings>')
        return text.encode("utf-8")

    rewrite_docx_parts(docx_path, transform)


def ensure_decimal_numbering(docx_path: PathLike, num_id: int = 900) -> None:
    """Ensure numbering.xml has a single-level decimal numbering definition (for heading auto-numbering).

    Skips injection if the num_id already exists. Idempotent.
    """
    def transform(name: str, data: bytes) -> bytes:
        if name != "word/numbering.xml":
            return data
        text = data.decode("utf-8", errors="ignore")
        if f'w:numId="{num_id}"' in text:
            return data
        definition = (
            f'<w:abstractNum w:abstractNumId="{num_id}">'
            '<w:multiLevelType w:val="singleLevel"/>'
            '<w:lvl w:ilvl="0">'
            '<w:start w:val="1"/>'
            '<w:numFmt w:val="decimal"/>'
            '<w:lvlText w:val="%1."/>'
            '<w:lvlJc w:val="left"/>'
            '<w:pPr><w:ind w:left="482" w:hanging="482"/></w:pPr>'
            '</w:lvl>'
            '</w:abstractNum>'
            f'<w:num w:numId="{num_id}"><w:abstractNumId w:val="{num_id}"/></w:num>'
        )
        if "</w:numbering>" not in text:
            return data
        return text.replace("</w:numbering>", definition + "</w:numbering>").encode("utf-8")

    rewrite_docx_parts(docx_path, transform)


def has_part(docx_path: PathLike, part_name: str) -> bool:
    with zipfile.ZipFile(docx_path, "r") as zin:
        return part_name in zin.namelist()


def read_part(docx_path: PathLike, part_name: str) -> bytes:
    with zipfile.ZipFile(docx_path, "r") as zin:
        return zin.read(part_name)
