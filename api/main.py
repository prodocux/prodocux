"""ProDocuX Kernel — FastAPI service (CONTRACT §4).

Start: python run_kernel.py  → http://localhost:8900/v1
The runtime does not call any LLM API.
"""
from __future__ import annotations

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
    ValidateStructureRequest,
    ValidateStructureResponse,
    VersionResponse,
)
from prodocux_kernel.review import capture
from prodocux_kernel.scoring import scorer

app = FastAPI(title="ProDocuX Kernel", version=__version__)

KNOWN_SCHEMAS = ["pif_tw_v1"]


@app.get("/v1/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(
        kernel_version=__version__,
        api_version=API_VERSION,
        frozen_model=FROZEN_MODEL,
        schemas=KNOWN_SCHEMAS,
    )


@app.post("/v1/validate-structure", response_model=ValidateStructureResponse)
def validate_structure(req: ValidateStructureRequest) -> ValidateStructureResponse:
    results = inv.validate_structure(req.document_path, req.reference_path)
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
