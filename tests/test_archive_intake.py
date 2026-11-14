"""Real archive bytes generated from owned fixtures."""

import bz2
import gzip
import lzma
import os
import shutil
import subprocess
import tarfile
import warnings
import zipfile
from hashlib import sha256
from io import BytesIO

import pytest
from reportlab.pdfgen.canvas import Canvas

from prodocux_kernel.archive_intake.decoders import ArchiveError, Budget, open_container
from prodocux_kernel.archive_intake.replay import (
    ChainStep,
    MemberSelector,
    resolve_member,
    selected_member,
)

TEXT = b"owned archive marker at the tail"
COMPRESSORS = {"gzip": gzip.compress, "bzip2": bz2.compress, "xz": lzma.compress}


def zipped(entries, *, force_zip64=False, method=zipfile.ZIP_DEFLATED):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=method) as archive:
        for name, data in entries:
            with archive.open(name, "w", force_zip64=force_zip64) as member:
                member.write(data)
    return buffer.getvalue()


def tarred(format=tarfile.PAX_FORMAT):
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=format) as archive:
        member = tarfile.TarInfo("text.txt")
        member.size = len(TEXT)
        archive.addfile(member, BytesIO(TEXT))
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "text.txt"
        archive.addfile(link)
        hardlink = tarfile.TarInfo("hardlink")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "text.txt"
        archive.addfile(hardlink)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "profile,raw",
    [
        ("zip-store-deflate", zipped([("text.txt", TEXT)], method=zipfile.ZIP_STORED)),
        ("zip-store-deflate", zipped([("text.txt", TEXT)])),
        ("zip64-store-deflate", zipped([("text.txt", TEXT)], force_zip64=True)),
        *[
            ("tar-ustar-pax-gnu", tarred(fmt))
            for fmt in (tarfile.USTAR_FORMAT, tarfile.PAX_FORMAT, tarfile.GNU_FORMAT)
        ],
        *[
            (
                key + "-single-" + ("member" if key == "gzip" else "stream"),
                compress(TEXT),
            )
            for key, compress in COMPRESSORS.items()
        ],
        *[("tar-" + key, compress(tarred())) for key, compress in COMPRESSORS.items()],
    ],
    ids=[
        "zip-store",
        "zip-deflate",
        "zip64",
        "ustar",
        "pax",
        "gnu",
        "gzip",
        "bzip2",
        "xz",
        "tar-gzip",
        "tar-bzip2",
        "tar-xz",
    ],
)
def test_read_real_profiles(profile, raw):
    with open_container(BytesIO(raw), profile, Budget()) as archive:
        page, next_start = archive.page(0, 1)
        assert page[0].ordinal == 0
        if profile.startswith("tar"):
            assert archive.page(next_start, 1)[0][0].kind == "link"
            with pytest.raises(ArchiveError, match="PROFILE_NOT_APPLICABLE"):
                archive.read(1, 0, 0)
            assert archive.page(2, 1)[0][0].kind == "hardlink"
            with pytest.raises(ArchiveError, match="PROFILE_NOT_APPLICABLE"):
                archive.read(2, 0, 0)
        else:
            assert next_start is None
        prefix = archive.read(0, 0, 3)
        assert prefix.data == TEXT[:3]
        assert prefix.member_sha256 is None and not prefix.eof_verified
        tail = archive.read(0, len(TEXT) - 4, len(TEXT))
        assert tail.data == b"tail" and tail.eof_verified
        assert tail.member_sha256 == sha256(TEXT).hexdigest()
    with pytest.raises(ArchiveError, match="BUDGET_EXHAUSTED"):
        with open_container(BytesIO(raw), profile, Budget(max_expanded_bytes=1)) as archive:
            archive.read(0, 0, len(TEXT))


