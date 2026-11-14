"""Bounded, read-only standard-library archive decoders.

Internal decoder primitives. Callers own source admission and authorization.
No entry name is ever used as a filesystem path.
"""

from __future__ import annotations

import bz2
import hashlib
import lzma
import os
import stat
import struct
import tarfile
import time
import zipfile
import zlib
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from tempfile import TemporaryFile

CHUNK = 65536


class ArchiveError(ValueError):
    """A decoder failure with a stable reason."""


@dataclass
class Budget:
    max_source_bytes: int = 64 << 20
    max_expanded_bytes: int = 128 << 20
    max_returned_bytes: int = 1 << 20
    max_metadata_bytes: int = 4 << 20
    max_entries: int = 4096
    max_depth: int = 8
    max_expansion_ratio: int = 500
    deadline_seconds: float = 30
    source_bytes: int = 0
    expanded_bytes: int = 0
    returned_bytes: int = 0
    metadata_bytes: int = 0
    entries: int = 0

    def __post_init__(self):
        self.deadline = time.monotonic() + self.deadline_seconds

    def charge(self, field, count):
        self.check_time()
        total = getattr(self, field) + count
        limit = getattr(self, "max_" + field)
        setattr(self, field, min(total, limit))
        if total > limit:
            raise ArchiveError("BUDGET_EXHAUSTED")

    def check_time(self):
        if time.monotonic() >= self.deadline:
            raise ArchiveError("BUDGET_EXHAUSTED")


@dataclass(frozen=True)
class Member:
    ordinal: int
    name: str
    size: int
    kind: str
    raw_name_sha256: str | None = None


@dataclass(frozen=True)
class Read:
    data: bytes
    range_sha256: str
    member_sha256: str | None
    member_size: int | None
    eof_verified: bool
    stop_reason: str | None


def size_of(stream):
    position = stream.tell()
    size = stream.seek(0, os.SEEK_END)
    stream.seek(position)
    return size


def _zip_directory(stream, budget):
    """Preflight directory allocation, including ZIP64, before constructing ZipFile."""
    size = size_of(stream)
    window = min(size, 65557)
    stream.seek(size - window)
    tail = stream.read(window)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or len(tail) - position < 22:
        raise ArchiveError("INTEGRITY_FAILED")
    disk, directory_disk, local_entries, entries, length, offset, comment = (
        struct.unpack_from("<4H2IH", tail, position + 4)
    )
    if position + 22 + comment != len(tail):
        raise ArchiveError("INTEGRITY_FAILED")
    if disk or directory_disk or local_entries != entries:
        raise ArchiveError("VOLUME_MISSING")
    eocd = size - window + position
    directory_end = eocd
    stream.seek(max(0, eocd - 20))
    locator = stream.read(20) if eocd >= 20 else b""
    zip64 = locator.startswith(b"PK\x06\x07")
    if zip64:
        zip_disk, header_offset, disks = struct.unpack_from("<IQI", locator, 4)
        if zip_disk or disks != 1:
            raise ArchiveError("VOLUME_MISSING")
        if header_offset + 56 != eocd - 20:
            raise ArchiveError("INTEGRITY_FAILED")
        stream.seek(header_offset)
        raw = stream.read(56)
        if len(raw) != 56 or raw[:4] != b"PK\x06\x06":
            raise ArchiveError("INTEGRITY_FAILED")
        (
            record_length,
            _,
            _,
            disk,
            directory_disk,
            local_entries,
            entries,
            length,
            offset,
        ) = struct.unpack_from("<Q2H2I4Q", raw, 4)
        if record_length != 44 or disk or directory_disk or local_entries != entries:
            raise ArchiveError("INTEGRITY_FAILED")
        directory_end = header_offset
    elif entries == 65535 or length == 0xFFFFFFFF or offset == 0xFFFFFFFF:
        raise ArchiveError("INTEGRITY_FAILED")
    if offset + length != directory_end:
        raise ArchiveError("INTEGRITY_FAILED")
    budget.charge("metadata_bytes", length)
    budget.charge("entries", entries)
    return zip64, entries


