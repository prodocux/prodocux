"""Archive wire boundary tests using the actual sidecar routes."""

import bz2
import gzip
import json
import lzma
import os
import subprocess
import sys
import tarfile
import warnings
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile, ZipInfo

import pytest
from fastapi.testclient import TestClient

from api.main import app
from prodocux_kernel.archive_intake.authority import COUNTERS, Identity
from prodocux_kernel.archive_intake.contracts import digest, validate
from prodocux_kernel.archive_intake.decoders import ArchiveError
from prodocux_kernel.archive_intake.sources import ArchiveSources

ROOT = "/v1/intake"
SELECTOR_NAMES = ("same", "same", "Same", "café", "cafe\u0301", "line\nbreak", "../escape.txt")


@pytest.mark.parametrize(
    "profile",
    [
        "disabled",
        pytest.param(
            "zip64-large",
            marks=pytest.mark.skipif(
                os.name != "nt" or os.environ.get("PRODOCUX_TEST_ARCHIVE_LARGE") != "1",
                reason="requires 4 GiB upload and local spool capacity",
            ),
        ),
        pytest.param(
            "zip-store-deflate",
            marks=pytest.mark.skipif(
                os.name != "nt" or os.environ.get("PRODOCUX_TEST_APPCONTAINER") != "1",
                reason="requires Windows AppContainer profile creation",
            ),
        ),
        *[
            pytest.param(
                profile,
                marks=pytest.mark.skipif(
                    os.name != "nt"
                    or os.environ.get("PRODOCUX_TEST_APPCONTAINER") != "1",
                    reason="requires Windows AppContainer profile creation",
                ),
            )
            for profile in (
                "zip64-store-deflate",
                "tar-ustar-pax-gnu",
                "gzip-single-member",
                "bzip2-single-stream",
                "xz-single-stream",
                "tar-gzip",
                "tar-bzip2",
                "tar-xz",
            )
        ],
    ],
)
def test_archive_wire_lifecycle(tmp_path, monkeypatch, profile):
    large = profile == "zip64-large"
    if large:
        profile = "zip64-store-deflate"
        monkeypatch.setenv("PRODOCUX_ARCHIVE_LARGE_SOURCES", "1")
    isolated = profile != "disabled"
    if not isolated:
        profile = "zip-store-deflate"
    monkeypatch.setenv("PRODOCUX_ARCHIVE_TTL_MS", "86400000")
    monkeypatch.setenv("PRODOCUX_ARCHIVE_DATABASE", str(tmp_path / "sources.sqlite"))
    monkeypatch.setenv("PRODOCUX_ARCHIVE_ISOLATED_ZIP_READ", "1" if isolated else "0")
    monkeypatch.setenv(
        "PRODOCUX_BEARER_TOKENS", "test-archive-first,test-archive-second"
    )
    with TestClient(app) as client:
        assert client.get(ROOT + "/archives/capabilities").status_code == 401
        client.headers["Authorization"] = "Bearer test-archive-first"
        policy = client.get(ROOT + "/source-sessions/policy").json()
        catalog = client.get(ROOT + "/archives/capabilities").json()
        validate("capability_catalog_v3", catalog)
        assert len(catalog["profiles"]) == 14
        entry = next(
            item
            for item in catalog["profiles"]
            if item["definition"]["profile_id"] == profile
        )
        raw = BytesIO()
        member_name = "owned.txt"
        payload = b"archive marker"
        has_links = not large and (profile.startswith("zip") or profile.startswith("tar"))
        if profile.startswith("zip"):
            with (
                ZipFile(raw, "w") as archive,
                archive.open(
                    member_name, "w", force_zip64=profile.startswith("zip64")
                ) as member,
            ):
                member.write(payload)
            if profile == "zip-store-deflate":
                with ZipFile(raw, "a") as archive:
                    archive.writestr("decoy.txt", b"second page")
            if has_links:
                with ZipFile(raw, "a") as archive:
                    link = ZipInfo("link")
                    link.create_system = 3
                    link.external_attr = 0o120777 << 16
                    archive.writestr(link, "../../outside")
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", message="Duplicate name")
                        for index, name in enumerate(SELECTOR_NAMES):
                            archive.writestr(name, bytes([65 + index]))
            payload = raw.getvalue()
        elif profile.startswith("tar"):
            with tarfile.open(fileobj=raw, mode="w") as archive:
                member = tarfile.TarInfo(member_name)
                member.size = len(payload)
                archive.addfile(member, BytesIO(payload))
                for name, kind in (("link", tarfile.SYMTYPE), ("hardlink", tarfile.LNKTYPE)):
                    link = tarfile.TarInfo(name)
                    link.type = kind
                    link.linkname = "../../outside"
                    archive.addfile(link)
                for index, name in enumerate(SELECTOR_NAMES):
                    member = tarfile.TarInfo(name)
                    member.size = 1
                    archive.addfile(member, BytesIO(bytes([65 + index])))
            payload = raw.getvalue()
        else:
            member_name = "stream"
        for codec, compress in (
            ("gzip", gzip.compress),
            ("bzip2", bz2.compress),
            ("xz", lzma.compress),
        ):
            if codec in profile:
                payload = compress(payload)
                break
        source_prefix = payload[:12]
        source = BytesIO(payload)
        if large:
            from test_archive_intake import _sparse_file

            source = (tmp_path / "zip64-large.zip").open("w+b")
            _sparse_file(source)
            source.seek((1 << 32) + 64)
            with ZipFile(source, "w") as archive:
                archive.writestr(member_name, b"archive marker")
                assert archive.getinfo(member_name).header_offset > 1 << 32
        source.seek(0, 2)
        source_size = source.tell()
        source.seek(0)
        chunk_size = int(policy["max_chunk_bytes"])
        descriptors = []
        source_digest = sha256()
        offset = 0
        while chunk := source.read(chunk_size):
            source_digest.update(chunk)
            descriptors.append(
                {
                    "volume_key": "part",
                    "range": {"start": str(offset), "end": str(offset + len(chunk))},
                    "sha256": sha256(chunk).hexdigest(),
                }
            )
            offset += len(chunk)
        checksum = source_digest.hexdigest()
        session = ROOT + "/source-sessions/owned-test"
        plan = {
            "schema_version": "prodocux_archive_source_admission_v2",
            "session_id": "owned-test",
            "operation_id": "operation",
            "authority_binding": policy["authority_binding"],
            "policy_digest": policy["policy_digest"],
            "mode": "chunked_snapshot",
            "expires_at_ms": str(int(policy["host_time_ms"]) + 3_600_000),
            "volumes": [
                {
                    "ordinal": "0",
                    "volume_key": "part",
                    "declared_size_bytes": str(source_size),
                }
            ],
            "upload_chunks": descriptors,
            "expected_bundle_digest": None,
        }
        assert client.post(ROOT + "/source-sessions", json=plan).status_code == 201
        missing = client.post(session + "/seal")
        assert missing.json()["reason_code"] == "VOLUME_MISSING"
        source.seek(0)
        with source:
            for descriptor in descriptors:
                span = descriptor["range"]
                data = source.read(int(span["end"]) - int(span["start"]))
                assert (
                    client.put(
                        session + "/volumes/part/chunks",
                        content=data,
                        headers={
                            "x-archive-range": f"{span['start']}:{span['end']}",
                            "x-archive-sha256": descriptor["sha256"],
                        },
                    ).status_code
                    == 204
                )
        lease = client.post(session + "/seal").json()
        validate("source_lease_v2", lease)
        assert lease["bundle"]["volumes"][0]["sha256"] == checksum
        assert client.post(session + "/seal").json() == lease
        ledger_url = ROOT + "/source-sessions/ledger"
        params = {"source_ref": lease["source_ref"], "profile_id": profile}
        ledger = client.get(ledger_url, params=params).json()
        validate("resource_ledger_v2", ledger)
        denied = client.get(
            ledger_url,
            params=params,
            headers={"Authorization": "Bearer test-archive-second"},
        )
        assert denied.status_code == 404
        assert denied.json()["operation_ref"] is None

        request = {
            "schema_version": "prodocux_archive_negotiation_request_v3",
            "catalog_digest": digest(catalog),
            "profile_id": profile,
            "profile_contract": entry["definition"]["profile_contract"],
            "expected_profile_digest": entry["definition_digest"],
            "base_request": {
                "schema_version": "prodocux_archive_request_envelope_v2",
                "context": {
                    "schema_version": "prodocux_archive_request_context_v2",
                    "request_id": "inspect",
                    "operation_id": "operation",
                    "source_lease_digest": digest(lease),
                    "profile_digest": entry["execution_profile_digest"],
                    "ledger_digest": digest(ledger),
                    "credential_ref": None,
                    "external_binding_digests": [],
                },
                "request": {
                    "schema_version": "prodocux_archive_inspect_request_v1",
                    "operation": "inspect",
                    "request_id": "inspect",
                    "source_ref": lease["source_ref"],
                    "view": "container",
                    "budget": ledger["limits"],
                    "parent_chain": [],
                },
            },
        }
        url = ROOT + "/archives/negotiate"
        if isolated:
            for operation, details in (
                ("inspect", {}),
                ("list", {"cursor": None, "max_entries": "1"}),
            ):
                operation_request = deepcopy(request)
                op_base = operation_request["base_request"]
                op_base["context"]["request_id"] = operation
                op_base["request"].update(
                    schema_version=f"prodocux_archive_{operation}_request_v1",
                    operation=operation,
                    request_id=operation,
                    budget={
                        **ledger["limits"],
                        "max_elapsed_ms": "300000" if large else "30000",
                        "max_returned_bytes": "1024",
                        "max_source_bytes": str(source_size) if large else "1048576",
                        "max_entries": "64",
                        "max_expanded_bytes": "1048576",
                        "max_metadata_bytes": "1048576",
                        "max_volumes": "1",
                    },
                    **details,
                )
                negotiated = client.post(url, json=operation_request).json()
                assert negotiated.get("decision") == "accepted", negotiated
                response = client.post(
                    ROOT + "/archives/" + operation,
                    json={
                        "schema_version": "prodocux_archive_request_envelope_v3",
                        "mode": "negotiated",
                        "base": op_base,
                        "profile_binding": negotiated["binding"],
                    },
                ).json()
                assert "base" in response, response
                validate("result_envelope_v3", response)
                assert response["base"]["response"]["outcome"] == "succeeded"
                ledger = client.get(ledger_url, params=params).json()
                op_context = request["base_request"]["context"]
                op_context["ledger_digest"] = digest(ledger)
                if operation == "list" and profile == "zip-store-deflate":
                    cursor = response["base"]["response"]["result"]["next_cursor"]
                    assert cursor["next_position"] == "1"
                    op_base["context"].update(
                        request_id="list-page-2", ledger_digest=digest(ledger)
                    )
                    op_base["request"].update(request_id="list-page-2", cursor=cursor)
                    forged = deepcopy(operation_request)
                    forged["base_request"]["request"]["cursor"]["next_position"] = "2"
                    assert client.post(url, json=forged).status_code == 409
                    negotiated = client.post(url, json=operation_request).json()
                    assert negotiated.get("decision") == "accepted", negotiated
                    second = client.post(
                        ROOT + "/archives/list",
                        json={
                            "schema_version": "prodocux_archive_request_envelope_v3",
                            "mode": "negotiated",
                            "base": op_base,
                            "profile_binding": negotiated["binding"],
                        },
                    ).json()
                    validate("result_envelope_v3", second)
                    assert (
                        second["base"]["response"]["result"]["members"][0]["selector"][
                            "display_name"
                        ]
                        == "decoy.txt"
                    )
                    assert second["base"]["response"]["result"]["next_cursor"]["next_position"] == "2"
                    ledger = client.get(ledger_url, params=params).json()
                    op_context["ledger_digest"] = digest(ledger)
            request["base_request"]["context"]["request_id"] = "read"
            request["base_request"]["request"].update(
                schema_version="prodocux_archive_read_request_v1",
                operation="read",
                request_id="read",
                budget={
                    **ledger["limits"],
                    "max_elapsed_ms": "300000" if large else "30000",
                    "max_returned_bytes": "1024",
                    "max_source_bytes": str(source_size) if large else "1048576",
                    "max_entries": "64",
                    "max_expanded_bytes": "1048576",
                    "max_metadata_bytes": "1048576",
                    "max_volumes": "1",
                },
                selector={
                    "kind": "entry",
                    "ordinal": "0",
                    "display_name": member_name,
                    "raw_name_sha256": sha256(member_name.encode()).hexdigest(),
                },
                link_policy="metadata_only",
                requested_range={"start": "0", "end": "14"},
            )
        result = client.post(url, json=request)
        assert result.status_code == 200
        if isolated:
            assert result.json()["decision"] == "accepted"
            wire = {
                "schema_version": "prodocux_archive_request_envelope_v3",
                "mode": "negotiated",
                "base": request["base_request"],
                "profile_binding": result.json()["binding"],
            }
            read_url = ROOT + "/archives/read"
            altered = deepcopy(wire)
            altered["base"]["request"]["requested_range"]["end"] = "13"
            assert client.post(read_url, json=altered).status_code == 409
            altered = deepcopy(wire)
            altered["base"]["request"]["selector"]["raw_name_sha256"] = "0" * 64
            denied = client.post(read_url, json=altered)
            assert denied.status_code == 409
            assert denied.json()["reason_code"] == "PROFILE_BINDING_CHANGED"
            response = client.post(read_url, json=wire)
            assert response.status_code == 200
            receipt = response.json()
            validate("result_envelope_v3", receipt)
            assert receipt["base"]["read_proof"] is not None, receipt["base"][
                "response"
            ]
            assert (
                receipt["base"]["read_proof"]["member_sha256"]
                == sha256(b"archive marker").hexdigest()
            )
            committed = client.get(ledger_url, params=params).json()
            assert digest(committed) == receipt["base"]["committed_ledger_digest"]
            assert client.post(read_url, json=wire).json() == receipt
            if not large:
                for limit, value in (
                    ("max_returned_bytes", "13"),
                    ("max_peak_memory_bytes", str((512 << 20) + 1)),
                    ("max_elapsed_ms", "30001"),
                ):
                    oversized = deepcopy(wire["base"])
                    oversized["context"]["ledger_digest"] = digest(committed)
                    oversized["request"]["budget"][limit] = value
                    rejected = client.post(url, json={**request, "base_request": oversized})
                    assert rejected.status_code == 422, rejected.json()
                    assert rejected.json()["reason_code"] == "INVALID_RANGE"
                    assert client.get(ledger_url, params=params).json() == committed
                if has_links:
                    from base64 import b64decode

                    first = 2 if profile == "zip64-store-deflate" else 3
                    for index, name in enumerate(SELECTOR_NAMES):
                        variant = deepcopy(wire["base"])
                        case = f"exact-selector-{index}"
                        variant["context"].update(request_id=case, ledger_digest=digest(committed))
                        variant["request"].update(
                            request_id=case,
                            selector={
                                "kind": "entry",
                                "ordinal": str(first + index),
                                "display_name": name,
                                "raw_name_sha256": sha256(name.encode()).hexdigest(),
                            },
                            requested_range={"start": "0", "end": "1"},
                        )
                        selected = client.post(url, json={**request, "base_request": variant}).json()
                        assert selected.get("decision") == "accepted", selected
                        selected = client.post(read_url, json={
                            **wire, "base": variant, "profile_binding": selected["binding"],
                        }).json()
                        validate("result_envelope_v3", selected)
                        data = selected["base"]["response"]["result"]
                        assert b64decode(data["bytes_b64"]) == bytes([65 + index])
                        committed = client.get(ledger_url, params=params).json()
                        assert digest(committed) == selected["base"]["committed_ledger_digest"]
                cases = [("wrong-name", "PROFILE_BINDING_CHANGED"), ("tiny-expansion", "BUDGET_EXHAUSTED")]
                if has_links:
                    cases.append(("link", "PROFILE_NOT_APPLICABLE"))
                if profile.startswith("tar"):
                    cases.append(("hardlink", "PROFILE_NOT_APPLICABLE"))
                for case, reason in cases:
                    variant = deepcopy(wire["base"])
                    variant["context"].update(request_id=case, ledger_digest=digest(committed))
                    variant["request"]["request_id"] = case
                    selector = variant["request"]["selector"]
                    if case == "wrong-name":
                        selector["raw_name_sha256"] = "0" * 64
                    elif case == "tiny-expansion":
                        variant["request"]["budget"]["max_expanded_bytes"] = "1"
                    else:
                        ordinal = 2 if case == "hardlink" or profile == "zip-store-deflate" else 1
                        selector.update(ordinal=str(ordinal), display_name=case, raw_name_sha256=sha256(case.encode()).hexdigest())
                    negotiated = client.post(url, json={**request, "base_request": variant}).json()
                    assert negotiated.get("decision") == "accepted", negotiated
                    refused = client.post(read_url, json={
                        **wire, "base": variant, "profile_binding": negotiated["binding"],
                    }).json()
                    validate("result_envelope_v3", refused)
                    assert refused["base"]["response"]["reason_codes"] == [reason], refused
                    assert refused["base"]["response"]["result"] is None
                    assert refused["base"]["read_proof"] is None
                    committed = client.get(ledger_url, params=params).json()
                    assert digest(committed) == refused["base"]["committed_ledger_digest"]
                adversarial = deepcopy(wire["base"])
                adversarial["context"].update(
                    request_id="wrong-selector", ledger_digest=digest(committed)
                )
                adversarial["request"]["request_id"] = "wrong-selector"
                adversarial["request"]["selector"]["ordinal"] = "99"
                binding = client.post(
                    url, json={**request, "base_request": adversarial}
                ).json()
                assert binding.get("decision") == "accepted", binding
                rejected = client.post(
                    read_url,
                    json={**wire, "base": adversarial, "profile_binding": binding["binding"]},
                ).json()
                validate("result_envelope_v3", rejected)
                assert rejected["base"]["response"]["reason_codes"] == ["INVALID_RANGE"]
                assert rejected["base"]["response"]["result"] is None
                assert rejected["base"]["read_proof"] is None
                committed = client.get(ledger_url, params=params).json()
                assert digest(committed) == rejected["base"]["committed_ledger_digest"]
            if member_name.endswith(".txt"):
                from prodocux_kernel.intake.documents import read_document

                content = b"archive marker"
                projection = read_document(member_name, content)
                op_base = deepcopy(request["base_request"])
                op_base["context"].update(
                    request_id="resolve", ledger_digest=digest(committed)
                )
                op_base["request"] = {
                    **{
                        key: op_base["request"][key]
                        for key in ("source_ref", "view", "budget")
                    },
                    "schema_version": "prodocux_archive_resolve_request_v1",
                    "request_id": "resolve",
                    "operation": "resolve",
                    "chain": receipt["base"]["response"]["result"]["chain"],
                    "document": {
                        "source_sha256": sha256(content).hexdigest(),
                        "parser_contract": projection["parser_contract"],
                        "projection_digest": digest(projection),
                        "locator": projection["text_items"][0]["source_locator"],
                    },
                    "quote": {
                        "start": "0",
                        "end": "14",
                        "normalization": "unicode_nfc_codepoint_v1",
                        "sha256": sha256(content).hexdigest(),
                    },
                }
                result = client.post(
                    url, json={**request, "base_request": op_base}
                ).json()
                assert result["decision"] == "accepted", result
                resolved = client.post(
                    ROOT + "/archives/resolve",
                    json={
                        **wire,
                        "base": op_base,
                        "profile_binding": result["binding"],
                    },
                ).json()
                validate("result_envelope_v3", resolved)
                assert (
                    resolved["base"]["response"]["result"]["text"] == "archive marker"
                ), resolved
                assert (
                    resolved["base"]["document_origin"]["origin"]["content_sha256"]
                    == sha256(content).hexdigest()
                )

            if profile == "zip-store-deflate":
                from docx import Document
                from reportlab.pdfgen.canvas import Canvas

                from prodocux_kernel.intake.docx import profile_docx_bytes
                from prodocux_kernel.intake.pdf_projection import (
                    extract_pdf_continuable_projection,
                )

                marker = b"archive PDF marker inside a nested ZIP"
                pdf = BytesIO()
                canvas = Canvas(pdf, invariant=True)
                canvas.drawString(50, 750, marker.decode())
                canvas.showPage()
                canvas.showPage()
                canvas.save()
                pdf_bytes = pdf.getvalue()
                docx = Document()
                docx.add_paragraph(marker.decode())
                docx_output = BytesIO()
                docx.save(docx_output)
                docx_bytes = docx_output.getvalue()
                inner, outer = BytesIO(), BytesIO()
                with tarfile.open(fileobj=inner, mode="w:gz") as archive:
                    member = tarfile.TarInfo("leaf.pdf")
                    member.size = len(pdf_bytes)
                    archive.addfile(member, BytesIO(pdf_bytes))
                tar_bytes = gzip.decompress(inner.getvalue())
                truncated = {
                    codec: compress(tar_bytes)[:-1]
                    for codec, compress in (
                        ("gzip", gzip.compress), ("bzip2", bz2.compress), ("xz", lzma.compress),
                    )
                }
                with tarfile.open(fileobj=outer, mode="w") as archive:
                    for name, content in (
                        ("inner.tar.gz", inner.getvalue()),
                        *(("broken-" + codec, part) for codec, part in truncated.items()),
                        ("leaf.docx", docx_bytes),
                    ):
                        member = tarfile.TarInfo(name)
                        member.size = len(content)
                        archive.addfile(member, BytesIO(content))
                payload = outer.getvalue()
                checksum = sha256(payload).hexdigest()
                nested_session = ROOT + "/source-sessions/nested-pdf"
                nested_plan = deepcopy(plan)
                nested_plan.update(
                    session_id="nested-pdf", operation_id="nested-operation"
                )
                nested_plan["volumes"][0]["declared_size_bytes"] = str(len(payload))
                nested_plan["upload_chunks"][0].update(
                    range={"start": "0", "end": str(len(payload))},
                    sha256=checksum,
                )
                assert (
                    client.post(ROOT + "/source-sessions", json=nested_plan).status_code
                    == 201
                )
                assert (
                    client.put(
                        nested_session + "/volumes/part/chunks",
                        content=payload,
                        headers={
                            "x-archive-range": f"0:{len(payload)}",
                            "x-archive-sha256": checksum,
                        },
                    ).status_code
                    == 204
                )
                nested_lease = client.post(nested_session + "/seal").json()
                nested_ledger = client.get(
                    ledger_url,
                    params={**params, "source_ref": nested_lease["source_ref"]},
                ).json()
                projection = extract_pdf_continuable_projection(pdf_bytes)
                chain = []
                parent = nested_lease["bundle_digest"]
                root_profile = next(
                    row for row in catalog["profiles"]
                    if row["definition"]["profile_id"] == "tar-ustar-pax-gnu"
                )
                decoder = digest({
                    "execution_profile_digest": root_profile["execution_profile_digest"],
                })
                inner_profile = next(
                    row
                    for row in catalog["profiles"]
                    if row["definition"]["profile_id"] == "tar-gzip"
                )
                inner_decoder = digest(
                    {
                        "execution_profile_digest": inner_profile[
                            "execution_profile_digest"
                        ]
                    }
                )
                for name, content, selected_decoder in (
                    ("inner.tar.gz", inner.getvalue(), decoder),
                    ("leaf.pdf", pdf_bytes, inner_decoder),
                ):
                    output = sha256(content).hexdigest()
                    chain.append(
                        {
                            "parent_digest": parent,
                            "selector": {
                                "kind": "entry",
                                "ordinal": "0",
                                "display_name": name,
                                "raw_name_sha256": sha256(name.encode()).hexdigest(),
                            },
                            "decoder_attestation_digest": selected_decoder,
                            "output_semantics": "embedded_bytes",
                            "output_sha256": output,
                            "output_size_bytes": str(len(content)),
                            "integrity": "verified",
                        }
                    )
                    parent = output
                op_base["context"].update(
                    request_id="nested-resolve",
                    operation_id="nested-operation",
                    source_lease_digest=digest(nested_lease),
                    ledger_digest=digest(nested_ledger),
                )
                op_base["request"].update(
                    request_id="nested-resolve",
                    source_ref=nested_lease["source_ref"],
                    chain=chain,
                    budget={
                        **op_base["request"]["budget"],
                        "max_returned_bytes": "65536",
                    },
                    document={
                        "source_sha256": parent,
                        "parser_contract": projection["parser_contract"],
                        "projection_digest": digest(projection),
                        "locator": "1",
                    },
                    quote={
                        "start": "0",
                        "end": str(len(marker)),
                        "normalization": "unicode_nfc_codepoint_v1",
                        "sha256": sha256(marker).hexdigest(),
                    },
                )
                for target in ("nested-qualified-profiles", "document-leaf-handoff"):
                    profile_entry = next(
                        row
                        for row in catalog["profiles"]
                        if row["definition"]["profile_id"] == target
                    )
                    target_ledger = client.get(
                        ledger_url,
                        params={
                            "source_ref": nested_lease["source_ref"],
                            "profile_id": target,
                        },
                    ).json()
                    op_base["context"].update(
                        request_id=target,
                        profile_digest=profile_entry["execution_profile_digest"],
                        ledger_digest=digest(target_ledger),
                    )
                    op_base["request"]["request_id"] = target
                    result = client.post(
                        url,
                        json={
                            **request,
                            "base_request": op_base,
                            "profile_id": target,
                            "profile_contract": profile_entry["definition"][
                                "profile_contract"
                            ],
                            "expected_profile_digest": profile_entry[
                                "definition_digest"
                            ],
                        },
                    ).json()
                    assert result.get("decision") == "accepted", result
                    if target == "nested-qualified-profiles":
                        for field in ("parent_digest", "decoder_attestation_digest", "depth"):
                            forged = deepcopy(op_base)
                            if field == "depth":
                                forged["request"]["budget"]["max_depth"] = "1"
                            else:
                                forged["request"]["chain"][1][field] = "0" * 64
                            denied = client.post(
                                url,
                                json={
                                    **request,
                                    "base_request": forged,
                                    "profile_id": target,
                                    "profile_contract": profile_entry["definition"][
                                        "profile_contract"
                                    ],
                                    "expected_profile_digest": profile_entry[
                                        "definition_digest"
                                    ],
                                },
                            ).json()
                            assert (
                                denied.get("binding") is None
                                and "reason_code" in denied
                            ), denied
                    resolved = client.post(
                        ROOT + "/archives/resolve",
                        json={
                            **wire,
                            "base": op_base,
                            "profile_binding": result["binding"],
                        },
                    ).json()
                    validate("result_envelope_v3", resolved)
                    assert (
                        resolved["base"]["response"]["result"]["text"]
                        == marker.decode()
                    ), resolved
                    response = resolved["base"]["response"]
                    assert response["observed"]["depth"] == "2"
                    assert response["outcome"] == "partial"
                    assert response["coverage"]["document"]["omissions"] == [
                        "ocr_required_not_performed"
                    ]
                    if target == "nested-qualified-profiles":
                        for ordinal, (codec, part) in enumerate(truncated.items(), 1):
                            ledger = client.get(ledger_url, params={
                                "source_ref": nested_lease["source_ref"], "profile_id": target,
                            }).json()
                            variant = deepcopy(op_base)
                            case = "broken-" + codec
                            variant["context"].update(request_id=case, ledger_digest=digest(ledger))
                            variant["request"]["request_id"] = case
                            first, second = variant["request"]["chain"]
                            first["selector"].update(
                                ordinal=str(ordinal), display_name=case,
                                raw_name_sha256=sha256(case.encode()).hexdigest(),
                            )
                            first.update(output_sha256=sha256(part).hexdigest(), output_size_bytes=str(len(part)))
                            second["parent_digest"] = first["output_sha256"]
                            second["decoder_attestation_digest"] = digest({
                                "execution_profile_digest": next(
                                    row["execution_profile_digest"] for row in catalog["profiles"]
                                    if row["definition"]["profile_id"] == "tar-" + codec
                                ),
                            })
                            negotiated = client.post(url, json={
                                **request, "base_request": variant, "profile_id": target,
                                "profile_contract": profile_entry["definition"]["profile_contract"],
                                "expected_profile_digest": profile_entry["definition_digest"],
                            }).json()
                            assert negotiated.get("decision") == "accepted", negotiated
                            refused = client.post(ROOT + "/archives/resolve", json={
                                **wire, "base": variant, "profile_binding": negotiated["binding"],
                            }).json()
                            validate("result_envelope_v3", refused)
                            assert refused["base"]["response"]["reason_codes"] == ["INTEGRITY_FAILED"], refused
                            assert refused["base"]["response"]["result"] is None
                            assert refused["base"]["document_origin"] is None
                    if target == "document-leaf-handoff":
                        docx_request = deepcopy(op_base)
                        ledger = client.get(ledger_url, params={
                            "source_ref": nested_lease["source_ref"], "profile_id": target,
                        }).json()
                        docx_request["context"].update(request_id="docx-leaf", ledger_digest=digest(ledger))
                        profiled = profile_docx_bytes(docx_bytes, filename="leaf.docx")
                        profiled["parser_contract"] = {"name": profiled["schema_version"], "version": "1"}
                        profiled["coverage"] = {
                            "disposition": "partial_unknown",
                            "omitted_content_classes": ["docx_non_paragraph_content_not_cited"],
                        }
                        docx_hash = sha256(docx_bytes).hexdigest()
                        docx_request["request"].update(
                            request_id="docx-leaf",
                            chain=[{
                                **chain[0],
                                "selector": {
                                    "kind": "entry", "ordinal": "4", "display_name": "leaf.docx",
                                    "raw_name_sha256": sha256(b"leaf.docx").hexdigest(),
                                },
                                "output_sha256": docx_hash, "output_size_bytes": str(len(docx_bytes)),
                            }],
                            document={
                                "source_sha256": docx_hash, "parser_contract": profiled["parser_contract"],
                                "projection_digest": digest(profiled), "locator": "paragraph:1",
                            },
                        )
                        negotiated = client.post(url, json={
                            **request, "base_request": docx_request, "profile_id": target,
                            "profile_contract": profile_entry["definition"]["profile_contract"],
                            "expected_profile_digest": profile_entry["definition_digest"],
                        }).json()
                        assert negotiated.get("decision") == "accepted", negotiated
                        cited = client.post(ROOT + "/archives/resolve", json={
                            **wire, "base": docx_request, "profile_binding": negotiated["binding"],
                        }).json()
                        assert "base" in cited, cited
                        validate("result_envelope_v3", cited)
                        assert cited["base"]["response"]["result"]["text"] == marker.decode()
                        assert cited["base"]["response"]["outcome"] == "partial"
                        for case, expected in (
                            ("wrong-pdf-quote", "PROFILE_BINDING_CHANGED"),
                            ("ocr-required", "OCR_REQUIRED"),
                            ("wrong-member-ordinal", "INVALID_RANGE"),
                            ("wrong-projection", "PROFILE_BINDING_CHANGED"),
                            ("wrong-parser", "PROFILE_BINDING_CHANGED"),
                            ("nested-expanded-budget", "BUDGET_EXHAUSTED"),
                        ):
                            after = client.get(
                                ledger_url,
                                params={
                                    "source_ref": nested_lease["source_ref"],
                                    "profile_id": target,
                                },
                            ).json()
                            forged = deepcopy(op_base)
                            forged["context"].update(
                                request_id=case, ledger_digest=digest(after)
                            )
                            forged["request"]["request_id"] = case
                            if case == "wrong-pdf-quote":
                                forged["request"]["quote"]["sha256"] = "0" * 64
                            elif case == "ocr-required":
                                forged["request"]["document"]["locator"] = "2"
                            elif case == "wrong-member-ordinal":
                                forged["request"]["chain"][1]["selector"]["ordinal"] = (
                                    "9"
                                )
                            elif case == "wrong-projection":
                                forged["request"]["document"]["projection_digest"] = "0" * 64
                            elif case == "wrong-parser":
                                forged["request"]["document"]["parser_contract"]["version"] = "999"
                            else:
                                forged["request"]["budget"]["max_expanded_bytes"] = "32"
                            invalid = client.post(
                                url,
                                json={
                                    **request,
                                    "base_request": forged,
                                    "profile_id": target,
                                    "profile_contract": profile_entry["definition"][
                                        "profile_contract"
                                    ],
                                    "expected_profile_digest": profile_entry[
                                        "definition_digest"
                                    ],
                                },
                            ).json()
                            assert invalid.get("decision") == "accepted", invalid
                            rejected = client.post(
                                ROOT + "/archives/resolve",
                                json={
                                    **wire,
                                    "base": forged,
                                    "profile_binding": invalid["binding"],
                                },
                            ).json()
                            validate("result_envelope_v3", rejected)
                            assert rejected["base"]["response"]["reason_codes"] == [
                                expected
                            ]
                            assert rejected["base"]["response"]["result"] is None
                            assert rejected["base"]["document_origin"] is None
                            if case == "ocr-required":
                                assert (
                                    rejected["base"]["response"]["outcome"]
                                    == "requires_input"
                                )
                                assert rejected["base"]["response"]["coverage"][
                                    "document"
                                ]["omissions"] == ["ocr_required_not_performed"]

        else:
            assert result.json()["availability"]["reason_codes"] == [
                "PROFILE_UNQUALIFIED"
            ]
            assert result.json()["binding"] is None
        request["base_request"]["context"]["ledger_digest"] = "0" * 64
        assert client.post(url, json=request).status_code == 409
        if isolated and not large:
            from api.archives import host, now_ms
            from prodocux_kernel.archive_intake.execution import _limits

            ledger = client.get(ledger_url, params=params).json()
            crash_base = deepcopy(wire["base"])
            crash_base["context"].update(
                request_id="interrupted", ledger_digest=digest(ledger)
            )
            crash_base["request"]["request_id"] = "interrupted"
            accepted = client.post(url, json={**request, "base_request": crash_base}).json()
            assert accepted.get("decision") == "accepted", accepted
            owner = Identity(
                "prodocux-sidecar", "default",
                sha256(b"test-archive-first").hexdigest(),
            )
            store = ArchiveSources(tmp_path / "sources.sqlite", ttl_ms=86400000)
            store.reserve_wire(
                owner, lease, crash_base, accepted["binding"],
                _limits(crash_base["request"], lease), now_ms(),
            )
            host.cache_clear()
            blocked = client.get(ledger_url, params=params).json()
            assert blocked["state"] == "blocked"
            assert blocked["attempts"][-1]["state"] == "reserved"
            retry = client.post(read_url, json={
                **wire, "base": crash_base, "profile_binding": accepted["binding"],
            })
            assert retry.status_code == 409
            assert retry.json()["reason_code"] == "OPERATION_RECONCILIATION_REQUIRED"
            assert client.get(ledger_url, params=params).json() == blocked
            binding = accepted["binding"]
            reconcile = session + "/reconcile/" + binding["negotiation_id"]
            assert client.post(reconcile, json={"source_bytes": "0"}).status_code == 400
            assert client.post(reconcile, headers={
                "Authorization": "Bearer test-archive-second",
            }).status_code == 404
            pending = client.post(reconcile)
            assert pending.status_code == 409
            assert pending.json()["reason_code"] == "OPERATION_RECONCILIATION_REQUIRED"
            store.settle_wire(lease, binding, "interrupted", None)
            measured = {
                **dict.fromkeys(COUNTERS, 0),
                "source_bytes": source_size,
                "volumes": 1,
                "elapsed_ms": 1,
            }
            store.record_reconciliation_cost(lease, binding, "interrupted", measured)
            with pytest.raises(ArchiveError, match="PROFILE_BINDING_CHANGED"):
                store.record_reconciliation_cost(
                    lease, binding, "interrupted", {**measured, "elapsed_ms": 2},
                )
            settled = client.post(reconcile)
            assert settled.status_code == 200, settled.json()
            result = settled.json()
            validate("resource_ledger_v2", result)
            assert result["attempts"][-1]["state"] == "settled"
            assert result["state"] == "active"
            assert client.post(reconcile).json() == result
            assert client.get(ledger_url, params=params).json() == result

            malformed = source_prefix
            bad_plan = deepcopy(plan)
            bad_plan.update(session_id="malformed", operation_id="malformed-operation")
            bad_plan["volumes"][0]["declared_size_bytes"] = str(len(malformed))
            bad_checksum = sha256(malformed).hexdigest()
            bad_plan["upload_chunks"] = [{
                "volume_key": "part",
                "range": {"start": "0", "end": str(len(malformed))},
                "sha256": bad_checksum,
            }]
            assert client.post(ROOT + "/source-sessions", json=bad_plan).status_code == 201
            bad_session = ROOT + "/source-sessions/malformed"
            assert client.put(
                bad_session + "/volumes/part/chunks", content=malformed,
                headers={
                    "x-archive-range": f"0:{len(malformed)}",
                    "x-archive-sha256": bad_checksum,
                },
            ).status_code == 204
            bad_lease = client.post(bad_session + "/seal").json()
            bad_ledger = client.get(ledger_url, params={
                **params, "source_ref": bad_lease["source_ref"],
            }).json()
            crash_base["context"].update(
                request_id="malformed-read", operation_id="malformed-operation",
                source_lease_digest=digest(bad_lease), ledger_digest=digest(bad_ledger),
            )
            crash_base["request"].update(
                request_id="malformed-read", source_ref=bad_lease["source_ref"],
            )
            accepted = client.post(url, json={**request, "base_request": crash_base}).json()
            assert accepted.get("decision") == "accepted", accepted
            invalid = client.post(read_url, json={
                **wire, "base": crash_base, "profile_binding": accepted["binding"],
            }).json()
            validate("result_envelope_v3", invalid)
            assert invalid["base"]["response"]["reason_codes"] == ["INTEGRITY_FAILED"]
            assert invalid["base"]["response"]["result"] is None
            assert invalid["base"]["read_proof"] is None
        close = {
            "schema_version": "prodocux_archive_source_control_v2",
            "session_id": "owned-test",
            "operation_id": "operation",
            "expected_lease_digest": digest(lease),
            "action": "revoke",
            "requested_expiry_ms": None,
        }
        assert (
            client.post(session + "/control", json=close).json()["state"] == "revoked"
        )
        assert client.post(url, json=request).status_code == 404


