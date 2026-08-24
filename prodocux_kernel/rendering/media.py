"""MIME / magic-byte checks for render templates and outputs."""

from __future__ import annotations

import zipfile
from io import BytesIO

from ..intake.archive import validate_office_archive
from .errors import TEMPLATE_MAGIC_MISMATCH, TEMPLATE_MEDIA_TYPE_INVALID, RenderContractError
from .limits import FORMAT_MEDIA_TYPES

_PDF_MAGIC = b"%PDF"
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OFFICE_MARKERS = {
    "docx": "word/",
    "xlsx": "xl/",
    "pptx": "ppt/",
}


def assert_media_matches_format(media_type: str, target_format: str) -> None:
    expected = FORMAT_MEDIA_TYPES[target_format]
    if media_type != expected:
        raise RenderContractError(
            TEMPLATE_MEDIA_TYPE_INVALID,
            "media_type does not match target_format",
        )


def assert_magic_matches_format(payload: bytes, target_format: str) -> None:
    if target_format == "pdf":
        if not payload.startswith(_PDF_MAGIC):
            raise RenderContractError(
                TEMPLATE_MAGIC_MISMATCH, "payload is not a PDF"
            )
        return
    if target_format == "csv":
        if payload.startswith(_PDF_MAGIC) or payload.startswith(_ZIP_MAGICS):
            raise RenderContractError(
                TEMPLATE_MAGIC_MISMATCH, "payload is not CSV text"
            )
        try:
            payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise RenderContractError(
                TEMPLATE_MAGIC_MISMATCH, "CSV payload is not UTF-8"
            ) from exc
        return
    if not payload.startswith(_ZIP_MAGICS):
        raise RenderContractError(
            TEMPLATE_MAGIC_MISMATCH, "payload is not an Office Open XML archive"
        )
    validate_office_archive(payload, label=target_format.upper())
    marker = _OFFICE_MARKERS[target_format]
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise RenderContractError(
            TEMPLATE_MAGIC_MISMATCH, "payload is not a valid ZIP archive"
        ) from exc
    if not any(name.startswith(marker) for name in names):
        raise RenderContractError(
            TEMPLATE_MAGIC_MISMATCH,
            "Office archive does not match target_format",
        )
