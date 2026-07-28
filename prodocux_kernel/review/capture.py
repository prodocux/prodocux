"""C3: Review capture tools.

- build_review_rows: assembles predictions into a field-by-field side-by-side
  comparison package (including source snippets).
- commit_review: writes human verdicts as golden records and derives
  correction records.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .. import FROZEN_MODEL
from ..config import golden_path


def build_review_rows(
    canonical_data: Dict[str, Any],
    provenance: Dict[str, Any],
    template_rendered: Dict[str, Any],
    confidence: Dict[str, float],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for field, value in canonical_data.items():
        prov = provenance.get(field) or {}
        snippet = prov.get("snippet", "") if isinstance(prov, dict) else str(prov)
        rows.append({
            "field": field,
            "source_snippet": snippet,
            "extracted": value,
            "template_rendered": template_rendered.get(field),
            "confidence": confidence.get(field),
        })
    return rows


def _local_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def commit_review(
    doc_id: str,
    schema_ref: str,
    split: str,
    reviewed_by: str,
    verdicts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Produce and save a golden record, returning the path and correction count."""
    fields: List[Dict[str, Any]] = []
    corrections: List[Dict[str, Any]] = []

    for v in verdicts:
        field = v["field"]
        ev = v.get("extraction_verdict", "correct")
        tv = v.get("template_verdict", "correct")
        # When correct, gold = extracted value; otherwise use the human-provided gold_value
        gold_value = v.get("extracted") if ev == "correct" else v.get("gold_value")
        fields.append({
            "field": field,
            "source_snippet": v.get("source_snippet", ""),
            "extracted": v.get("extracted"),
            "template_rendered": v.get("template_rendered"),
            "extraction_verdict": ev,
            "template_verdict": tv,
            "gold_value": gold_value,
            "note": v.get("note", ""),
        })
        if ev != "correct" or tv != "correct":
            corrections.append({
                "field": field,
                "before": v.get("extracted"),
                "gold_value": gold_value,
                "source_snippet": v.get("source_snippet", ""),
            })

    record = {
        "doc_id": doc_id,
        "schema_ref": schema_ref,
        "model_frozen": FROZEN_MODEL,
        "reviewed_by": reviewed_by,
        "reviewed_at": _local_iso(),
        "split": split,
        "fields": fields,
        "corrections": corrections,
    }

    out = golden_path(split, doc_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    return {"golden_path": str(out), "correction_count": len(corrections)}