@pytest.fixture
def wire_reservation(tmp_path):
    database = tmp_path / "wire.sqlite"
    store = ArchiveSources(database, ttl_ms=1000)
    owner = Identity("authority", "tenant", "principal")
    scope = {
        "authority_id": "authority",
        "tenant_id": "tenant",
        "principal_id": "principal",
    }
    archive_bytes = BytesIO()
    with ZipFile(archive_bytes, "w") as archive:
        archive.writestr("owned.txt", b"archive marker")
    raw = archive_bytes.getvalue()
    checksum = sha256(raw).hexdigest()
    plan = {
        "schema_version": "prodocux_archive_source_admission_v2",
        "session_id": "session",
        "operation_id": "operation",
        "authority_binding": scope,
        "policy_digest": store.policy,
        "mode": "chunked_snapshot",
        "expires_at_ms": "900",
        "volumes": [
            {"ordinal": "0", "volume_key": "part", "declared_size_bytes": str(len(raw))}
        ],
        "upload_chunks": [
            {
                "volume_key": "part",
                "range": {"start": "0", "end": str(len(raw))},
                "sha256": checksum,
            }
        ],
        "expected_bundle_digest": None,
    }
    store.create(owner, plan, 1)
    store.upload(owner, "session", "part", 0, len(raw), checksum, raw, 1)
    lease = store.seal(owner, "session", 1)
    profile_digest = digest("test execution profile")
    ledger = store.initial_ledger(owner, lease, profile_digest, 1)
    request = {
        "request_id": "read-1",
        "operation": "read",
        "view": "container",
        "source_ref": lease["source_ref"],
        "requested_range": {"start": "0", "end": "1"},
        "selector": {
            "kind": "entry",
            "ordinal": "0",
            "display_name": "owned.txt",
            "raw_name_sha256": sha256(b"owned.txt").hexdigest(),
        },
        "parent_chain": [],
        "link_policy": "metadata_only",
        "budget": {
            **ledger["limits"],
            "max_elapsed_ms": "30000",
            "max_returned_bytes": "1024",
            "max_source_bytes": "1048576",
            "max_entries": "64",
            "max_expanded_bytes": "1048576",
            "max_metadata_bytes": "1048576",
            "max_volumes": "1",
        },
    }
    base = {
        "request": request,
        "context": {
            "operation_id": "operation",
            "request_id": "read-1",
            "profile_digest": profile_digest,
            "source_lease_digest": digest(lease),
            "ledger_digest": digest(ledger),
            "credential_ref": None,
            "external_binding_digests": [],
        },
    }
    contract = {"name": "test-profile", "version": "1"}
    binding = {
        "negotiation_id": "negotiation",
        "catalog_digest": digest("test catalog"),
        "profile_id": "zip-store-deflate",
        "profile_contract": contract,
        "profile_digest": digest("test profile"),
        "execution_profile_digest": profile_digest,
        "source_bundle_digest": lease["bundle_digest"],
        "source_chain_digest": digest([]),
        "operation_id": "operation",
        "operation": "read",
        "view": "container",
        "request_digest": digest(request),
        "authority_scope": scope,
        "issued_at_ms": "1",
        "expires_at_ms": "800",
    }
    store.save_binding(
        owner,
        lease,
        {
            "schema_version": "prodocux_archive_negotiation_result_v3",
            "request_id": "read-1",
            "profile_id": "test-profile",
            "profile_contract": contract,
            "catalog_digest": binding["catalog_digest"],
            "decision": "accepted",
            "http_status": 200,
            "availability": {
                "support_status": "qualified",
                "availability": "available",
                "reason_codes": [],
            },
            "binding": binding,
        },
        1,
    )
    accepted = store.saved_binding(owner, lease, binding, 1)
    return database, owner, lease, base, accepted, ledger, len(raw)


