"""Trusted internal read command for a host-controlled immutable source."""

import base64
import json
import sys
from contextlib import ExitStack
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from time import monotonic_ns
from unicodedata import normalize

import rfc8785

from .decoders import ArchiveError, Budget, open_container
from .replay import MemberSelector, selected_member, snapshot


def _embedded(archive, step):
    if step["output_semantics"] != "embedded_bytes" or step["integrity"] != "verified":
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    selector = step["selector"]
    if selector["kind"] != "entry":
        raise ArchiveError("PROFILE_NOT_APPLICABLE")
    member = selected_member(
        archive, MemberSelector(int(selector["ordinal"]), selector["display_name"])
    )
    if member.size > archive.budget.max_returned_bytes - archive.budget.returned_bytes:
        raise ArchiveError("BUDGET_EXHAUSTED")
    if member.raw_name_sha256 != selector["raw_name_sha256"]:
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    result = archive.read(member.ordinal, 0, member.size)
    if (
        result.member_sha256 != step["output_sha256"]
        or str(result.member_size) != step["output_size_bytes"]
    ):
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    return member, result


def main():
    source, expected_digest, profile, ordinal, name_json, start, end, *options = (
        sys.argv[1:]
    )
    budget = Budget(**json.loads(options[0])) if options else Budget()
    raw_name_digest = options[1] if len(options) > 1 else None
    chain_profiles = json.loads(options[2]) if len(options) > 2 else []
    started = monotonic_ns()
    try:
        with (
            open(source, "rb") as input_file,
            snapshot(input_file, budget) as (stored, digest),
        ):
            if digest != expected_digest:
                raise ArchiveError("SOURCE_CHANGED")
            with open_container(stored, profile, budget) as archive:
                if ordinal == "inventory":
                    members, next_start = archive.page(int(start), int(end))
                    rows = [asdict(item) for item in members]
                    budget.charge(
                        "returned_bytes",
                        len(json.dumps(rows, ensure_ascii=True).encode("ascii")),
                    )
                    result = {
                        "members": rows,
                        "next_start": next_start,
                        "total": len(archive.members),
                    }
                elif ordinal == "resolve":
                    result = _resolve(
                        archive, json.loads(name_json), budget, chain_profiles
                    )
                else:
                    result = _read(
                        archive, ordinal, name_json, start, end, raw_name_digest
                    )
    except ArchiveError as error:
        result = {"reason_code": str(error)}
    result["observed"] = {
        key: str(getattr(budget, key))
        for key in (
            "source_bytes",
            "expanded_bytes",
            "returned_bytes",
            "metadata_bytes",
            "entries",
        )
    }
    result["observed"]["elapsed_ms"] = str(
        (monotonic_ns() - started + 999_999) // 1_000_000
    )
    print(json.dumps(result))


def _read(archive, ordinal, name_json, start, end, raw_name_digest):
    member = selected_member(
        archive, MemberSelector(int(ordinal), json.loads(name_json))
    )
    if raw_name_digest is not None and member.raw_name_sha256 != raw_name_digest:
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    requested_end = int(end)
    actual_end = min(requested_end, member.size)
    result = asdict(archive.read(member.ordinal, int(start), actual_end))
    result["returned_end"] = str(actual_end)
    result["verified_eof"] = actual_end < requested_end
    result["data"] = base64.b64encode(result["data"]).decode("ascii")
    return result


def _resolve(archive, request, budget, profiles):
    chain = request["chain"]
    if not 1 <= len(chain) <= budget.max_depth:
        raise ArchiveError("BUDGET_EXHAUSTED")
    with ExitStack() as stack:
        if len(profiles) != len(chain) or profiles[0] != archive.profile:
            raise ArchiveError("PROFILE_BINDING_CHANGED")
        for step, profile in zip(chain[:-1], profiles[1:], strict=True):
            _, result = _embedded(archive, step)
            archive = stack.enter_context(
                open_container(BytesIO(result.data), profile, budget)
            )
        member, result = _embedded(archive, chain[-1])
    if result.member_sha256 != request["document"]["source_sha256"]:
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    return _quote(member, result, request, budget)


