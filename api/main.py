"""ProDocuX Kernel — FastAPI service (CONTRACT §4).

Start: python run_kernel.py  → http://localhost:8900/v1
The runtime does not call any LLM API.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response

from api.auth import BearerAuthMiddleware, auth_profile_ok
from api.path_policy import resolve_allowed_input_path
from prodocux_kernel import API_VERSION, FROZEN_MODEL, __version__
from prodocux_kernel.artifacts import ArtifactResolutionError, resolve_opaque_artifact
from prodocux_kernel.config import golden_path
from prodocux_kernel.docops import invariants as inv
from prodocux_kernel.intake import (
    MAX_DOCX_BYTES,
    MAX_IMAGE_BYTES,
    MAX_PDF_BYTES,
    MAX_PRESENTATION_BYTES,
    MAX_TABLE_BYTES,
    MAX_WORKBOOK_BYTES,
    extract_csv_continuable_projection,
    extract_image_tile_projection,
    extract_pdf_bytes,
    extract_pdf_continuable_projection,
    extract_pptx_continuable_projection,
    extract_xlsx_continuable_projection,
    profile_csv,
    profile_csv_bytes,
    profile_docx,
    profile_docx_bytes,
    profile_image_bytes,
    profile_pptx,
    profile_pptx_bytes,
    profile_xlsx,
    profile_xlsx_bytes,
)
from prodocux_kernel.intake.errors import SourceTooLargeError
from prodocux_kernel.models import (
    ArtifactRetrieveRequest,
    ContinuableProjectionRequest,
    CsvContinuableProjectionRequest,
    DerivedArtifactStoreRequest,
    DocumentProfileRequest,
    DocumentProfileResponse,
    ExtractBlocksRequest,
    ImageProfileRequest,
    ImageProfileResponse,
    ImageTileProjectionRequest,
    IntakeCapabilitiesResponse,
    IntakeMaterializeRequest,
    PdfContinuableProjectionRequest,
    PdfExtractPagesRequest,
    PdfExtractPagesResponse,
    PptxContinuableProjectionRequest,
    PresentationProfileRequest,
    PresentationProfileResponse,
    ProjectionCapabilitiesResponse,
    ReviewCommitRequest,
    ReviewCommitResponse,
    ReviewStartRequest,
    ReviewStartResponse,
    ScoreRequest,
    ScoreResponse,
    TableProfileRequest,
    TableProfileResponse,
    ValidateStructureRequest,
    ValidateStructureResponse,
    VersionResponse,
    WorkbookProfileRequest,
    WorkbookProfileResponse,
    XlsxContinuableProjectionRequest,
)
from prodocux_kernel.rendering import (
    FilesystemArtifactSink,
    InMemoryArtifactSink,
    capabilities_document,
    content_blocks_validation_result,
    execute_continuable_projection,
    execute_extract_blocks,
    execute_render_artifact,
)
from prodocux_kernel.rendering.artifact_retrieval import (
    ArtifactRetrievalError,
    ArtifactTooLargeError,
    retrieve_verified_opaque_artifact,
)
from prodocux_kernel.rendering.derived_store import DerivedArtifactStore
from prodocux_kernel.rendering.errors import HTTP_STATUS, RenderContractError
from prodocux_kernel.rendering.filesystem import default_output_mount
from prodocux_kernel.rendering.intake_store import IntakeMaterialStore
from prodocux_kernel.review import capture
from prodocux_kernel.scoring import scorer
from prodocux_kernel.verification import (
    EvidenceValidationError,
    NormalizedDiffError,
    compare_normalized_profiles,
    verify_evidence_bundle,
)
from prodocux_kernel.verification.diff_models import (
    NormalizedDiffRequestV1,
    NormalizedDiffResultV1,
)
from prodocux_kernel.verification.evidence_models import (
    EvidenceBundleRequestV1,
    EvidenceBundleResultV1,
)

app = FastAPI(title="ProDocuX Kernel", version=__version__)
app.add_middleware(BearerAuthMiddleware)

KNOWN_SCHEMAS = [
    "intake_request_v1",
    "intake_response_v1",
    "prodocux_intake_capabilities_v1",
    "pif_tw_v1",
    "prodocux_table_profile_v1",
    "prodocux_workbook_profile_v1",
    "prodocux_docx_profile_v1",
    "prodocux_presentation_profile_v1",
    "prodocux_source_reference_v1",
    "prodocux_evidence_bundle_request_v1",
    "prodocux_evidence_bundle_result_v1",
    "prodocux_image_profile_v1",
    "prodocux_normalized_diff_request_v1",
    "prodocux_normalized_diff_result_v1",
    "prodocux_opaque_artifact_v1",
    "prodocux_content_blocks_v1",
    "prodocux_render_request_v1",
    "prodocux_render_result_v1",
    "prodocux_render_capabilities_v1",
    "prodocux_continuable_projection_v1",
    "prodocux_projection_cursor_v1",
    "prodocux_projection_capabilities_v1",
    "prodocux_pdf_continuable_projection_v1",
    "prodocux_csv_continuable_projection_v1",
    "prodocux_xlsx_continuable_projection_v1",
    "prodocux_pptx_continuable_projection_v1",
    "prodocux_image_tile_projection_v1",
]

_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$")


def _build_render_sink():
    if os.environ.get("PRODOCUX_ARTIFACT_MOUNT", "").strip():
        return FilesystemArtifactSink()
    return InMemoryArtifactSink()


_RENDER_SINK = None
_INTAKE_STORE = None
_DERIVED_STORE = None
_MAX_EXTRACT_BLOCKS_BYTES = 32 * 1024 * 1024


def _render_sink():
    global _RENDER_SINK
    if _RENDER_SINK is None:
        _RENDER_SINK = _build_render_sink()
    return _RENDER_SINK


def _intake_store() -> IntakeMaterialStore:
    global _INTAKE_STORE
    if _INTAKE_STORE is None:
        _INTAKE_STORE = IntakeMaterialStore()
    return _INTAKE_STORE


def _derived_store() -> DerivedArtifactStore:
    global _DERIVED_STORE
    if _DERIVED_STORE is None:
        _DERIVED_STORE = DerivedArtifactStore()
    return _DERIVED_STORE


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "prodocux-kernel"}


@app.get("/ready")
def ready() -> JSONResponse:
    checks: dict[str, bool] = {"process": True}
    mount = os.environ.get("PRODOCUX_ARTIFACT_MOUNT", "").strip()
    if mount:
        root = default_output_mount()
        checks["artifact_mount_writable"] = root.exists() and os.access(root, os.W_OK)
    else:
        checks["artifact_mount_writable"] = True
    checks["auth_profile_ok"] = auth_profile_ok()
    ready_ok = all(checks.values())
    return JSONResponse(
        status_code=200 if ready_ok else 503,
        content={"status": "ready" if ready_ok else "not_ready", "checks": checks},
    )


@app.post("/v1/intake/materialize")
def intake_materialize(req: IntakeMaterializeRequest) -> JSONResponse:
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        raw = base64.b64decode(req.document_b64, validate=True)
        if len(raw) > _MAX_EXTRACT_BLOCKS_BYTES:
            raise ValueError("document exceeds extract-blocks byte limit")
        identity = _intake_store().materialize(
            output_name=req.document_filename,
            media_type=req.media_type,
            payload=raw,
            sha256=req.sha256,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=200, content=dict(identity))


@app.post("/v1/artifacts/derived")
def store_derived_artifact(req: DerivedArtifactStoreRequest) -> JSONResponse:
    try:
        if Path(req.output_name).name != req.output_name:
            raise ValueError("output_name must be a plain basename")
        raw = base64.b64decode(req.content_b64, validate=True)
        if len(raw) > _MAX_EXTRACT_BLOCKS_BYTES:
            raise ValueError("derived artifact exceeds byte limit")
        identity = _derived_store().store(
            output_name=req.output_name,
            media_type=req.media_type,
            payload=raw,
            sha256=req.sha256,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=200, content=dict(identity))


_MAX_RETRIEVAL_BYTES = 32 * 1024 * 1024


@app.post("/v1/artifacts/retrieve")
def retrieve_artifact(req: ArtifactRetrieveRequest) -> JSONResponse:
    """Phase 3 verified retrieval: identity-bound bytes with digest recheck."""
    identity = req.artifact.model_dump()
    try:
        raw = retrieve_verified_opaque_artifact(
            identity,
            intake_store=_intake_store(),
            derived_store=_derived_store(),
            render_sink=_render_sink(),
            max_bytes=_MAX_RETRIEVAL_BYTES,
        )
    except ArtifactTooLargeError as exc:
        return JSONResponse(
            status_code=413,
            content={
                "schema_version": "prodocux_safe_error_v1",
                "ok": False,
                "code": "ARTIFACT_TOO_LARGE",
                "message": str(exc) or "artifact exceeds retrieval byte limit",
                "retryable": False,
                "request_id": req.request_id,
            },
        )
    except (ArtifactRetrievalError, ValueError, KeyError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(
        status_code=200,
        content={
            "schema_version": "prodocux_artifact_content_v1",
            "request_id": req.request_id,
            "artifact": identity,
            "media_type": identity["media_type"],
            "size_bytes": len(raw),
            "sha256": identity["sha256"],
            "content_b64": base64.b64encode(raw).decode("ascii"),
        },
    )


@app.post(
    "/v1/verify/evidence-bundle",
    response_model=EvidenceBundleResultV1,
    response_model_exclude_none=True,
)
def verify_evidence(req: EvidenceBundleRequestV1) -> EvidenceBundleResultV1:
    try:
        result = verify_evidence_bundle(req)
    except EvidenceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EvidenceBundleResultV1.model_validate(result)


@app.post(
    "/v1/compare/normalized-profiles",
    response_model=NormalizedDiffResultV1,
    response_model_exclude_unset=True,
)
def compare_profiles(req: NormalizedDiffRequestV1) -> NormalizedDiffResultV1:
    try:
        result = compare_normalized_profiles(req)
    except NormalizedDiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return NormalizedDiffResultV1.model_validate(result)


@app.post("/v1/intake/extract-pages", response_model=PdfExtractPagesResponse)
def extract_pages(req: PdfExtractPagesRequest) -> PdfExtractPagesResponse:
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        if req.document_filename in {
            ".",
            "..",
        } or not req.document_filename.casefold().endswith(".pdf"):
            raise ValueError("document_filename must end with .pdf")
        if len(req.document_b64) > ((MAX_PDF_BYTES + 2) // 3) * 4:
            raise ValueError("document_b64 exceeds PDF intake limit")
        raw = base64.b64decode(req.document_b64, validate=True)
        pages, truncated = extract_pdf_bytes(
            raw,
            filename=req.document_filename,
            max_pages=req.max_pages,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    total_characters = sum(len(page["text"]) for page in pages)
    status = (
        "ocr_required" if any(page["ocr_required"] for page in pages) else "success"
    )
    return PdfExtractPagesResponse(
        status=status,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        page_count=len(pages),
        pages=pages,
        truncation={"truncated": truncated, "total_characters": total_characters},
    )


@app.post("/v1/intake/extract-pages/continue")
def extract_pages_continue(req: PdfContinuableProjectionRequest) -> JSONResponse:
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        if req.document_filename in {".", ".."} or not req.document_filename.casefold().endswith(".pdf"):
            raise ValueError("document_filename must end with .pdf")
        if len(req.document_b64) > ((MAX_PDF_BYTES + 2) // 3) * 4:
            raise SourceTooLargeError("document exceeds PDF inline intake limit")
        raw = base64.b64decode(req.document_b64, validate=True)
        result = extract_pdf_continuable_projection(
            raw, cursor=req.cursor, max_pages=req.max_pages, ocr_requested=req.ocr_requested
        )
    except SourceTooLargeError as exc:
        raise HTTPException(status_code=413, detail={"code": "SOURCE_TOO_LARGE", "message": str(exc), "retryable": False}) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=200, content=result)


@app.post("/v1/intake/profile-table/continue")
def profile_table_continue(req: CsvContinuableProjectionRequest) -> JSONResponse:
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        if req.document_filename in {".", ".."} or not req.document_filename.casefold().endswith(".csv"):
            raise ValueError("document_filename must end with .csv")
        if len(req.document_b64) > ((MAX_TABLE_BYTES + 2) // 3) * 4:
            raise SourceTooLargeError("document exceeds CSV inline intake limit")
        raw = base64.b64decode(req.document_b64, validate=True)
        result = extract_csv_continuable_projection(
            raw, cursor=req.cursor, max_rows=req.max_rows
        )
    except SourceTooLargeError as exc:
        raise HTTPException(status_code=413, detail={"code": "SOURCE_TOO_LARGE", "message": str(exc), "retryable": False}) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=200, content=result)


@app.post("/v1/intake/profile-workbook/continue")
def profile_workbook_continue(req: XlsxContinuableProjectionRequest) -> JSONResponse:
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        if req.document_filename in {".", ".."} or not req.document_filename.casefold().endswith(".xlsx"):
            raise ValueError("document_filename must end with .xlsx")
        if len(req.document_b64) > ((MAX_WORKBOOK_BYTES + 2) // 3) * 4:
            raise SourceTooLargeError("document exceeds XLSX inline intake limit")
        raw = base64.b64decode(req.document_b64, validate=True)
        result = extract_xlsx_continuable_projection(
            raw, cursor=req.cursor, max_rows=req.max_rows
        )
    except SourceTooLargeError as exc:
        raise HTTPException(status_code=413, detail={"code": "SOURCE_TOO_LARGE", "message": str(exc), "retryable": False}) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=200, content=result)


@app.post("/v1/intake/profile-presentation/continue")
def profile_presentation_continue(req: PptxContinuableProjectionRequest) -> JSONResponse:
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        if req.document_filename in {".", ".."} or not req.document_filename.casefold().endswith(".pptx"):
            raise ValueError("document_filename must end with .pptx")
        if len(req.document_b64) > ((MAX_PRESENTATION_BYTES + 2) // 3) * 4:
            raise SourceTooLargeError("document exceeds PPTX inline intake limit")
        raw = base64.b64decode(req.document_b64, validate=True)
        result = extract_pptx_continuable_projection(raw, cursor=req.cursor, max_slides=req.max_slides)
    except SourceTooLargeError as exc:
        raise HTTPException(status_code=413, detail={"code": "SOURCE_TOO_LARGE", "message": str(exc), "retryable": False}) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=200, content=result)


@app.post("/v1/intake/profile-image/tiles")
def profile_image_tiles(req: ImageTileProjectionRequest) -> JSONResponse:
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        if len(req.document_b64) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
            raise SourceTooLargeError("document exceeds image inline intake limit")
        raw = base64.b64decode(req.document_b64, validate=True)
        result = extract_image_tile_projection(raw, filename=req.document_filename, cursor=req.cursor, max_tiles=req.max_tiles, tile_edge=req.tile_edge, ocr_requested=req.ocr_requested)
    except SourceTooLargeError as exc:
        raise HTTPException(status_code=413, detail={"code": "SOURCE_TOO_LARGE", "message": str(exc), "retryable": False}) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=200, content=result)


@app.post("/v1/intake/extract-blocks")
def extract_blocks(req: ExtractBlocksRequest) -> JSONResponse:
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        if req.document_filename in {".", ".."}:
            raise ValueError("document_filename must be a plain basename")
        if req.document_artifact is not None:
            raw = resolve_opaque_artifact(
                req.document_artifact,
                _intake_store(),
                max_bytes=_MAX_EXTRACT_BLOCKS_BYTES,
            )
        else:
            assert req.document_b64 is not None
            raw = base64.b64decode(req.document_b64, validate=True)
        body = execute_extract_blocks(req.document_filename, raw)
    except RenderContractError as exc:
        raise HTTPException(
            status_code=HTTP_STATUS.get(exc.code, 400), detail=exc.public_message
        ) from exc
    except ArtifactResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=200, content=body)


@app.post("/v1/intake/extract-blocks/continue")
def extract_blocks_continue(req: ContinuableProjectionRequest) -> JSONResponse:
    """Return a deterministic source-bound DOCX block range."""
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        if req.document_filename in {".", ".."}:
            raise ValueError("document_filename must be a plain basename")
        if req.document_artifact is not None:
            raw = resolve_opaque_artifact(
                req.document_artifact,
                _intake_store(),
                max_bytes=_MAX_EXTRACT_BLOCKS_BYTES,
            )
        else:
            assert req.document_b64 is not None
            raw = base64.b64decode(req.document_b64, validate=True)
        body = execute_continuable_projection(
            req.document_filename,
            raw,
            cursor=req.cursor,
            max_blocks=req.max_blocks,
        )
    except RenderContractError as exc:
        raise HTTPException(
            status_code=HTTP_STATUS.get(exc.code, 400),
            detail={"code": exc.code, "message": exc.public_message},
        ) from exc
    except ArtifactResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=200, content=body)


@app.get("/v1/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(
        kernel_version=__version__,
        api_version=API_VERSION,
        frozen_model=FROZEN_MODEL,
        schemas=KNOWN_SCHEMAS,
    )


@app.get(
    "/v1/intake/capabilities",
    response_model=IntakeCapabilitiesResponse,
    response_model_exclude_none=True,
)
def intake_capabilities() -> IntakeCapabilitiesResponse:
    return IntakeCapabilitiesResponse.model_validate(
        {
            "schema_version": "prodocux_intake_capabilities_v1",
            "kernel_version": __version__,
            "api_version": API_VERSION,
            "formats": [
                {
                    "extensions": [".pdf"],
                    "status": "available",
                    "operation": "extract_pages",
                    "max_bytes": MAX_PDF_BYTES,
                    "max_pages": 50,
                    "additional_operations": ["extract_blocks"],
                },
                {
                    "extensions": [".csv"],
                    "status": "available",
                    "operation": "profile_table",
                    "max_bytes": MAX_TABLE_BYTES,
                    "additional_operations": ["extract_blocks"],
                },
                {
                    "extensions": [".docx"],
                    "status": "available",
                    "operation": "profile_document",
                    "max_bytes": MAX_DOCX_BYTES,
                    "additional_operations": [
                        "validate_structure",
                        "extract_blocks",
                        "extract_blocks_continue",
                    ],
                },
                {
                    "extensions": [".pptx"],
                    "status": "available",
                    "operation": "profile_presentation",
                    "max_bytes": MAX_PRESENTATION_BYTES,
                    "additional_operations": ["extract_blocks"],
                },
                {
                    "extensions": [".xlsx"],
                    "status": "available",
                    "operation": "profile_workbook",
                    "max_bytes": MAX_WORKBOOK_BYTES,
                    "additional_operations": ["extract_blocks"],
                },
                {
                    "extensions": [".jpg", ".jpeg", ".png"],
                    "status": "available",
                    "operation": "profile_image",
                    "max_bytes": MAX_IMAGE_BYTES,
                },
                {
                    "extensions": [".xls"],
                    "status": "planned",
                    "operation": "profile_legacy_workbook",
                },
                {
                    "extensions": [".mp4", ".mov", ".mxf"],
                    "status": "external_pipeline_required",
                    "operation": "probe_and_proxy",
                },
                {
                    "extensions": [".r3d"],
                    "status": "external_pipeline_required",
                    "operation": "register_raw_and_proxy",
                },
            ],
        }
    )


@app.get(
    "/v1/intake/projection-capabilities",
    response_model=ProjectionCapabilitiesResponse,
    response_model_exclude_none=True,
)
def projection_capabilities() -> ProjectionCapabilitiesResponse:
    """Disclose source admission and projection ceilings without implying support."""
    common = {
        "artifact_backed_source": False,
        "inline_source": True,
        "spooled_source": False,
        "oversized_source_disposition": "SOURCE_TOO_LARGE",
    }
    return ProjectionCapabilitiesResponse.model_validate(
        {
            "schema_version": "prodocux_projection_capabilities_v1",
            "kernel_version": __version__,
            "api_version": API_VERSION,
            "profiles": [
                {
                    "format": "docx",
                    "extensions": [".docx"],
                    "status": "bounded_with_continuation",
                    "range_units": ["block"],
                    "endpoint": "/v1/intake/extract-blocks/continue",
                    "source_admission": {"max_inline_bytes": MAX_DOCX_BYTES, **common},
                    "limits": {
                        "max_blocks_per_range": 200,
                        "max_table_rows_per_block": 500,
                        "max_table_columns_per_block": 32,
                        "max_text_codepoints": 8192,
                    },
                    "known_uncontinuable_limits": [
                        "source_bytes",
                        "table_rows",
                        "table_columns",
                        "text_codepoints",
                    ],
                },
                {
                    "format": "pdf",
                    "extensions": [".pdf"],
                    "status": "bounded_with_continuation",
                    "range_units": ["page"],
                    "endpoint": "/v1/intake/extract-pages/continue",
                    "source_admission": {"max_inline_bytes": MAX_PDF_BYTES, **common},
                    "limits": {
                        "max_pages": 50,
                        "max_page_characters": 50000,
                        "max_total_characters": 500000,
                    },
                    "known_uncontinuable_limits": [
                        "source_bytes",
                        "page_characters",
                        "total_characters",
                    ],
                },
                {
                    "format": "csv",
                    "extensions": [".csv"],
                    "status": "bounded_with_continuation",
                    "range_units": ["row"],
                    "endpoint": "/v1/intake/profile-table/continue",
                    "source_admission": {"max_inline_bytes": MAX_TABLE_BYTES, **common},
                    "limits": {"max_rows": 500, "max_columns": 32},
                    "known_uncontinuable_limits": ["source_bytes", "columns"],
                },
                {
                    "format": "xlsx",
                    "extensions": [".xlsx"],
                    "status": "bounded_with_continuation",
                    "range_units": ["worksheet_row"],
                    "endpoint": "/v1/intake/profile-workbook/continue",
                    "source_admission": {
                        "max_inline_bytes": MAX_WORKBOOK_BYTES,
                        **common,
                    },
                    "limits": {
                        "max_rows_per_sheet": 500,
                        "max_columns_per_sheet": 32,
                        "max_blocks": 200,
                    },
                    "known_uncontinuable_limits": [
                        "source_bytes",
                        "columns",
                    ],
                },
                {
                    "format": "pptx",
                    "extensions": [".pptx"],
                    "status": "bounded_with_continuation",
                    "range_units": ["slide"],
                    "endpoint": "/v1/intake/profile-presentation/continue",
                    "source_admission": {
                        "max_inline_bytes": MAX_PRESENTATION_BYTES,
                        **common,
                    },
                    "limits": {
                        "max_blocks": 200,
                        "max_paragraphs_per_slide": 50,
                        "max_table_rows": 500,
                        "max_table_columns": 32,
                    },
                    "known_uncontinuable_limits": [
                        "source_bytes",
                        "shapes",
                        "paragraphs",
                        "table_rows",
                        "table_columns",
                    ],
                },
                {
                    "format": "image",
                    "extensions": [".jpg", ".jpeg", ".png"],
                    "status": "bounded_with_continuation",
                    "range_units": ["tile"],
                    "endpoint": "/v1/intake/profile-image/tiles",
                    "source_admission": {"max_inline_bytes": MAX_IMAGE_BYTES, **common},
                    "limits": {
                        "max_pixels": 40000000,
                        "max_ocr_regions": 100,
                        "max_region_text_codepoints": 2000,
                    },
                    "known_uncontinuable_limits": [
                        "source_bytes",
                        "pixels",
                        "ocr_regions",
                        "region_text_codepoints",
                    ],
                },
            ],
        }
    )


@app.post("/v1/intake/profile-image", response_model=ImageProfileResponse)
def profile_image(req: ImageProfileRequest) -> ImageProfileResponse:
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        if len(req.document_b64) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
            raise ValueError("document_b64 exceeds image intake limit")
        raw = base64.b64decode(req.document_b64, validate=True)
        profile = profile_image_bytes(
            raw,
            filename=req.document_filename,
            ocr_requested=req.ocr_requested,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImageProfileResponse(kernel_version=__version__, profile=profile)


@app.post("/v1/intake/profile-table", response_model=TableProfileResponse)
def profile_table(req: TableProfileRequest) -> TableProfileResponse:
    try:
        if req.document_b64:
            if Path(req.document_filename).name != req.document_filename:
                raise ValueError("document_filename must be a plain basename")
            if not req.document_filename.casefold().endswith(".csv"):
                raise ValueError("document_filename must end with .csv")
            if len(req.document_b64) > ((MAX_TABLE_BYTES + 2) // 3) * 4:
                raise ValueError("document_b64 exceeds CSV intake limit")
            raw = base64.b64decode(req.document_b64, validate=True)
            profile = profile_csv_bytes(raw, filename=req.document_filename)
        elif req.document_path:
            profile = profile_csv(
                resolve_allowed_input_path(req.document_path, suffix=".csv")
            )
        else:
            raise ValueError("document_path or document_b64 is required")
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TableProfileResponse(kernel_version=__version__, profile=profile)


@app.post("/v1/intake/profile-workbook", response_model=WorkbookProfileResponse)
def profile_workbook(req: WorkbookProfileRequest) -> WorkbookProfileResponse:
    try:
        if req.document_b64:
            if Path(req.document_filename).name != req.document_filename:
                raise ValueError("document_filename must be a plain basename")
            if not req.document_filename.casefold().endswith(".xlsx"):
                raise ValueError("document_filename must end with .xlsx")
            if len(req.document_b64) > ((MAX_WORKBOOK_BYTES + 2) // 3) * 4:
                raise ValueError("document_b64 exceeds XLSX intake limit")
            raw = base64.b64decode(req.document_b64, validate=True)
            profile = profile_xlsx_bytes(raw, filename=req.document_filename)
        elif req.document_path:
            profile = profile_xlsx(
                resolve_allowed_input_path(req.document_path, suffix=".xlsx")
            )
        else:
            raise ValueError("document_path or document_b64 is required")
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WorkbookProfileResponse(kernel_version=__version__, profile=profile)


@app.post("/v1/intake/profile-document", response_model=DocumentProfileResponse)
def profile_document(req: DocumentProfileRequest) -> DocumentProfileResponse:
    try:
        if req.document_b64:
            if Path(req.document_filename).name != req.document_filename:
                raise ValueError("document_filename must be a plain basename")
            if not req.document_filename.casefold().endswith(".docx"):
                raise ValueError("document_filename must end with .docx")
            if len(req.document_b64) > ((MAX_DOCX_BYTES + 2) // 3) * 4:
                raise ValueError("document_b64 exceeds DOCX intake limit")
            raw = base64.b64decode(req.document_b64, validate=True)
            profile = profile_docx_bytes(raw, filename=req.document_filename)
        elif req.document_path:
            profile = profile_docx(
                resolve_allowed_input_path(req.document_path, suffix=".docx")
            )
        else:
            raise ValueError("document_path or document_b64 is required")
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentProfileResponse(kernel_version=__version__, profile=profile)


@app.post("/v1/intake/profile-presentation", response_model=PresentationProfileResponse)
def profile_presentation(
    req: PresentationProfileRequest,
) -> PresentationProfileResponse:
    try:
        if req.document_b64:
            if Path(req.document_filename).name != req.document_filename:
                raise ValueError("document_filename must be a plain basename")
            if not req.document_filename.casefold().endswith(".pptx"):
                raise ValueError("document_filename must end with .pptx")
            if len(req.document_b64) > ((MAX_PRESENTATION_BYTES + 2) // 3) * 4:
                raise ValueError("document_b64 exceeds PPTX intake limit")
            raw = base64.b64decode(req.document_b64, validate=True)
            profile = profile_pptx_bytes(raw, filename=req.document_filename)
        elif req.document_path:
            profile = profile_pptx(
                resolve_allowed_input_path(req.document_path, suffix=".pptx")
            )
        else:
            raise ValueError("document_path or document_b64 is required")
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PresentationProfileResponse(kernel_version=__version__, profile=profile)


@app.post("/v1/validate-structure", response_model=ValidateStructureResponse)
def validate_structure(req: ValidateStructureRequest) -> ValidateStructureResponse:
    try:
        document_path = resolve_allowed_input_path(req.document_path, suffix=".docx")
        reference_path = (
            resolve_allowed_input_path(req.reference_path, suffix=".docx")
            if req.reference_path
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    results = inv.validate_structure(
        str(document_path), str(reference_path) if reference_path else None
    )
    return ValidateStructureResponse(
        kernel_version=__version__,
        passed=inv.overall_passed(results),
        invariants=[
            {
                "id": r.id,
                "passed": r.passed,
                "status": r.status,
                "code": r.code,
                "params": r.params,
            }
            for r in results
        ],
    )


@app.post("/v1/review/start", response_model=ReviewStartResponse)
def review_start(req: ReviewStartRequest) -> ReviewStartResponse:
    rows = capture.build_review_rows(
        req.canonical_data, req.provenance, req.template_rendered, req.confidence
    )
    return ReviewStartResponse(
        kernel_version=__version__, doc_id=req.doc_id, fields=rows
    )


@app.post("/v1/review/commit", response_model=ReviewCommitResponse)
def review_commit(req: ReviewCommitRequest) -> ReviewCommitResponse:
    out = capture.commit_review(
        doc_id=req.doc_id,
        schema_ref=req.schema_ref,
        split=req.split,
        reviewed_by=req.reviewed_by,
        verdicts=[v.model_dump() for v in req.verdicts],
    )
    return ReviewCommitResponse(
        kernel_version=__version__,
        golden_path=out["golden_path"],
        correction_count=out["correction_count"],
    )


@app.post("/v1/score", response_model=ScoreResponse)
def score(req: ScoreRequest) -> ScoreResponse:
    gpath = golden_path(req.dataset, req.doc_id)
    if not gpath.exists():
        raise HTTPException(status_code=404, detail=f"golden not found: {gpath}")
    golden = scorer.load_golden(gpath)

    include_per_field = req.dataset != "heldout"  # heldout only returns the total score
    result = scorer.score(
        golden=golden,
        canonical_data=req.prediction.canonical_data,
        output_path=req.prediction.output_path,
        include_per_field=include_per_field,
    )
    return ScoreResponse(
        kernel_version=__version__,
        l0_gate=result["l0_gate"],
        scores=result["scores"],
        acceptance=result["acceptance"],
        per_field=result.get("per_field"),
    )


# ---- Semantic endpoints not yet implemented for P2+: explicitly return 501 ----
@app.post("/v1/extract")
def extract(_: dict) -> None:
    raise HTTPException(
        status_code=501,
        detail="P2 in progress; runtime LLM is executed by the solver side",
    )


@app.get("/v1/render/capabilities")
def render_capabilities() -> dict:
    return capabilities_document()


@app.post("/v1/content-blocks/validate")
def validate_content_blocks(payload: dict) -> JSONResponse:
    status, body = content_blocks_validation_result(payload)
    return JSONResponse(status_code=status, content=body)


@app.post("/v1/render/artifact")
def render_artifact(payload: dict) -> JSONResponse:
    status, body = execute_render_artifact(payload, sink=_render_sink())
    return JSONResponse(status_code=status, content=body)


@app.get("/v1/render/artifacts/{artifact_id}")
def get_render_artifact(artifact_id: str) -> Response:
    if not _ARTIFACT_ID.fullmatch(artifact_id):
        raise HTTPException(
            status_code=400, detail="artifact_id is not a safe identifier"
        )
    found = _render_sink().get(artifact_id)
    if found is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    payload, identity = found
    return Response(
        content=payload,
        media_type=str(identity["media_type"]),
        headers={
            "X-ProDocuX-SHA256": str(identity["sha256"]),
            "X-ProDocuX-Artifact-URI": str(identity["uri"]),
        },
    )


@app.post("/v1/render")
def render(payload: dict) -> JSONResponse:
    if (
        isinstance(payload, dict)
        and payload.get("schema_version") == "prodocux_render_request_v1"
    ):
        return render_artifact(payload)
    raise HTTPException(status_code=501, detail="P2 in progress")


@app.post("/v1/learn")
def learn(_: dict) -> None:
    raise HTTPException(status_code=501, detail="P3 in progress")