class _TarInput:
    def __init__(self, stream, budget):
        self.stream = stream
        self.budget = budget

    def read(self, size):
        self.budget.charge("metadata_bytes", size)
        return self.stream.read(size)

    def seek(self, *args):
        return self.stream.seek(*args)

    def tell(self):
        return self.stream.tell()


@contextmanager
def _expanded_stream(source, profile, budget):
    decoder = {
        "gzip": lambda: zlib.decompressobj(31),
        "bzip2": bz2.BZ2Decompressor,
        "xz": lambda: lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=64 << 20),
    }[profile]()
    source.seek(0)
    input_size = size_of(source)
    with TemporaryFile() as spool:
        while not decoder.eof:
            budget.check_time()
            needs_input = getattr(decoder, "needs_input", True)
            pending = getattr(decoder, "unconsumed_tail", b"")
            chunk = pending or (source.read(CHUNK) if needs_input else b"")
            if needs_input and not chunk:
                raise ArchiveError("INTEGRITY_FAILED")
            try:
                data = decoder.decompress(chunk, CHUNK)
            except (OSError, EOFError, zlib.error, lzma.LZMAError) as exc:
                raise ArchiveError("INTEGRITY_FAILED") from exc
            budget.charge("expanded_bytes", len(data))
            if spool.tell() + len(data) > input_size * budget.max_expansion_ratio:
                raise ArchiveError("BUDGET_EXHAUSTED")
            spool.write(data)
        if decoder.unused_data or source.read(1):
            raise ArchiveError("INTEGRITY_FAILED")
        spool.seek(0)
        yield spool


