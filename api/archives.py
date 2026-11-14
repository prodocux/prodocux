"""Authenticated archive intake transport over frozen request contracts."""

import re
from functools import lru_cache, wraps
from hashlib import sha256
from pathlib import Path
from time import time_ns

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from api.auth import (
    auth_profile_ok,
    client_certificate_verified,
    configured_bearer_tokens,
    mtls_required,
)
from prodocux_kernel.archive_intake.authority import Identity
from prodocux_kernel.archive_intake.contracts import reasons, strict_load, validate
from prodocux_kernel.archive_intake.decoders import ArchiveError
from prodocux_kernel.archive_intake.negotiation import Negotiation
from prodocux_kernel.archive_intake.sources import CHUNK_LIMIT, ArchiveSources, scope

router = APIRouter(prefix="/v1/intake")
SAFE_RANGE = re.compile(r"(0|[1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})")


@lru_cache(maxsize=4)
def host(database, ttl, isolated_zip_read=False, large_sources=False):
    return Negotiation(
        ArchiveSources(database, ttl_ms=ttl, large_sources=large_sources),
        isolated_zip_read=isolated_zip_read,
    )


def _configured():
    import os

    database = os.environ.get("PRODOCUX_ARCHIVE_DATABASE")
    if not database:
        raise ArchiveError("PROFILE_UNQUALIFIED")
    ttl = os.environ.get("PRODOCUX_ARCHIVE_TTL_MS", "900000")
    if (
        not ttl.isascii()
        or not ttl.isdecimal()
        or len(ttl) > 10
        or not 0 < int(ttl) <= 86400000
    ):
        raise ArchiveError("PROFILE_UNQUALIFIED")
    return host(
        Path(database),
        int(ttl),
        os.environ.get("PRODOCUX_ARCHIVE_ISOLATED_ZIP_READ") == "1",
        os.environ.get("PRODOCUX_ARCHIVE_LARGE_SOURCES") == "1",
    )


def _identity(request):
    import secrets

    scheme, _, credential = request.headers.get("authorization", "").partition(" ")
    if (
        not auth_profile_ok()
        or scheme.lower() != "bearer"
        or not credential.isascii()
        or not any(
            secrets.compare_digest(credential, item)
            for item in configured_bearer_tokens()
            if item.isascii()
        )
    ):
        raise ArchiveError("UNAUTHENTICATED")
    if mtls_required() and not client_certificate_verified(
        request.headers,
        peer=request.client.host if request.client else None,
    ):
        raise ArchiveError("UNAUTHENTICATED")
    # Existing sidecar credentials share a deployment. Each credential owns its sessions.
    return Identity(
        "prodocux-sidecar", "default", sha256(credential.encode("ascii")).hexdigest()
    )


async def _body(request, limit=CHUNK_LIMIT):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise ArchiveError("SOURCE_TOO_LARGE")
        data.extend(chunk)
    return bytes(data)


def _route(phase):
    def decorate(endpoint):
        @wraps(endpoint)
        async def guarded(request, **kwargs):
            try:
                return await endpoint(request, **kwargs)
            except ArchiveError as error:
                code = str(error)
                spec = reasons()[code]
                value = {
                    "schema_version": "prodocux_archive_error_report_v3",
                    "request_id": None,
                    "operation_ref": None,
                    "reason_code": code,
                    "http_status": spec["http_status"],
                    "phase": phase
                    if phase in spec["allowed_phases"]
                    else spec["allowed_phases"][0],
                    "execution_disposition": spec["execution_disposition"],
                    "retry_hint": spec["retry_hint"],
                    "receipt_ref": None,
                }
                validate("error_report_v3", value)
                return JSONResponse(value, status_code=spec["http_status"])

        return guarded

    return decorate


def now_ms():
    return time_ns() // 1_000_000


@router.get("/archives/capabilities")
@_route("negotiation")
async def capabilities(request: Request):
    owner = _identity(request)
    service = await run_in_threadpool(_configured)
    return await run_in_threadpool(service.catalog, owner, now_ms())


@router.get("/source-sessions/policy")
@_route("admission")
async def source_policy(request: Request):
    owner = _identity(request)
    service = await run_in_threadpool(_configured)
    return {
        "authority_binding": scope(owner),
        "policy_digest": service.sources.policy,
        "host_time_ms": str(now_ms()),
        "max_ttl_ms": str(service.sources.ttl_ms),
        "max_source_bytes": str(service.sources.source_limit),
        "max_chunk_bytes": str(service.sources.chunk_limit),
    }


@router.post("/source-sessions", status_code=201)
@_route("admission")
async def create(request: Request):
    owner = _identity(request)
    service = await run_in_threadpool(_configured)
    plan = strict_load(await _body(request))
    return await run_in_threadpool(service.sources.create, owner, plan, now_ms())


@router.put("/source-sessions/{session}/volumes/{volume}/chunks", status_code=204)
@_route("admission")
async def upload(request: Request, session: str, volume: str):
    owner = _identity(request)
    service = await run_in_threadpool(_configured)
    span = SAFE_RANGE.fullmatch(request.headers.get("x-archive-range", ""))
    checksum = request.headers.get("x-archive-sha256", "")
    if span is None or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise ArchiveError("MALFORMED_REQUEST")
    start, end = map(int, span.groups())
    await run_in_threadpool(
        service.sources.upload,
        owner,
        session,
        volume,
        start,
        end,
        checksum,
        await _body(request, service.sources.chunk_limit),
        now_ms(),
    )


@router.post("/source-sessions/{session}/seal")
@_route("admission")
async def seal(request: Request, session: str):
    owner = _identity(request)
    service = await run_in_threadpool(_configured)
    return await run_in_threadpool(service.sources.seal, owner, session, now_ms())


@router.post("/source-sessions/{session}/control")
@_route("admission")
async def control(request: Request, session: str):
    owner = _identity(request)
    service = await run_in_threadpool(_configured)
    value = strict_load(await _body(request))
    return await run_in_threadpool(
        service.sources.control, owner, session, value, now_ms()
    )


@router.post("/archives/negotiate")
@_route("negotiation")
async def negotiate(request: Request):
    owner = _identity(request)
    service = await run_in_threadpool(_configured)
    value = strict_load(await _body(request))
    return await run_in_threadpool(service.negotiate, owner, value, now_ms())


@router.get("/source-sessions/ledger")
@_route("pre_execution")
async def ledger(request: Request, source_ref: str, profile_id: str):
    owner = _identity(request)
    service = await run_in_threadpool(_configured)
    return await run_in_threadpool(
        service.ledger, owner, source_ref, profile_id, now_ms()
    )


@router.post("/source-sessions/{session}/reconcile/{negotiation_id}")
@_route("reconciliation")
async def reconcile(request: Request, session: str, negotiation_id: str):
    owner = _identity(request)
    if await _body(request):
        raise ArchiveError("MALFORMED_REQUEST")
    service = await run_in_threadpool(_configured)
    return await run_in_threadpool(
        service.sources.reconcile_wire, owner, session, negotiation_id, now_ms()
    )


@router.post("/archives/{operation}")
@_route("pre_execution")
async def execute(request: Request, operation: str):
    owner = _identity(request)
    service = await run_in_threadpool(_configured)
    value = strict_load(await _body(request))
    return await run_in_threadpool(
        service.execution_gate, owner, value, operation, now_ms()
    )