def _text_items(member, result):
    from ._text_projection import inspect, read

    name = member.name
    extension = PurePosixPath(name).suffix.lower()
    format_name = {
        ".txt": "txt",
        ".md": "markdown",
        ".markdown": "markdown",
        ".log": "log",
        ".tsv": "tsv",
    }.get(extension)
    if not format_name or any(character in name for character in ("/", chr(92), ":")):
        raise ArchiveError("PROFILE_NOT_APPLICABLE")
    if not 0 < member.size <= 4 << 20:
        raise ArchiveError("BUDGET_EXHAUSTED")

    class Snapshot:
        source_sha256 = result.member_sha256
        size = member.size

        def read_at(self, offset, limit):
            return result.data[offset : offset + limit]

    source = Snapshot()
    info = inspect(source, format_name)
    try:
        page = read(source, format_name)
    except ValueError as error:
        raise ArchiveError("INTEGRITY_FAILED") from error
    items = [
        {
            "source_locator": json.dumps(
                row["locator"], ensure_ascii=False, separators=(",", ":")
            ),
            "text": row["text"],
            "type": "physical_line",
        }
        for row in page["records"]
    ]
    projection = {
        "schema_version": "prodocux_document_read_v1",
        "source": {
            "source_sha256": source.source_sha256,
            "size_bytes": source.size,
            "extension": extension,
            "payload_validated": True,
            "admission": "portable",
            "parser_contract": info["parser_contract"],
        },
        "parser_contract": info["parser_contract"],
        "text_items": items,
        "next_cursor": page["next_cursor"],
        "coverage": {
            "disposition": "complete" if page["complete"] else "partial_unknown",
            "omitted_content_classes": [],
        },
        "metadata": {},
    }
    return projection, items


def _quote(member, result, request, budget):
    suffix = PurePosixPath(member.name).suffix.lower()
    if suffix == ".pdf":
        from prodocux_kernel.intake.pdf_projection import (
            extract_pdf_continuable_projection,
        )

        try:
            projection = extract_pdf_continuable_projection(result.data)
        except ValueError as error:
            raise ArchiveError("INTEGRITY_FAILED") from error
        items = [
            {"source_locator": str(page["page_number"]), "text": page["text"]}
            for page in projection["pages"]
            if not page["ocr_required"]
        ]
    elif suffix == ".docx":
        from prodocux_kernel.intake.docx import profile_docx_bytes

        try:
            projection = profile_docx_bytes(result.data, filename=member.name)
        except ValueError as error:
            raise ArchiveError("INTEGRITY_FAILED") from error
        projection["parser_contract"] = {
            "name": projection["schema_version"],
            "version": "1",
        }
        projection["coverage"] = {
            "disposition": "partial_unknown",
            "omitted_content_classes": ["docx_non_paragraph_content_not_cited"],
        }
        if projection["preview_truncated"]:
            projection["coverage"]["omitted_content_classes"].append("docx_preview_limit")
        items = [
            {"source_locator": f"paragraph:{row['index']}", "text": row["text"]}
            for row in projection["paragraphs"]
        ]
    else:
        projection, items = _text_items(member, result)
    document = request["document"]
    if (
        document["parser_contract"] != projection["parser_contract"]
        or document["projection_digest"]
        != sha256(rfc8785.dumps(projection)).hexdigest()
    ):
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    item = next(
        (item for item in items if item["source_locator"] == document["locator"]), None
    )
    if item is None:
        if suffix == ".pdf" and any(
            str(page["page_number"]) == document["locator"] and page["ocr_required"]
            for page in projection["pages"]
        ):
            return {
                "reason_code": "OCR_REQUIRED",
                "omissions": ["ocr_required_not_performed"],
                "depth": len(request["chain"]),
            }
        raise ArchiveError("INVALID_RANGE")
    text = normalize("NFC", item["text"])
    quote = request["quote"]
    start, end = int(quote["start"]), int(quote["end"])
    if not 0 <= start < end <= len(text):
        raise ArchiveError("INVALID_RANGE")
    selected = text[start:end]
    encoded = selected.encode()
    if sha256(encoded).hexdigest() != quote["sha256"]:
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    budget.charge("returned_bytes", len(encoded))
    return {
        "text": selected,
        "complete": projection["coverage"]["disposition"] == "complete",
        "omissions": projection["coverage"]["omitted_content_classes"],
        "depth": len(request["chain"]),
    }