def test_wire_reservation_survives_restart_without_qualification_claim(
    wire_reservation,
):
    database, owner, lease, base, accepted, ledger, size = wire_reservation
    store = ArchiveSources(database, ttl_ms=1000)
    binding = accepted["binding"]
    cost = dict.fromkeys(COUNTERS, 0)
    cost["source_bytes"] = size
    changed = deepcopy(base)
    changed["request"]["requested_range"]["end"] = "2"
    with pytest.raises(ArchiveError, match="PROFILE_BINDING_CHANGED"):
        store.reserve_wire(owner, lease, changed, binding, cost, 2)
    crash = subprocess.run(
        [sys.executable, "-B", "-c", """
import json, os, sys
from prodocux_kernel.archive_intake.authority import Identity
from prodocux_kernel.archive_intake.sources import ArchiveSources
database, identity, lease, base, binding, cost = json.load(sys.stdin)
ArchiveSources(database, ttl_ms=1000).reserve_wire(
    Identity(*identity), lease, base, binding, cost, 2
)
os._exit(37)
"""],
        input=json.dumps([str(database), ["authority", "tenant", "principal"], lease, base, binding, cost]),
        text=True,
        timeout=30,
        check=False,
    )
    assert crash.returncode == 37
    store = ArchiveSources(database, ttl_ms=1000)
    reserved = store.initial_ledger(owner, lease, binding["execution_profile_digest"], 3)
    assert reserved["previous_ledger_digest"] == digest(ledger)
    assert reserved["state"] == "blocked"
    store = ArchiveSources(database, ttl_ms=1000)
    with pytest.raises(ArchiveError, match="OPERATION_RECONCILIATION_REQUIRED"):
        store.reserve_wire(owner, lease, base, binding, cost, 3)
    unknown = store.settle_wire(lease, binding, "read-1", None)
    assert unknown["attempts"][0]["state"] == "unknown_cost"
    settled = store.settle_wire(lease, binding, "read-1", cost)
    assert settled["previous_ledger_digest"] == digest(unknown)
    assert settled["consumed"]["source_bytes"] == str(size)
    assert (
        store.initial_ledger(owner, lease, binding["execution_profile_digest"], 3)
        == settled
    )