@pytest.mark.parametrize("name,compress", COMPRESSORS.items())
def test_nested_compressed_tar_rejects_truncation(name, compress):
    member = f"inner.tar.{name}"
    raw = zipped([(member, compress(tarred())[:-1])])
    chain = [
        ChainStep("zip-store-deflate", MemberSelector(0, member)),
        ChainStep("tar-" + name, MemberSelector(0, "text.txt")),
    ]
    with pytest.raises(ArchiveError, match="INTEGRITY_FAILED"):
        resolve_member(
            BytesIO(raw),
            sha256(raw).hexdigest(),
            chain,
            Budget(),
            locator="1",
            start=0,
            end=len(TEXT),
            expected_quote_sha256=sha256(TEXT).hexdigest(),
        )


@pytest.mark.parametrize(
    "extension,profile",
    [
        ("zip", "zip-store-deflate"),
        ("zip64", "zip64-store-deflate"),
        ("tar", "tar-ustar-pax-gnu"),
        ("tar.gz", "tar-gzip"),
        ("tar.bz2", "tar-bzip2"),
        ("tar.xz", "tar-xz"),
        ("gz", "gzip-single-member"),
        ("bz2", "bzip2-single-stream"),
        ("xz", "xz-single-stream"),
    ],
)
def test_independently_authored_archive(tmp_path, extension, profile):
    tool = shutil.which("tar.exe") if os.name == "nt" else shutil.which("bsdtar")
    if tool is None:
        pytest.skip("requires a local bsdtar writer")
    (tmp_path / "owned.txt").write_bytes(TEXT)
    source = tmp_path / f"authored.{extension}"
    flags = {
        "zip": ["--format", "zip"],
        "zip64": ["--format=zip", "--options=zip:zip64"],
        "tar": ["--format", "ustar"],
        "tar.gz": ["-z"],
        "tar.bz2": ["-j"],
        "tar.xz": ["-J"],
        "gz": ["--format=raw", "-z"],
        "bz2": ["--format=raw", "-j"],
        "xz": ["--format=raw", "-J"],
    }
    subprocess.run(
        [tool, *flags[extension], "-cf", str(source), "owned.txt"],
        cwd=tmp_path,
        check=True,
        timeout=20,
        capture_output=True,
    )
    with source.open("rb") as stream, open_container(stream, profile, Budget()) as archive:
        name = "stream" if extension in {"gz", "bz2", "xz"} else "owned.txt"
        selected = selected_member(archive, MemberSelector(0, name))
        read = archive.read(selected.ordinal, 0, len(TEXT))
        assert read.data == TEXT and read.member_sha256 == sha256(TEXT).hexdigest()


def test_duplicate_names_and_path_like_names():
    names = [
        "same",
        "same",
        "Same",
        "cafe\u0301",
        "caf\xe9",
        "line\nbreak",
        "../../owned.txt",
    ]
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name")
        raw = zipped([(name, str(i).encode()) for i, name in enumerate(names)])
    with open_container(BytesIO(raw), "zip-store-deflate", Budget()) as archive:
        for ordinal, name in enumerate(names):
            member = selected_member(archive, MemberSelector(ordinal, name))
            assert archive.read(member.ordinal, 0, 1).data == str(ordinal).encode()
        with pytest.raises(ArchiveError, match="PROFILE_BINDING_CHANGED"):
            selected_member(archive, MemberSelector(2, "same"))


@pytest.mark.parametrize("name,compress", COMPRESSORS.items())
def test_stream_rejects_truncation_and_concat(name, compress):
    profile = name + "-single-" + ("member" if name == "gzip" else "stream")
    good = compress(TEXT)
    for malformed in (good[:-1], good + good, good + b"trailing"):
        with (
            pytest.raises(ArchiveError, match="INTEGRITY_FAILED"),
            open_container(BytesIO(malformed), profile, Budget()),
        ):
            pytest.fail("malformed stream accepted")


def test_zip_corrupt_crc_and_bounded_listing():
    raw = zipped([("text.txt", TEXT)], method=zipfile.ZIP_STORED)
    damaged = raw.replace(TEXT, bytes(len(TEXT)))
    with (
        open_container(BytesIO(damaged), "zip-store-deflate", Budget()) as archive,
        pytest.raises(ArchiveError, match="INTEGRITY_FAILED"),
    ):
        archive.read(0, 0, len(TEXT))
    with (
        pytest.raises(ArchiveError, match="BUDGET_EXHAUSTED"),
        open_container(
            BytesIO(raw),
            "zip-store-deflate",
            Budget(max_metadata_bytes=1),
        ),
    ):
        pytest.fail("metadata budget exceeded")


