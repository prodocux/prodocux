"""Build and commit a read receipt from a trusted worker, behind the execution gate."""

from base64 import b64decode
from hashlib import sha256
from json import dumps

from .authority import COUNTERS
from .contracts import digest, strict_load
from .decoders import STREAMS, ZIP_PROFILES, ArchiveError
from .process_guard import run_archive_worker

PORTABLE = ZIP_PROFILES | set(STREAMS) | {"tar-ustar-pax-gnu"}
CHAIN_PROFILES = {"nested-qualified-profiles", "document-leaf-handoff"}
OPERATIONS = {"inspect", "list", "read", "resolve"}


def verify_selection(sources, owner, lease, base, profile, now, chain_profiles=()):
    request = base["request"]
    operation = request["operation"]
    if (
        profile not in PORTABLE | CHAIN_PROFILES
        or operation not in OPERATIONS
        or (profile in CHAIN_PROFILES and operation != "resolve")
        or request["view"] != "container"
        or request.get("parent_chain")
        or base["context"]["credential_ref"]
        or base["context"]["external_binding_digests"]
        or (
            operation == "read"
            and (
                request["selector"]["kind"] != "entry"
                or request["link_policy"] != "metadata_only"
            )
        )
    ):
        raise ArchiveError("PROFILE_NOT_APPLICABLE")
    if operation == "resolve":
        chain = request["chain"]
        if not 1 <= len(chain) <= int(request["budget"]["max_depth"]) or any(
            step["parent_digest"] != parent
            or step["integrity"] != "verified"
            or step["output_semantics"] != "embedded_bytes"
            or step["output_sha256"] is None
            for step, parent in zip(
                chain,
                [
                    lease["bundle_digest"],
                    *(item["output_sha256"] for item in chain[:-1]),
                ],
                strict=True,
            )
        ):
            raise ArchiveError("PROFILE_NOT_APPLICABLE")
    root = chain_profiles[0] if chain_profiles else profile
    prefix = (
        b"PK\x03\x04"
        if root == "zip-store-deflate"
        else {"gzip": b"\x1f\x8b", "bzip2": b"BZh", "xz": b"\xfd7zX"}.get(
            STREAMS.get(root)
        )
    )
    if prefix and not sources.source_signature(owner, lease, now).startswith(prefix):
        raise ArchiveError("PROFILE_MISMATCH")
    if operation == "list" and request["cursor"] is not None:
        sources.verify_list_cursor(owner, lease, request["cursor"], now)
    _limits(request, lease)


def _limits(request, lease):
    limits = {key: int(request["budget"]["max_" + key]) for key in COUNTERS}
    span = request.get("requested_range")
    if (
        not all(limits.values())
        or (
            span
            and not 0
            <= int(span["end"]) - int(span["start"])
            <= limits["returned_bytes"]
        )
        or limits["returned_bytes"] > 1 << 20
        or limits["elapsed_ms"]
        > (
            300_000
            if int(lease["bundle"]["volumes"][0]["size_bytes"]) > 64 << 20
            else 30_000
        )
        or limits["peak_memory_bytes"] > 512 << 20
        or limits["source_bytes"] < int(lease["bundle"]["volumes"][0]["size_bytes"])
    ):
        raise ArchiveError("INVALID_RANGE")
    return limits


def _result_binding(lease, binding):
    return {
        "source_bundle_digest": lease["bundle_digest"],
        "chain_digest": digest([]),
        "profile_digest": binding["execution_profile_digest"],
        "decoder_attestation_digest": digest(
            {"execution_profile_digest": binding["execution_profile_digest"]}
        ),
    }


def _cursor(lease, binding, position):
    wire = _result_binding(lease, binding)
    return {
        **{k: v for k, v in wire.items() if k != "chain_digest"},
        "parent_chain_digest": wire["chain_digest"],
        "view": binding["view"],
        "next_position": str(position),
    }


