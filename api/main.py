"""ProDocuX Kernel — FastAPI service (CONTRACT §4).

Start: python run_kernel.py  → http://localhost:8900/v1
The runtime does not call any LLM API.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from fastapi import FastAPI, HTTPException

from prodocux_kernel import API_VERSION, FROZEN_MODEL, __version__
from prodocux_kernel.config import golden_path
from prodocux_kernel.docops import invariants as inv
from prodocux_kernel.models import (
    Prediction,
    ReviewCommitRequest,
    ReviewCommitResponse,
    ReviewStartRequest,
    ReviewStartResponse,
    ScoreRequest,
    ScoreResponse,
    TableProfileRequest,
    TableProfileResponse,
    WorkbookProfileRequest,
    WorkbookProfileResponse,
    DocumentProfileRequest,
    DocumentProfileResponse,
    PresentationProfileRequest,
    PresentationProfileResponse,
    PdfExtractPagesRequest,
    PdfExtractPagesResponse,
    ValidateStructureRequest,
    ValidateStructureResponse,
    VersionResponse,
)
from prodocux_kernel.review import capture
from prodocux_kernel.scoring import scorer
from api.path_policy import resolve_allowed_input_path
from prodocux_kernel.intake import (
    MAX_TABLE_BYTES,
    MAX_WORKBOOK_BYTES,
    profile_csv,
    profile_csv_bytes,
    profile_xlsx,
    profile_xlsx_bytes,
    MAX_DOCX_BYTES,
    profile_docx,
    profile_docx_bytes,
    MAX_PRESENTATION_BYTES,
    profile_pptx,
    profile_pptx_bytes,
    MAX_PDF_BYTES,
    extract_pdf_bytes,
)

app = FastAPI(title="ProDocuX Kernel", version=__version__)

KNOWN_SCHEMAS = [
    "intake_request_v1",
    "intake_response_v1",
    "pif_tw_v1",
    "prodocux_table_profile_v1",
    "prodocux_workbook_profile_v1",
    "prodocux_docx_profile_v1",
    "prodocux_presentation_profile_v1",
]


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


@app.get("/v1/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(
        kernel_version=__version__,
        api_version=API_VERSION,
        frozen_model=FROZEN_MODEL,
        schemas=KNOWN_SCHEMAS,
    )


@app.get("/v1/intake/capabilities")
def intake_capabilities() -> dict:
    return {
        "kernel_version": __version__,
        "formats": [
            {"extensions": [".pdf"], "status": "available", "operation": "extract_pages"},
            {"extensions": [".csv"], "status": "available", "operation": "profile_table"},
            {"extensions": [".docx"], "status": "available", "operation": "profile_document", "additional_operations": ["validate_structure"]},
            {"extensions": [".pptx"], "status": "available", "operation": "profile_presentation"},
            {"extensions": [".xlsx"], "status": "available", "operation": "profile_workbook"},
            {"extensions": [".xls"], "status": "planned", "operation": "profile_legacy_workbook"},
            {"extensions": [".mp4", ".mov", ".mxf"], "status": "external_pipeline_required", "operation": "probe_and_proxy"},
            {"extensions": [".r3d"], "status": "external_pipeline_required", "operation": "register_raw_and_proxy"},
        ],
    }


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


@app.post("/v1/render")
def render(_: dict) -> None:
    raise HTTPException(status_code=501, detail="P2 in progress")


@app.post("/v1/learn")
def learn(_: dict) -> None:
    raise HTTPException(status_code=501, detail="P3 in progress")