class Container:
    def __init__(self, stream, profile, budget):
        self.stream = stream
        self.profile = profile
        self.budget = budget
        self.members = []
        self._zip = None
        self._tar_members = []

    def load_zip(self):
        zip64, declared = _zip_directory(self.stream, self.budget)
        self._zip = zipfile.ZipFile(self.stream)
        infos = self._zip.infolist()
        if len(infos) != declared:
            raise ArchiveError("INTEGRITY_FAILED")
        if self.profile == "zip64-store-deflate" and not (
            zip64 or any(i.extract_version >= 45 for i in infos)
        ):
            raise ArchiveError("PROFILE_MISMATCH")
        if self.profile == "zip-store-deflate" and (
            zip64 or any(i.extract_version >= 45 for i in infos)
        ):
            raise ArchiveError("PROFILE_MISMATCH")
        for ordinal, info in enumerate(infos):
            mode = info.external_attr >> 16
            if info.flag_bits & 1:
                kind = "encrypted"
            elif stat.S_ISLNK(mode):
                kind = "link"
            elif info.is_dir():
                kind = "directory"
            elif info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                kind = "unsupported"
            else:
                kind = "file"
            self.members.append(
                Member(
                    ordinal,
                    info.orig_filename,
                    info.file_size,
                    kind,
                    hashlib.sha256(
                        info.orig_filename.encode(
                            "utf-8" if info.flag_bits & 0x800 else "cp437"
                        )
                    ).hexdigest(),
                )
            )

    def load_tar(self):
        self.stream.seek(0)
        with tarfile.open(
            fileobj=_TarInput(self.stream, self.budget), mode="r:"
        ) as archive:
            for info in archive:
                self.budget.charge("entries", 1)
                if info.size < 0 or info.offset_data + info.size > size_of(self.stream):
                    raise ArchiveError("INTEGRITY_FAILED")
                kind = (
                    "file"
                    if info.isfile() and not info.issparse()
                    else "directory"
                    if info.isdir()
                    else "hardlink"
                    if info.islnk()
                    else "link"
                    if info.issym()
                    else "unsupported"
                )
                self.members.append(
                    Member(
                        len(self.members),
                        info.name,
                        info.size,
                        kind,
                        hashlib.sha256(
                            info.name.encode("utf-8", "surrogateescape")
                        ).hexdigest(),
                    )
                )
                self._tar_members.append(info)
            self.stream.seek(archive.offset)
            terminator = self.stream.read(1024)
            if terminator != bytes(1024):
                raise ArchiveError("INTEGRITY_FAILED")
            while chunk := self.stream.read(CHUNK):
                self.budget.charge("metadata_bytes", len(chunk))
                if any(chunk):
                    raise ArchiveError("INTEGRITY_FAILED")

    def page(self, start, limit):
        if (
            type(start) is not int
            or type(limit) is not int
            or not 0 <= start <= len(self.members)
            or limit < 1
        ):
            raise ArchiveError("INVALID_RANGE")
        end = min(start + limit, len(self.members))
        return tuple(self.members[start:end]), end if end < len(self.members) else None

    @contextmanager
    def _member_stream(self, ordinal):
        if self._zip is not None:
            with self._zip.open(self._zip.infolist()[ordinal]) as stream:
                yield stream
        else:
            self.stream.seek(
                self._tar_members[ordinal].offset_data if self._tar_members else 0
            )
            yield self.stream

    def _verified_zip_chunks(self, ordinal):
        info = self._zip.infolist()[ordinal]
        # ZipFile checks the local name and the entry's compressed extent.
        with self._zip.open(info):
            pass
        self.stream.seek(info.header_offset)
        header = self.stream.read(30)
        if len(header) != 30 or header[:4] != b"PK\x03\x04":
            raise ArchiveError("INTEGRITY_FAILED")
        flags, method = struct.unpack_from("<HH", header, 6)
        local_crc, compressed, size, name_len, extra_len = struct.unpack_from(
            "<IIIHH", header, 14
        )
        if (flags, method) != (info.flag_bits, info.compress_type):
            raise ArchiveError("INTEGRITY_FAILED")
        self.stream.seek(name_len, os.SEEK_CUR)
        self.budget.charge("metadata_bytes", 30 + name_len + extra_len)
        extra = self.stream.read(extra_len)
        if len(extra) != extra_len:
            raise ArchiveError("INTEGRITY_FAILED")
        if not flags & 8:
            if size == 0xFFFFFFFF or compressed == 0xFFFFFFFF:
                size, compressed = _local_zip64_sizes(extra, size, compressed)
            if (local_crc, compressed, size) != (
                info.CRC,
                info.compress_size,
                info.file_size,
            ):
                raise ArchiveError("INTEGRITY_FAILED")
        remaining = info.compress_size
        decoder = zlib.decompressobj(-15) if method == zipfile.ZIP_DEFLATED else None
        crc = total = 0
        pending = b""
        while remaining or pending:
            self.budget.check_time()
            if not pending:
                pending = self.stream.read(min(remaining, CHUNK))
                if not pending:
                    raise ArchiveError("INTEGRITY_FAILED")
                remaining -= len(pending)
            if decoder is None:
                output, pending = pending, b""
            else:
                output = decoder.decompress(pending, CHUNK)
                pending = decoder.unconsumed_tail
                if decoder.unused_data or (decoder.eof and (remaining or pending)):
                    raise ArchiveError("INTEGRITY_FAILED")
            total += len(output)
            if total > info.file_size:
                raise ArchiveError("INTEGRITY_FAILED")
            crc = zlib.crc32(output, crc)
            if output:
                yield output
        if (decoder is not None and not decoder.eof) or (total, crc) != (
            info.file_size,
            info.CRC,
        ):
            raise ArchiveError("INTEGRITY_FAILED")
        if flags & 8:
            _verify_zip_descriptor(
                self.stream, info,
                size == 0xFFFFFFFF or compressed == 0xFFFFFFFF,
            )

    def read(self, ordinal, start, end, *, verify_full=False):
        if type(ordinal) is not int or not 0 <= ordinal < len(self.members):
            raise ArchiveError("INVALID_RANGE")
        member = self.members[ordinal]
        if member.kind == "encrypted":
            raise ArchiveError("CREDENTIAL_REQUIRED")
        if member.kind != "file":
            raise ArchiveError("PROFILE_NOT_APPLICABLE")
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start <= end <= member.size
        ):
            raise ArchiveError("INVALID_RANGE")
        self.budget.charge("returned_bytes", end - start)
        if self._zip is not None:
            compressed = self._zip.infolist()[ordinal].compress_size
            if member.size > max(1, compressed) * self.budget.max_expansion_ratio:
                raise ArchiveError("BUDGET_EXHAUSTED")
        data = bytearray()
        digest = hashlib.sha256()
        position = 0
        full = verify_full or end == member.size
        target = member.size if full else end
        try:
            with (
                nullcontext()
                if full and self._zip is not None
                else self._member_stream(ordinal)
            ) as stream:
                chunks = (
                    self._verified_zip_chunks(ordinal)
                    if full and self._zip is not None
                    else _read_chunks(stream, target, self.budget)
                )
                for chunk in chunks:
                    self.budget.charge("expanded_bytes", len(chunk))
                    digest.update(chunk)
                    left = max(0, start - position)
                    right = min(len(chunk), end - position)
                    if left < right:
                        data.extend(chunk[left:right])
                    position += len(chunk)
        except (zipfile.BadZipFile, EOFError, zlib.error, NotImplementedError) as exc:
            raise ArchiveError("INTEGRITY_FAILED") from exc
        payload = bytes(data)
        return Read(
            payload,
            hashlib.sha256(payload).hexdigest(),
            digest.hexdigest() if full else None,
            member.size if full else None,
            full,
            None if full else "requested_range",
        )