def _worker_arguments(request, lease, binding, proposed):
    if request["operation"] == "read":
        selector = request["selector"]
        span = request["requested_range"]
        args = [
            selector["ordinal"],
            dumps(selector["display_name"]),
            span["start"],
            span["end"],
        ]
        raw_name = selector["raw_name_sha256"]
    elif request["operation"] == "resolve":
        args = ["resolve", dumps(request), "0", "0"]
        raw_name = ""
    else:
        cursor = request.get("cursor")
        start = int(cursor["next_position"]) if cursor else 0
        if cursor and cursor != _cursor(lease, binding, start):
            raise ArchiveError("PROFILE_BINDING_CHANGED")
        limit = int(request["max_entries"]) if request["operation"] == "list" else 1
        if not 0 < limit <= min(256, proposed["entries"]):
            raise ArchiveError("INVALID_RANGE")
        args = ["inventory", "null", str(start), str(limit)]
        raw_name = ""
    options = {
        "max_" + key: proposed[key]
        for key in (
            "source_bytes",
            "expanded_bytes",
            "returned_bytes",
            "metadata_bytes",
            "entries",
            "depth",
        )
    }
    return [*args, dumps(options), raw_name]


def execute_operation(
    sources,
    owner,
    lease,
    base,
    accepted,
    *,
    clock,
    worker=run_archive_worker,
    network_isolated=True,
    chain_profiles=(),
):
    request = base["request"]
    binding = accepted["binding"]
    verify_selection(
        sources, owner, lease, base, binding["profile_id"], clock(), chain_profiles
    )
    proposed = _limits(request, lease)
    worker_args = _worker_arguments(request, lease, binding, proposed)
    now = clock()
    context = base["context"]
    if (
        digest(request) != binding["request_digest"]
        or context["request_id"] != request["request_id"]
        or context["operation_id"] != lease["operation_id"]
        or context["source_lease_digest"] != digest(lease)
        or context["profile_digest"] != binding["execution_profile_digest"]
        or request["source_ref"] != lease["source_ref"]
    ):
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    if not int(binding["issued_at_ms"]) <= now < int(binding["expires_at_ms"]):
        raise ArchiveError("NEGOTIATION_EXPIRED")
    if sources.saved_binding(owner, lease, binding, now) != accepted:
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    if receipt := sources.wire_receipt(owner, lease, binding, clock()):
        return receipt
    sources.reserve_wire(owner, lease, base, binding, proposed, clock())
    measured = dict.fromkeys(COUNTERS, 0)

    def peak(value):
        measured["peak_memory_bytes"] = value

    def check_active():
        sources.lookup(owner, lease["source_ref"], clock())

    try:
        with sources.worker_snapshot(owner, lease, clock()) as path:
            volume = lease["bundle"]["volumes"][0]
            duration = proposed["elapsed_ms"] / 1000
            worker_args[-2] = dumps(
                {
                    **strict_load(worker_args[-2].encode("utf-8")),
                    "deadline_seconds": duration,
                }
            )
            raw = worker(
                [
                    str(path),
                    volume["sha256"],
                    chain_profiles[0] if chain_profiles else binding["profile_id"],
                    *worker_args,
                    dumps(chain_profiles),
                ],
                wall_seconds=duration,
                cpu_seconds=duration,
                memory_bytes=proposed["peak_memory_bytes"],
                observe_peak=peak,
                network_isolated=network_isolated,
                check_active=check_active,
            )
        data = strict_load(raw)
        for key in (
            "source_bytes",
            "expanded_bytes",
            "returned_bytes",
            "metadata_bytes",
            "entries",
        ):
            measured[key] = int(data["observed"][key])
        measured.update(
            elapsed_ms=int(data["observed"]["elapsed_ms"]),
            depth=int(data.get("depth", 1)),
            volumes=1,
        )
        if not measured["peak_memory_bytes"]:
            raise ArchiveError("EXECUTION_UNKNOWN")
        response, proof = _operation_response(
            request, lease, binding, data, measured, proposed
        )

        def receipt(committed):
            return {
                "schema_version": "prodocux_archive_result_envelope_v3",
                "mode": "negotiated",
                "profile_binding_digest": digest(binding),
                "profile_availability": accepted["availability"],
                "base": {
                    "schema_version": "prodocux_archive_result_envelope_v2",
                    "request_id": request["request_id"],
                    "operation_id": lease["operation_id"],
                    "source_lease_digest": digest(lease),
                    "committed_ledger_digest": digest(committed),
                    "response": response,
                    "read_proof": proof,
                    "document_origin": _document_origin(request, lease)
                    if request["operation"] == "resolve"
                    and response["result"] is not None
                    else None,
                },
            }

        sources.settle_wire(
            lease, binding, request["request_id"], measured, make_receipt=receipt
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        sources.settle_wire(lease, binding, request["request_id"], None)
        if isinstance(error, ArchiveError) and str(error) in (
            "SOURCE_NOT_FOUND",
            "SOURCE_LEASE_EXPIRED",
        ):
            raise
        raise ArchiveError("EXECUTION_UNKNOWN") from error
    return sources.wire_receipt(owner, lease, binding, clock())


def _operation_response(request, lease, binding, data, measured, proposed):
    coverage = {
        axis: {
            "disposition": "not_evaluated",
            "known_total": None,
            "evaluated": [],
            "unknown_remainder": False,
            "omissions": [],
        }
        for axis in ("inventory", "member", "document")
    }
    code = data.get("reason_code")
    if any(measured[key] > proposed[key] for key in COUNTERS):
        code = "BUDGET_EXHAUSTED"
    response = {
        "schema_version": f"prodocux_archive_{request['operation']}_result_v1",
        "operation": request["operation"],
        "request_id": request["request_id"],
        "outcome": "failed",
        "reason_codes": [code] if code else [],
        "binding": None,
        "coverage": coverage,
        "observed": {key: str(value) for key, value in measured.items()},
        "consumed": {
            key: str(min(value, proposed[key])) for key, value in measured.items()
        },
        "result": None,
    }
    if code:
        if code in ("CREDENTIAL_REQUIRED", "VOLUME_MISSING", "OCR_REQUIRED"):
            response["outcome"] = "requires_input"
        if code == "OCR_REQUIRED":
            coverage["document"].update(
                disposition="partial_unknown",
                unknown_remainder=True,
                omissions=data["omissions"],
            )
        return response, None
    if request["operation"] != "read":
        response.update(outcome="succeeded", binding=_result_binding(lease, binding))
        if request["operation"] == "inspect":
            response["result"] = {
                "classification": {
                    "format_id": binding["profile_id"],
                    "codecs": [],
                    "view": binding["view"],
                },
                "capabilities": {
                    "inspect": "available",
                    "list": "not_evaluated",
                    "read": "not_evaluated",
                    "resolve": "not_evaluated",
                },
            }
        elif request["operation"] == "resolve":
            response["binding"]["chain_digest"] = digest(request["chain"])
            response["result"] = {
                key: request[key] for key in ("chain", "document", "quote")
            }
            response["result"]["text"] = data["text"]
            if not data["complete"]:
                response["outcome"] = "partial"
                response["coverage"]["document"].update(
                    disposition="partial_unknown",
                    unknown_remainder=True,
                    omissions=data["omissions"],
                )
        else:
            _list_result(response, request, lease, binding, data)
        return response, None
    payload = b64decode(data["data"], validate=True)
    span = {"start": request["requested_range"]["start"], "end": data["returned_end"]}
    if (
        len(payload) != int(span["end"]) - int(span["start"])
        or not int(span["start"])
        <= int(span["end"])
        <= int(request["requested_range"]["end"])
        or sha256(payload).hexdigest() != data["range_sha256"]
        or len(payload) > measured["returned_bytes"]
    ):
        raise ArchiveError("EXECUTION_UNKNOWN")
    full = data["eof_verified"]
    member_size = str(data["member_size"]) if full else None
    member_sha = data["member_sha256"] if full else None
    decoder = digest({"execution_profile_digest": binding["execution_profile_digest"]})
    chain = [
        {
            "parent_digest": lease["bundle_digest"],
            "selector": request["selector"],
            "decoder_attestation_digest": decoder,
            "output_semantics": "embedded_bytes",
            "output_sha256": member_sha,
            "output_size_bytes": member_size,
            "integrity": "verified" if full else "partial",
        }
    ]
    response.update(
        outcome="succeeded" if full else "partial",
        binding={
            "source_bundle_digest": lease["bundle_digest"],
            "chain_digest": digest(chain),
            "profile_digest": binding["execution_profile_digest"],
            "decoder_attestation_digest": decoder,
        },
        result={
            "chain": chain,
            "returned_range": span,
            "bytes_b64": data["data"],
            "returned_sha256": data["range_sha256"],
            "member_sha256": member_sha,
            "member_size_bytes": member_size,
            "integrity_scope": "full_member" if full else "returned_range_only",
        },
    )
    origin = (
        {
            "kind": "verified_member",
            "source_bundle_digest": lease["bundle_digest"],
            "chain_digest": digest(chain),
            "volume_key": None,
            "content_sha256": member_sha,
            "content_size_bytes": member_size,
            "representation_contract": None,
            "producer_attestation_digest": None,
        }
        if full
        else None
    )
    proof = {
        "schema_version": "prodocux_archive_read_proof_v2",
        "range": span,
        "available_range": {"start": "0", "end": member_size or span["end"]},
        "range_sha256": data["range_sha256"],
        "eof_verified": full,
        "full_integrity_verified": full,
        "member_sha256": member_sha,
        "member_size_bytes": member_size,
        "short_read_reason": "verified_eof" if data["verified_eof"] else "none",
        "origin": origin,
    }
    return response, proof


def _list_result(response, request, lease, binding, data):
    cursor = request["cursor"]
    start = int(cursor["next_position"]) if cursor else 0
    members = []
    for row in data["members"]:
        selector = {
            "kind": "entry",
            "ordinal": str(row["ordinal"]),
            "display_name": row["name"],
            "raw_name_sha256": row["raw_name_sha256"],
        }
        kind = {
            "link": "symlink",
            "hardlink": "hardlink",
            "directory": "directory",
        }.get(row["kind"], "file")
        members.append(
            {
                "member_id": digest(
                    {
                        "source_bundle_digest": lease["bundle_digest"],
                        "parent_chain_digest": digest([]),
                        "selector": selector,
                    }
                ),
                "selector": selector,
                "kind": kind,
                "declared_size_bytes": str(row["size"]),
                "content_presence": "embedded"
                if row["kind"] == "file"
                else "metadata_only",
                "integrity": "metadata_only",
            }
        )
    end = start + len(members)
    total = data["total"]
    span = {"start": str(start), "end": str(end)}
    response["result"] = {
        "members": members,
        "returned_range": span,
        "known_total": str(total),
        "next_cursor": _cursor(lease, binding, end)
        if data["next_start"] is not None
        else None,
    }
    response["coverage"]["inventory"].update(
        disposition="complete" if start == 0 and end == total else "partial_known",
        known_total=str(total),
        evaluated=[span] if members else [],
    )


def _document_origin(request, lease):
    document = request["document"]
    step = request["chain"][-1]
    return {
        "schema_version": "prodocux_archive_document_origin_v2",
        "origin": {
            "kind": "verified_member",
            "source_bundle_digest": lease["bundle_digest"],
            "chain_digest": digest(request["chain"]),
            "volume_key": None,
            "content_sha256": step["output_sha256"],
            "content_size_bytes": step["output_size_bytes"],
            "representation_contract": None,
            "producer_attestation_digest": None,
        },
        "parser_contract": document["parser_contract"],
        "projection_digest": document["projection_digest"],
        "locator": document["locator"],
        "quote": request["quote"],
    }
