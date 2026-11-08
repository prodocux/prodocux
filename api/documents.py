"""Additive portable-document HTTP entry points."""
import base64
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from prodocux_kernel.intake.documents import (
    document_capabilities,
    inspect_document,
    read_document,
    resolve_document,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/v1/intake/documents")


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    document_filename: str = Field(min_length=1, max_length=255)
    document_b64: str = Field(max_length=5_592_408)


class ReadRequest(InspectRequest):
    cursor: dict[str, Any] | None = None
    max_bytes: int = Field(default=65536, ge=1, le=2_097_152)
    max_records: int = Field(default=512, ge=1, le=20000)


class ResolveRequest(InspectRequest):
    source_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    parser_contract: dict[str, str]
    locator: str = Field(max_length=8192)
    quote_start: int = Field(ge=0)
    quote_end: int = Field(gt=0)
    quote_sha256: str = Field(pattern="^[a-f0-9]{64}$")


async def execute(request, model, operation):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 6 * 1024 * 1024:
            return JSONResponse({"code": "REQUEST_TOO_LARGE"}, status_code=413)
        raw.extend(chunk)
    try:
        parsed = model.model_validate_json(raw)
        payload = base64.b64decode(parsed.document_b64, validate=True)
        args = parsed.model_dump(exclude={"document_filename", "document_b64"})
        result = await run_in_threadpool(operation, parsed.document_filename, payload, **args)
        if isinstance(result, str):
            result = {"quote": result}
        return JSONResponse(result)
    except (ValidationError, ValueError) as exc:
        code = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, ValidationError) else "REQUEST_INVALID"
        if not code.replace("_", "").isalnum() or len(code) > 96:
            code = "REQUEST_INVALID"
        return JSONResponse({"code": code}, status_code=413 if code in
                            {"SOURCE_TOO_LARGE", "INTAKE_SOURCE_SIZE_LIMIT"} else 422)


@router.get("/capabilities")
def capabilities():
    return document_capabilities()


@router.post("/inspect")
async def inspect(request: Request):
    return await execute(request, InspectRequest, inspect_document)


@router.post("/read")
async def read(request: Request):
    return await execute(request, ReadRequest, read_document)


@router.post("/resolve")
async def resolve(request: Request):
    return await execute(request, ResolveRequest, resolve_document)
