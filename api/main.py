"""ProDocuX Kernel — FastAPI service (CONTRACT §4).

Start: python run_kernel.py  → http://localhost:8900/v1
The runtime does not call any LLM API.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response

from api.path_policy import resolve_allowed_input_path
from prodocux_kernel import API_VERSION, FROZEN_MODEL, __version__
from prodocux_kernel.config import golden_path
from prodocux_kernel.docops import invariants as inv
from prodocux_kernel.intake import (
    MAX_DOCX_BYTES,
    MAX_IMAGE_BYTES,
    MAX_PDF_BYTES,
    MAX_PRESENTATION_BYTES,
    MAX_TABLE_BYTES,
    MAX_WORKBOOK_BYTES,
    extract_pdf_bytes,
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
from prodocux_kernel.models import (
    DocumentProfileRequest,
    DocumentProfileResponse,
    ExtractBlocksRequest,
    ImageProfileRequest,
    ImageProfileResponse,
    IntakeCapabilitiesResponse,
    PdfExtractPagesRequest,
    PdfExtractPagesResponse,
    PresentationProfileRequest,
    PresentationProfileResponse,
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
)
from prodocux_kernel.rendering import (
    InMemoryArtifactSink,
    capabilities_document,
    content_blocks_validation_result,
    execute_extract_blocks,
    execute_render_artifact,
)
from prodocux_kernel.rendering.errors import HTTP_STATUS, RenderContractError
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
]

_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$")
_RENDER_SINK = InMemoryArtifactSink()


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
        if req.document_filename in {".", ".."} or not req.document_filename.casefold().endswith(".pdf"):
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
    status = "ocr_required" if any(page["ocr_required"] for page in pages) else "success"
    return PdfExtractPagesResponse(
        status=status,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        page_count=len(pages),
        pages=pages,
        truncation={"truncated": truncated, "total_characters": total_characters},
    )


@app.post("/v1/intake/extract-blocks")
def extract_blocks(req: ExtractBlocksRequest) -> JSONResponse:
    try:
        if Path(req.document_filename).name != req.document_filename:
            raise ValueError("document_filename must be a plain basename")
        if req.document_filename in {".", ".."}:
            raise ValueError("document_filename must be a plain basename")
        raw = base64.b64decode(req.document_b64, validate=True)
        body = execute_extract_blocks(req.document_filename, raw)
    except RenderContractError as exc:
        raise HTTPException(status_code=HTTP_STATUS.get(exc.code, 400), detail=exc.public_message) from exc
    except (ValueError, OSError) as exc:
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
    return IntakeCapabilitiesResponse.model_validate({
        "schema_version": "prodocux_intake_capabilities_v1",
        "kernel_version": __version__,
        "api_version": API_VERSION,
        "formats": [
            {"extensions": [".pdf"], "status": "available", "operation": "extract_pages", "max_bytes": MAX_PDF_BYTES, "max_pages": 50, "additional_operations": ["extract_blocks"]},
            {"extensions": [".csv"], "status": "available", "operation": "profile_table", "max_bytes": MAX_TABLE_BYTES, "additional_operations": ["extract_blocks"]},
            {"extensions": [".docx"], "status": "available", "operation": "profile_document", "max_bytes": MAX_DOCX_BYTES, "additional_operations": ["validate_structure", "extract_blocks"]},
            {"extensions": [".pptx"], "status": "available", "operation": "profile_presentation", "max_bytes": MAX_PRESENTATION_BYTES, "additional_operations": ["extract_blocks"]},
            {"extensions": [".xlsx"], "status": "available", "operation": "profile_workbook", "max_bytes": MAX_WORKBOOK_BYTES, "additional_operations": ["extract_blocks"]},
            {"extensions": [".jpg", ".jpeg", ".png"], "status": "available", "operation": "profile_image", "max_bytes": MAX_IMAGE_BYTES},
            {"extensions": [".xls"], "status": "planned", "operation": "profile_legacy_workbook"},
            {"extensions": [".mp4", ".mov", ".mxf"], "status": "external_pipeline_required", "operation": "probe_and_proxy"},
            {"extensions": [".r3d"], "status": "external_pipeline_required", "operation": "register_raw_and_proxy"},
        ],
    })


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
            profile = profile_csv(resolve_allowed_input_path(req.document_path, suffix=".csv"))
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
            profile = profile_xlsx(resolve_allowed_input_path(req.document_path, suffix=".xlsx"))
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
            profile = profile_docx(resolve_allowed_input_path(req.document_path, suffix=".docx"))
        else:
            raise ValueError("document_path or document_b64 is required")
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentProfileResponse(kernel_version=__version__, profile=profile)


@app.post("/v1/intake/profile-presentation", response_model=PresentationProfileResponse)
def profile_presentation(req: PresentationProfileRequest) -> PresentationProfileResponse:
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
            profile = profile_pptx(resolve_allowed_input_path(req.document_path, suffix=".pptx"))
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
            {"id": r.id, "passed": r.passed, "status": r.status,
             "code": r.code, "params": r.params}
            for r in results
        ],
    )


@app.post("/v1/review/start", response_model=ReviewStartResponse)
def review_start(req: ReviewStartRequest) -> ReviewStartResponse:
    rows = capture.build_review_rows(
        req.canonical_data, req.provenance, req.template_rendered, req.confidence
    )
    return ReviewStartResponse(kernel_version=__version__, doc_id=req.doc_id, fields=rows)


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
    raise HTTPException(status_code=501, detail="P2 in progress; runtime LLM is executed by the solver side")


@app.get("/v1/render/capabilities")
def render_capabilities() -> dict:
    return capabilities_document()


@app.post("/v1/content-blocks/validate")
def validate_content_blocks(payload: dict) -> JSONResponse:
    status, body = content_blocks_validation_result(payload)
    return JSONResponse(status_code=status, content=body)


@app.post("/v1/render/artifact")
def render_artifact(payload: dict) -> JSONResponse:
    status, body = execute_render_artifact(payload, sink=_RENDER_SINK)
    return JSONResponse(status_code=status, content=body)


@app.get("/v1/render/artifacts/{artifact_id}")
def get_render_artifact(artifact_id: str) -> Response:
    if not _ARTIFACT_ID.fullmatch(artifact_id):
        raise HTTPException(status_code=400, detail="artifact_id is not a safe identifier")
    found = _RENDER_SINK.get(artifact_id)
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
    if isinstance(payload, dict) and payload.get("schema_version") == "prodocux_render_request_v1":
        return render_artifact(payload)
    raise HTTPException(status_code=501, detail="P2 in progress")


@app.post("/v1/learn")
def learn(_: dict) -> None:
    raise HTTPException(status_code=501, detail="P3 in progress")
