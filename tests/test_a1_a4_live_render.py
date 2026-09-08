from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from prodocux_kernel.rendering import (
    extract_content_blocks,
    validate_content_blocks,
    write_content_blocks,
)
from prodocux_kernel.rendering.media import assert_magic_matches_format

ROOT = Path(__file__).resolve().parents[1]
G1A = ROOT / "examples" / "contracts" / "g1a"
MARKER = "SYNTH-ROUNDTRIP-ALPHA-001"


def _load(name: str) -> dict:
    return json.loads((G1A / name).read_text(encoding="utf-8"))


def _blocks() -> dict:
    return {
        "schema_version": "prodocux_content_blocks_v1",
        "document": {"title": MARKER, "locale": "en"},
        "blocks": [
            {"id": "h1", "type": "heading", "level": 1, "text": MARKER},
            {
                "id": "p1",
                "type": "paragraphs",
                "paragraphs": ["Synthetic paragraph with no production data."],
            },
            {
                "id": "t1",
                "type": "table",
                "table": {
                    "header_rows": 1,
                    "rows": [["Name", "Amount"], [MARKER, "1"]],
                },
            },
            {
                "id": "s1",
                "type": "sheet",
                "name": "Records",
                "table": {
                    "header_rows": 1,
                    "rows": [["id", "label"], ["1", MARKER]],
                },
            },
            {
                "id": "d1",
                "type": "slide",
                "title": MARKER,
                "paragraphs": ["Synthetic slide body"],
            },
        ],
    }


def test_minimal_fixture_round_trips_all_five_formats() -> None:
    content = _blocks()
    validate_content_blocks(content)
    suffixes = {
        "csv": "notes.csv",
        "xlsx": "notes.xlsx",
        "docx": "notes.docx",
        "pptx": "notes.pptx",
        "pdf": "notes.pdf",
    }
    for fmt, filename in suffixes.items():
        payload = write_content_blocks(content, fmt)
        assert_magic_matches_format(payload, fmt)
        extracted = extract_content_blocks(filename, payload)
        assert extracted["format"] == fmt
        blob = json.dumps(extracted["content"], ensure_ascii=True)
        assert MARKER in blob or MARKER in json.dumps(extracted["text_items"])
        validate_content_blocks(extracted["content"])


def test_pdf_wraps_long_table_rows_and_paginates_without_dropping_text() -> None:
    import fitz

    last_marker = "FINAL-ROW-079"
    long_value = (
        "A deliberately long production location description with multilingual "
        "content 中文場景 and operational notes that must remain inside page boundaries."
    )
    content = {
        "schema_version": "prodocux_content_blocks_v1",
        "document": {"title": "Boundary test", "locale": "en"},
        "blocks": [
            {
                "id": "rows",
                "type": "table",
                "table": {
                    "header_rows": 1,
                    "rows": [["ID", "Description"]]
                    + [[f"ROW-{index:03d}", f"{long_value} FINAL-ROW-{index:03d}"] for index in range(80)],
                },
            }
        ],
    }

    payload = write_content_blocks(content, "pdf")
    pdf = fitz.open(stream=payload, filetype="pdf")
    extracted = "\n".join(page.get_text() for page in pdf)
    assert len(pdf) > 1
    assert all(f"ROW-{index:03d}" in extracted for index in range(80))
    assert all(f"FINAL-ROW-{index:03d}" in extracted for index in range(80))
    assert last_marker in extracted
    assert all(
        word[2] <= 547.01 and word[3] <= 800.01
        for page in pdf
        for word in page.get_text("words")
    )


def test_pdf_explicit_lines_advance_cursor_and_paginate_without_overlap() -> None:
    import fitz

    explicit_lines = [f"EXPLICIT-LINE-{index:03d}" for index in range(60)]
    next_marker = "NEXT-PARAGRAPH"
    content = {
        "schema_version": "prodocux_content_blocks_v1",
        "document": {"title": "Explicit line test", "locale": "en"},
        "blocks": [
            {
                "id": "paragraphs",
                "type": "paragraphs",
                "paragraphs": ["\n".join(explicit_lines), next_marker],
            }
        ],
    }

    payload = write_content_blocks(content, "pdf")
    pdf = fitz.open(stream=payload, filetype="pdf")
    words = [word for page in pdf for word in page.get_text("words")]
    extracted = "\n".join(page.get_text() for page in pdf)
    next_word = next(word for word in words if word[4] == next_marker)

    assert len(pdf) > 1
    assert all(marker in extracted for marker in explicit_lines)
    assert next_marker in extracted
    assert next_word[1] > 48.0
    assert all(word[2] <= 547.01 and word[3] <= 800.01 for word in words)


def test_http_extract_blocks_and_inline_render() -> None:
    content = _blocks()
    csv_bytes = write_content_blocks(content, "csv")
    client = TestClient(app)
    extracted = client.post(
        "/v1/intake/extract-blocks",
        json={
            "document_filename": "records.csv",
            "document_b64": base64.b64encode(csv_bytes).decode("ascii"),
        },
    )
    assert extracted.status_code == 200
    body = extracted.json()
    assert body["format"] == "csv"
    assert body["content"]["schema_version"] == "prodocux_content_blocks_v1"
    assert any(MARKER in item["text"] for item in body["text_items"])

    rendered = client.post(
        "/v1/render/artifact",
        json={
            "schema_version": "prodocux_render_request_v1",
            "request_id": "roundtrip-csv",
            "target_format": "csv",
            "content": body["content"],
            "output": {"output_name": "out.csv", "delivery_mode": "inline"},
        },
    )
    assert rendered.status_code == 200
    result = rendered.json()
    assert result["status"] == "completed"
    decoded = base64.b64decode(result["content_b64"])
    assert MARKER.encode("utf-8") in decoded


def test_http_extract_rejects_path_and_unknown_suffix() -> None:
    client = TestClient(app)
    payload = {
        "document_filename": "../secret.csv",
        "document_b64": base64.b64encode(b"id,label\n1,a\n").decode("ascii"),
    }
    assert client.post("/v1/intake/extract-blocks", json=payload).status_code in {400, 422}
    payload["document_filename"] = "notes.txt"
    assert client.post("/v1/intake/extract-blocks", json=payload).status_code == 400


def test_g1a_inline_csv_fixture_renders_bytes() -> None:
    client = TestClient(app)
    response = client.post("/v1/render", json=_load("render_request.inline.csv.json"))
    assert response.status_code == 200
    body = response.json()
    decoded = base64.b64decode(body["content_b64"])
    assert b"alpha" in decoded
    assert_magic_matches_format(decoded, "csv")
