"""C3 review-capture tests."""
import json

from prodocux_kernel import config
from prodocux_kernel.review import capture


def test_build_review_rows():
    rows = capture.build_review_rows(
        canonical_data={"product_name": "ABC"},
        provenance={"product_name": {"page": 1, "snippet": "Product: ABC"}},
        template_rendered={"product_name": "ABC 乳霜"},
        confidence={"product_name": 0.97},
    )
    assert rows[0]["source_snippet"] == "Product: ABC"
    assert rows[0]["confidence"] == 0.97


def test_commit_creates_golden_and_corrections(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEV_DATASET_DIR", tmp_path)

    out = capture.commit_review(
        doc_id="doc1",
        schema_ref="pif_tw_v1",
        split="dev",
        reviewed_by="human",
        verdicts=[
            {"field": "product_name", "extraction_verdict": "correct",
             "template_verdict": "correct", "extracted": "ABC Cream",
             "source_snippet": "Product: ABC Cream"},
            {"field": "lead", "extraction_verdict": "wrong",
             "template_verdict": "correct", "extracted": "9", "gold_value": "1",
             "source_snippet": "Lead: 1 ppm"},
        ],
    )
    assert out["correction_count"] == 1
    saved = json.loads((tmp_path / "doc1.json").read_text(encoding="utf-8"))
    assert saved["doc_id"] == "doc1"
    # correct fields: gold = extracted value; wrong fields: gold = human-entered value
    fields = {f["field"]: f for f in saved["fields"]}
    assert fields["product_name"]["gold_value"] == "ABC Cream"
    assert fields["lead"]["gold_value"] == "1"
    assert len(saved["corrections"]) == 1