@pytest.mark.parametrize("action", ["close", "revoke"])
def test_in_flight_source_control_accounts_cost_without_publication(wire_reservation, action):
    import sqlite3

    database, owner, lease, base, accepted, _, size = wire_reservation
    store = ArchiveSources(database, ttl_ms=1000)
    binding = accepted["binding"]
    cost = {**dict.fromkeys(COUNTERS, 0), "source_bytes": size}
    store.reserve_wire(owner, lease, base, binding, cost, 2)
    store.control(owner, lease["session_id"], {
        "schema_version": "prodocux_archive_source_control_v2",
        "session_id": lease["session_id"],
        "operation_id": lease["operation_id"],
        "expected_lease_digest": digest(lease),
        "action": action,
        "requested_expiry_ms": None,
    }, 3)

    def forbidden_receipt(_):
        pytest.fail("revoked or closed source must not publish a receipt")

    settled = store.settle_wire(lease, binding, base["request"]["request_id"], cost, make_receipt=forbidden_receipt)
    assert settled["attempts"][0]["state"] == "settled"
    assert settled["observed"]["source_bytes"] == str(size)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM archive_wire_receipt").fetchone() == (0,)
    with pytest.raises(ArchiveError, match="SOURCE_NOT_FOUND"):
        store.wire_receipt(owner, lease, binding, 4)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object")
