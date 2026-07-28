"""C2 scorer tests."""
from prodocux_kernel.scoring import scorer


def _golden():
    return {
        "doc_id": "t1",
        "schema_ref": "pif_tw_v1",
        "mandatory_fields": ["product_name", "lead"],
        "fields": [
            {"field": "product_name", "gold_value": "ABC Cream"},
            {"field": "lead", "gold_value": 1.0},
            {"field": "note", "gold_value": "optional"},
        ],
    }


def test_perfect_match_accepted():
    res = scorer.score(_golden(), {"product_name": "ABC Cream", "lead": 1.0, "note": "optional"})
    assert res["scores"]["mandatory_field_accuracy"] == 1.0
    assert res["scores"]["hallucination_count"] == 0
    assert res["acceptance"]["passed"] is True


def test_normalization_and_numeric_tolerance():
    # full-width/whitespace normalization + numeric-string comparison
    res = scorer.score(_golden(), {"product_name": " ABC　Cream ", "lead": "1.0", "note": "optional"})
    assert res["scores"]["all_field_accuracy"] == 1.0


def test_wrong_mandatory_not_accepted():
    res = scorer.score(_golden(), {"product_name": "WRONG", "lead": 1.0, "note": "optional"})
    assert res["scores"]["mandatory_field_accuracy"] == 0.5
    assert res["acceptance"]["passed"] is False


def test_hallucination_blocks_acceptance():
    res = scorer.score(
        _golden(),
        {"product_name": "ABC Cream", "lead": 1.0, "note": "optional", "ghost": "made up"},
    )
    assert res["scores"]["hallucination_count"] == 1
    assert "ghost" in res["scores"]["hallucination_fields"]
    assert res["acceptance"]["passed"] is False


def test_transformation_compliance():
    res = scorer.score(
        _golden(),
        {"product_name": "ABC Cream", "lead": 1.0, "note": "optional", "source_label": "EU PIF"},
        transformations=[{"rename_source_to": "EU PIF"}],
    )
    # source_label is not in golden → also counts as a hallucination, but here we only verify transformation compliance
    assert res["scores"]["transformation_compliance"] == 1.0
