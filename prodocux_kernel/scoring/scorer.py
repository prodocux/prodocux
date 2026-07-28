"""C2: Evaluation scorer (CONTRACT §5).

Scoring tiers:
- L0: structural gate (calls docops.invariants)
- L1: field accuracy (mandatory / all fields)
- Hallucination: prediction has a value but the golden has no such field
- L2: transformation/intent compliance (best-effort; needs a profile for P1
  to be complete)
- L3: required/optional elements (P1 placeholder)

Pass criteria (heldout): all L0 pass AND mandatory_field_accuracy>=0.95 AND
hallucination_count==0
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..docops import invariants as inv

ACCEPT_MANDATORY_ACCURACY = 0.95


# --------------------------------------------------------------------------
# Normalization and comparison
# --------------------------------------------------------------------------
def _normalize(value: Any) -> str:
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _values_equal(pred: Any, gold: Any, tol: float = 1e-6) -> bool:
    # numeric comparison with tolerance
    pn, gn = _try_float(pred), _try_float(gold)
    if pn is not None and gn is not None:
        return abs(pn - gn) <= tol
    # element-wise comparison for tables / lists
    if isinstance(gold, list) and isinstance(pred, list):
        if len(pred) != len(gold):
            return False
        return all(_values_equal(p, g) for p, g in zip(pred, gold))
    if isinstance(gold, dict) and isinstance(pred, dict):
        if set(pred.keys()) != set(gold.keys()):
            return False
        return all(_values_equal(pred[k], gold[k]) for k in gold)
    return _normalize(pred) == _normalize(gold)


def _try_float(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.fullmatch(r"\s*-?\d+(\.\d+)?\s*", v)
        if m:
            return float(v)
    return None


# --------------------------------------------------------------------------
# Loading golden records
# --------------------------------------------------------------------------
def load_golden(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _golden_field_map(golden: Dict[str, Any]) -> Dict[str, Any]:
    return {fd["field"]: fd.get("gold_value") for fd in golden.get("fields", [])}


def _mandatory_fields(golden: Dict[str, Any]) -> List[str]:
    # prefer the top-level golden mandatory_fields; otherwise fall back to all fields
    if golden.get("mandatory_fields"):
        return list(golden["mandatory_fields"])
    return [fd["field"] for fd in golden.get("fields", [])]


# --------------------------------------------------------------------------
# Main scoring
# --------------------------------------------------------------------------
def score(
    golden: Dict[str, Any],
    canonical_data: Dict[str, Any],
    output_path: Optional[str] = None,
    transformations: Optional[List[Dict[str, Any]]] = None,
    include_per_field: bool = True,
) -> Dict[str, Any]:
    gold_map = _golden_field_map(golden)
    mandatory = set(_mandatory_fields(golden))

    per_field: List[Dict[str, Any]] = []
    correct_all = 0
    correct_mand = 0
    total_mand = 0
    for field, gold_val in gold_map.items():
        pred_val = canonical_data.get(field)
        ok = _values_equal(pred_val, gold_val)
        correct_all += int(ok)
        if field in mandatory:
            total_mand += 1
            correct_mand += int(ok)
        per_field.append({
            "field": field,
            "expected": gold_val,
            "predicted": pred_val,
            "correct": ok,
            "mandatory": field in mandatory,
        })

    total_all = len(gold_map)
    all_acc = correct_all / total_all if total_all else 1.0
    mand_acc = correct_mand / total_mand if total_mand else 1.0

    # hallucination: prediction has a value but the golden has no such field
    hallucinations = [
        k for k, v in canonical_data.items()
        if k not in gold_map and _normalize(v) != ""
    ]

    # L0 gate
    l0_gate = "pass"
    l0_report: List[Dict[str, Any]] = []
    if output_path:
        invs = inv.validate_structure(output_path)
        l0_report = [vars(i) for i in invs]
        l0_gate = "pass" if inv.overall_passed(invs) else "fail"

    # L2 transformation compliance (best-effort)
    transform_compliance = _check_transformations(canonical_data, transformations)

    scores = {
        "mandatory_field_accuracy": round(mand_acc, 4),
        "all_field_accuracy": round(all_acc, 4),
        "hallucination_count": len(hallucinations),
        "hallucination_fields": hallucinations,
        "transformation_compliance": transform_compliance,
    }

    accepted = (
        l0_gate == "pass"
        and mand_acc >= ACCEPT_MANDATORY_ACCURACY
        and len(hallucinations) == 0
    )
    acceptance = {
        "passed": accepted,
        "criteria": "all L0 pass AND mandatory_field_accuracy>=0.95 AND hallucination_count==0",
    }

    result: Dict[str, Any] = {
        "l0_gate": l0_gate,
        "l0_report": l0_report,
        "scores": scores,
        "acceptance": acceptance,
    }
    if include_per_field:
        result["per_field"] = per_field
    return result


def _check_transformations(
    canonical_data: Dict[str, Any],
    transformations: Optional[List[Dict[str, Any]]],
) -> Optional[float]:
    if not transformations:
        return None
    blob = _normalize(json.dumps(canonical_data, ensure_ascii=False))
    passed = 0
    total = 0
    for rule in transformations:
        if "rename_source_to" in rule:
            total += 1
            target = _normalize(rule["rename_source_to"])
            if target and target.lower() in blob.lower():
                passed += 1
    return round(passed / total, 4) if total else None
