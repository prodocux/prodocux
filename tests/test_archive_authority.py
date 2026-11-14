import os
import struct
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from prodocux_kernel.archive_intake.authority import (
    COUNTERS,
    ArchiveAuthority,
    Identity,
)
from prodocux_kernel.archive_intake.decoders import ArchiveError, Budget, open_container


def counters(**changes):
    return dict(dict.fromkeys(COUNTERS, 0), **changes)


def test_authority_cross_request_budget_and_restart(tmp_path):
    database = tmp_path / "authority.sqlite"
    owner = Identity("test", "tenant-a", "alice")
    stranger = Identity("test", "tenant-b", "alice")
    authority = ArchiveAuthority(database)
    ref = authority.issue(
        owner,
        "a" * 64,
        expires_ms=100,
        now_ms=0,
        limits=dict.fromkeys(COUNTERS, 10),
    )
    with pytest.raises(ArchiveError, match="SOURCE_NOT_FOUND"):
        authority.authorize(stranger, ref, now_ms=1)
    assert authority.reserve(
        owner, ref, "request-1", "a", counters(expanded_bytes=6), now_ms=1
    )
    authority = ArchiveAuthority(database)
    with pytest.raises(ArchiveError, match="OPERATION_RECONCILIATION_REQUIRED"):
        authority.reserve(
            owner, ref, "request-2", "a", counters(expanded_bytes=3), now_ms=2
        )
    authority.settle(owner, ref, "request-1", None)
    with pytest.raises(ArchiveError, match="OPERATION_RECONCILIATION_REQUIRED"):
        authority.reserve(
            owner, ref, "request-1", "a", counters(expanded_bytes=6), now_ms=3
        )
    authority.settle(owner, ref, "request-1", counters(expanded_bytes=6))
    assert not authority.reserve(
        owner, ref, "request-1", "a", counters(expanded_bytes=6), now_ms=4
    )
    with pytest.raises(ArchiveError, match="PROFILE_BINDING_CHANGED"):
        authority.reserve(
            owner, ref, "request-1", "b", counters(expanded_bytes=6), now_ms=4
        )
    with pytest.raises(ArchiveError, match="BUDGET_EXHAUSTED"):
        authority.reserve(
            owner, ref, "request-2", "a", counters(expanded_bytes=5), now_ms=4
        )
    with pytest.raises(ArchiveError, match="SOURCE_LEASE_EXPIRED"):
        authority.authorize(owner, ref, now_ms=100)
    authority.close(owner, ref)
    with pytest.raises(ArchiveError, match="SOURCE_NOT_FOUND"):
        authority.authorize(owner, ref, now_ms=5)


def test_concurrent_replay_reserves_once(tmp_path):
    authority = ArchiveAuthority(tmp_path / "authority.sqlite")
    owner = Identity("test", "tenant", "principal")
    ref = authority.issue(
        owner, "a" * 64, expires_ms=100, now_ms=0, limits=dict.fromkeys(COUNTERS, 100)
    )

    def reserve():
        try:
            return authority.reserve(
                owner, ref, "same", "binding", counters(returned_bytes=1), now_ms=1
            )
        except ArchiveError as error:
            return str(error)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert results.count(True) == 1
    assert results.count("OPERATION_RECONCILIATION_REQUIRED") == 1


@pytest.mark.parametrize(
    "defect", ["local-crc", "local-method", "deflate-trailer", "truncated-deflate"]
)
def test_full_zip_identity_rejects_local_and_deflate_mismatch(defect):
    raw = BytesIO()
    payload = b"owned test data" * 50
    with ZipFile(raw, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("payload.txt", payload)
    data = bytearray(raw.getvalue())
    if defect == "local-crc":
        data[14] ^= 1
    elif defect == "local-method":
        data[8] ^= 8
    else:
        central = data.index(b"PK\x01\x02")
        if defect == "deflate-trailer":
            data[central:central] = b"x"
            offset = 1
        else:
            del data[central - 1]
            offset = -1
        central += offset
        eocd = data.index(b"PK\x05\x06")
        size = struct.unpack_from("<I", data, 18)[0] + offset
        struct.pack_into("<I", data, 18, size)
        struct.pack_into("<I", data, central + 20, size)
        struct.pack_into("<I", data, eocd + 16, central)
    with (
        open_container(BytesIO(data), "zip-store-deflate", Budget()) as archive,
        pytest.raises(ArchiveError, match="INTEGRITY_FAILED"),
    ):
        archive.read(0, 0, len(payload))


def test_zip_descriptor_crc_is_verified():
    class NonSeekable(BytesIO):
        def seek(self, *args):
            raise OSError("non-seekable")

    source = NonSeekable()
    payload = b"descriptor"
    with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("payload.txt", payload)
    raw = source.getvalue()
    with open_container(BytesIO(raw), "zip-store-deflate", Budget()) as archive:
        assert archive.read(0, 0, len(payload)).data == payload
    damaged = bytearray(raw)
    damaged[damaged.index(b"PK\x07\x08") + 4] ^= 1
    with (
        open_container(BytesIO(damaged), "zip-store-deflate", Budget()) as archive,
        pytest.raises(ArchiveError, match="INTEGRITY_FAILED"),
    ):
        archive.read(0, 0, len(payload))


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object")
def test_guarded_worker_real_zip_and_timeout(tmp_path):
    import base64
    import json
    from hashlib import sha256

    from prodocux_kernel.archive_intake.process_guard import run_archive_worker

    source = tmp_path / "payload.zip"
    payload = b"guarded archive read"
    with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("owned.txt", payload)
    args = [
        str(source),
        sha256(source.read_bytes()).hexdigest(),
        "zip-store-deflate",
        "0",
        json.dumps("owned.txt"),
        "0",
        str(len(payload)),
    ]
    raw = run_archive_worker(
        args, wall_seconds=15, cpu_seconds=10, memory_bytes=512 << 20
    )
    result = json.loads(raw)
    assert base64.b64decode(result["data"]) == payload
    assert result["member_sha256"] == sha256(payload).hexdigest()
    with pytest.raises(ArchiveError, match="EXECUTION_UNKNOWN"):
        run_archive_worker(
            args, wall_seconds=0.001, cpu_seconds=10, memory_bytes=512 << 20
        )