def test_worker_wire_receipt_is_atomic_and_replayed(wire_reservation):
    from prodocux_kernel.archive_intake.execution import execute_operation

    database, owner, lease, base, accepted, _, size = wire_reservation
    store = ArchiveSources(database, ttl_ms=1000)
    receipt = execute_operation(
        store, owner, lease, base, accepted, clock=lambda: 2, network_isolated=False
    )
    validate("result_envelope_v3", receipt)
    assert receipt["base"]["response"]["outcome"] == "partial"
    assert receipt["base"]["read_proof"]["full_integrity_verified"] is False
    assert receipt["base"]["read_proof"]["member_sha256"] is None
    store = ArchiveSources(database, ttl_ms=1000)
    ledger = store.initial_ledger(
        owner, lease, accepted["binding"]["execution_profile_digest"], 3
    )
    assert ledger["consumed"]["source_bytes"] == str(size)
    assert ledger["attempts"][0]["state"] == "settled"
    assert receipt["base"]["committed_ledger_digest"] == digest(ledger)
    assert (
        execute_operation(store, owner, lease, base, accepted, clock=lambda: 3)
        == receipt
    )
    altered = deepcopy(base)
    altered["context"]["source_lease_digest"] = "0" * 64
    with pytest.raises(ArchiveError, match="PROFILE_BINDING_CHANGED"):
        execute_operation(store, owner, lease, altered, accepted, clock=lambda: 3)
    with pytest.raises(ArchiveError, match="NEGOTIATION_EXPIRED"):
        execute_operation(store, owner, lease, base, accepted, clock=lambda: 800)
    assert (
        store.initial_ledger(
            owner, lease, accepted["binding"]["execution_profile_digest"], 3
        )
        == ledger
    )


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("PRODOCUX_TEST_APPCONTAINER") != "1",
    reason="requires Windows AppContainer profile creation",
)
def test_appcontainer_worker_commits_receipt(wire_reservation):
    from prodocux_kernel.archive_intake.execution import execute_operation

    database, owner, lease, base, accepted, _, size = wire_reservation
    store = ArchiveSources(database, ttl_ms=1000)
    receipt = execute_operation(store, owner, lease, base, accepted, clock=lambda: 2)
    validate("result_envelope_v3", receipt)
    assert receipt["base"]["response"]["result"]["bytes_b64"] == "YQ=="
    ledger = store.initial_ledger(
        owner, lease, accepted["binding"]["execution_profile_digest"], 3
    )
    assert ledger["observed"]["source_bytes"] == str(size)
    assert int(ledger["observed"]["peak_memory_bytes"]) > 0
    assert digest(ledger) == receipt["base"]["committed_ledger_digest"]


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("PRODOCUX_TEST_APPCONTAINER") != "1",
    reason="requires Windows AppContainer profile creation",
)
def test_appcontainer_network_has_reachable_control():
    import socket
    import sys
    from pathlib import Path

    from prodocux_kernel.archive_intake._appcontainer import (
        isolated_runtime,
        launch_isolated,
    )

    with (
        socket.socket() as listener,
        isolated_runtime(sys._base_executable, []) as (root, _, sid),
    ):
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        address = listener.getsockname()
        with socket.create_connection(address, timeout=2):
            connection, _ = listener.accept()
            connection.close()
        script = f"""
import socket
try:
    with socket.create_connection({address!r}, timeout=2):
        raise SystemExit(1)
except TimeoutError:
    raise SystemExit(42)
except OSError as exc:
    raise SystemExit(42 if exc.winerror == 10013 else 2)
"""
        result = launch_isolated(
            root / Path(sys._base_executable).name,
            ["-I", "-S", "-B", "-c", script],
            root,
            sid,
            assign=lambda handle: None,
            timeout=10,
        )
        assert result == 42
        listener.setblocking(False)
        with pytest.raises(BlockingIOError):
            listener.accept()


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("PRODOCUX_TEST_APPCONTAINER") != "1",
    reason="requires Windows AppContainer profile creation",
)
def test_revocation_terminates_started_appcontainer(wire_reservation):
    from pathlib import Path
    from time import monotonic

    from prodocux_kernel.archive_intake._appcontainer import (
        isolated_runtime,
        launch_isolated,
    )

    database, owner, lease, *_ = wire_reservation
    store = ArchiveSources(database, ttl_ms=1000)
    with isolated_runtime(sys._base_executable, []) as (root, scratch, sid):
        started = scratch / "started"
        finished = scratch / "finished"
        script = (
            "from pathlib import Path; from time import sleep; import sys; "
            "Path(sys.argv[1]).touch(); sleep(60); Path(sys.argv[2]).touch()"
        )

        def check_active():
            if started.exists():
                store.control(owner, lease["session_id"], {
                    "schema_version": "prodocux_archive_source_control_v2",
                    "session_id": lease["session_id"],
                    "operation_id": lease["operation_id"],
                    "expected_lease_digest": digest(lease),
                    "action": "revoke",
                    "requested_expiry_ms": None,
                }, 3)
            store.lookup(owner, lease["source_ref"], 3)

        before = monotonic()
        with pytest.raises(ArchiveError, match="SOURCE_NOT_FOUND"):
            launch_isolated(
                root / Path(sys._base_executable).name,
                ["-I", "-S", "-B", "-c", script, str(started), str(finished)],
                root,
                sid,
                assign=lambda handle: None,
                timeout=15,
                check_active=check_active,
            )
        assert started.is_file() and not finished.exists()
        assert monotonic() - before < 15