def _sparse_file(file):
    if os.name != "nt":
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes

    output = wintypes.DWORD()
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(file.fileno()))
    ioctl = ctypes.WinDLL("kernel32", use_last_error=True).DeviceIoControl
    if not ioctl(handle, 0x900C4, None, 0, None, 0, ctypes.byref(output), None):
        pytest.skip("filesystem does not permit controlled sparse ZIP64 fixture")


def test_zip64_real_high_offset(tmp_path):
    with (tmp_path / "high-offset.zip").open("w+b") as source:
        _sparse_file(source)
        offset = (1 << 32) + 64
        source.seek(offset)
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("text.txt", TEXT)
            assert archive.getinfo("text.txt").header_offset == offset
        with open_container(source, "zip64-store-deflate", Budget()) as archive:
            assert archive.read(0, 0, len(TEXT)).data == TEXT


@pytest.mark.parametrize("leaf", ["leaf.txt", "leaf.pdf"])
@pytest.mark.parametrize("external_writer", [False, True])
def test_nested_document_resolve(leaf, external_writer, tmp_path):
    marker = "owned archive citation tail marker"
    if leaf.endswith(".pdf"):
        pdf = BytesIO()
        canvas = Canvas(pdf, invariant=True)
        canvas.drawString(50, 750, marker)
        canvas.save()
        payload = pdf.getvalue()
        locator = "1"
    else:
        from prodocux_kernel.intake.documents import read_document

        payload = (marker + "\n").encode()
        locator = read_document(leaf, payload)["text_items"][0]["source_locator"]
    if external_writer:
        tool = shutil.which("tar.exe") if os.name == "nt" else shutil.which("bsdtar")
        if tool is None:
            pytest.skip("requires a local bsdtar writer")
        (tmp_path / leaf).write_bytes(payload)
        for options, output, member in (
            (["-z"], "inner.tar.gz", leaf),
            (["--format=zip"], "outer.zip", "inner.tar.gz"),
        ):
            subprocess.run(
                [tool, *options, "-cf", output, member],
                cwd=tmp_path, check=True, timeout=20, capture_output=True,
            )
        inner = (tmp_path / "inner.tar.gz").read_bytes()
        raw = (tmp_path / "outer.zip").read_bytes()
        inner_name, inner_profile = "inner.tar.gz", "tar-gzip"
    else:
        inner = zipped([(leaf, payload)])
        raw = zipped([("inner.zip", inner)])
        inner_name, inner_profile = "inner.zip", "zip-store-deflate"
    chain = [
        ChainStep("zip-store-deflate", MemberSelector(0, inner_name)),
        ChainStep(inner_profile, MemberSelector(0, leaf)),
    ]
    args = {
        "locator": locator,
        "start": 0,
        "end": len(marker),
        "expected_quote_sha256": sha256(marker.encode()).hexdigest(),
    }
    digest = sha256(raw).hexdigest()
    quote, proof = resolve_member(BytesIO(raw), digest, chain, Budget(), **args)
    assert quote == marker
    assert (
        len(proof["layers"]) == 2
        and proof["layers"][-1]["member_sha256"] == sha256(payload).hexdigest()
    )
    assert (
        resolve_member(
            BytesIO(raw), digest, chain, Budget(), expected_provenance=proof, **args
        )[0]
        == marker
    )
    with pytest.raises(ArchiveError, match="SOURCE_CHANGED"):
        resolve_member(BytesIO(raw + b"x"), digest, chain, Budget(), **args)
    with pytest.raises(ArchiveError, match="BUDGET_EXHAUSTED"):
        resolve_member(BytesIO(raw), digest, chain, Budget(max_depth=1), **args)
    with pytest.raises(ArchiveError, match="BUDGET_EXHAUSTED"):
        resolve_member(
            BytesIO(raw),
            digest,
            chain,
            Budget(max_expanded_bytes=len(inner) + len(payload) - 1),
            **args,
        )
