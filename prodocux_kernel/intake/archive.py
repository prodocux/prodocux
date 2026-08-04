"""Fail-closed preflight for ZIP-based Office input formats."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import PurePosixPath, PureWindowsPath

MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 200.0


def validate_office_archive(
    raw: bytes, *, label: str, invalid_message: str | None = None
) -> None:
    """Reject resource-exhaustion and unsafe-member archives before parsing."""
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ValueError(invalid_message or f"invalid {label} archive") from exc

    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ValueError(f"{label} archive has too many entries")

    total_uncompressed = 0
    for info in infos:
        original_name = info.filename
        name = original_name.replace("\\", "/")
        member = PurePosixPath(name)
        windows_member = PureWindowsPath(original_name)
        if (
            member.is_absolute()
            or windows_member.is_absolute()
            or bool(windows_member.drive)
            or name.startswith("//")
            or ".." in member.parts
        ):
            raise ValueError(f"{label} archive contains an unsafe member name")
        if info.flag_bits & 0x1:
            raise ValueError(f"{label} archive contains encrypted content")

        total_uncompressed += info.file_size
        if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError(f"{label} archive expands beyond the safety limit")
        if info.file_size:
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_ARCHIVE_COMPRESSION_RATIO:
                raise ValueError(f"{label} archive compression ratio is unsafe")