def _read_chunks(stream, target, budget):
    while target:
        budget.check_time()
        chunk = stream.read(min(CHUNK, target))
        if not chunk:
            raise ArchiveError("INTEGRITY_FAILED")
        target -= len(chunk)
        yield chunk


def _local_zip64_sizes(extra, size, compressed):
    offset = 0
    while offset + 4 <= len(extra):
        kind, length = struct.unpack_from("<HH", extra, offset)
        offset += 4
        if offset + length > len(extra):
            break
        if kind == 1:
            sizes = iter(
                value
                for (value,) in struct.iter_unpack(
                    "<Q", extra[offset : offset + length]
                )
            )
            return (
                next(sizes, -1) if size == 0xFFFFFFFF else size,
                next(sizes, -1) if compressed == 0xFFFFFFFF else compressed,
            )
        offset += length
    raise ArchiveError("INTEGRITY_FAILED")


def _verify_zip_descriptor(stream, info, zip64):
    # Forced ZIP64 writers may leave local sizes at zero while emitting
    # a wide descriptor. Use the exact extent before the next ZIP record.
    extent = info._end_offset - stream.tell()
    zip64 = zip64 or (extent in (20, 24) and info.extract_version >= 45)
    expected = struct.pack(
        "<IQQ" if zip64 else "<III", info.CRC, info.compress_size, info.file_size
    )
    if extent not in (len(expected), len(expected) + 4):
        raise ArchiveError("INTEGRITY_FAILED")
    raw = stream.read(extent)
    if raw not in (expected, b"PK\x07\x08" + expected):
        raise ArchiveError("INTEGRITY_FAILED")


STREAMS = {
    "gzip-single-member": "gzip",
    "bzip2-single-stream": "bzip2",
    "xz-single-stream": "xz",
    "tar-gzip": "gzip",
    "tar-bzip2": "bzip2",
    "tar-xz": "xz",
}
ZIP_PROFILES = {"zip-store-deflate", "zip64-store-deflate"}


@contextmanager
def open_container(source, profile, budget):
    """Open an admitted seekable snapshot under the caller's cumulative budget."""
    try:
        if profile in STREAMS:
            with _expanded_stream(source, STREAMS[profile], budget) as spool:
                container = Container(spool, profile, budget)
                if profile.startswith("tar-"):
                    container.load_tar()
                else:
                    budget.charge("entries", 1)
                    container.members.append(
                        Member(
                            0,
                            "stream",
                            size_of(spool),
                            "file",
                            hashlib.sha256(b"stream").hexdigest(),
                        )
                    )
                yield container
        elif profile in ZIP_PROFILES or profile == "tar-ustar-pax-gnu":
            container = Container(source, profile, budget)
            try:
                if profile in ZIP_PROFILES:
                    container.load_zip()
                else:
                    container.load_tar()
                yield container
            finally:
                if container._zip is not None:
                    container._zip.close()
        else:
            raise ArchiveError("PROFILE_NOT_IMPLEMENTED")
    except (
        tarfile.TarError,
        zipfile.BadZipFile,
        EOFError,
        struct.error,
        UnicodeError,
    ) as exc:
        raise ArchiveError("INTEGRITY_FAILED") from exc
