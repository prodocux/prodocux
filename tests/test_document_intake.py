import base64
import importlib.util
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from api.main import app
from fastapi.testclient import TestClient
from prodocux_kernel.intake.documents import read_document, resolve_document

_spec = importlib.util.spec_from_file_location("document_fixtures", Path(__file__).with_name("document_fixtures.py"))
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
cases = _fixtures.cases


@pytest.mark.parametrize("fmt", tuple(cases()))
def test_portable_source_replay(fmt):
    raw, expected, _ = cases()[fmt]
    page = read_document("sample." + fmt, raw, max_bytes=2_097_152, max_records=20000)
    item = next(row for row in page["text_items"] if expected in row["text"])
    start = item["text"].index(expected)
    args = {"source_sha256": page["source"]["source_sha256"],
            "parser_contract": page["parser_contract"], "locator": item["source_locator"],
            "quote_start": start, "quote_end": start+len(expected),
            "quote_sha256": sha256(expected.encode()).hexdigest()}
    assert resolve_document("sample."+fmt, raw, **args) == expected
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        resolve_document("sample."+fmt, raw+b"x", **args)


def test_streamed_lines_and_astral_quote():
    raw = ("first line\n" + "😀 café\n" + "tail\n").encode()
    page = read_document("sample.md", raw, max_records=1)
    assert page["next_cursor"] is not None
    second = read_document("sample.md", raw, cursor=page["next_cursor"], max_records=1)
    item = second["text_items"][0]
    assert resolve_document("sample.md", raw, source_sha256=sha256(raw).hexdigest(),
        parser_contract=second["parser_contract"], locator=item["source_locator"],
        quote_start=0, quote_end=1, quote_sha256=sha256("😀".encode()).hexdigest()) == "😀"


def test_http_read_and_resolve():
    with TestClient(app) as client:
        body = {"document_filename": "sample.json", "document_b64": base64.b64encode(b'{"a":"value"}').decode()}
        response = client.post("/v1/intake/documents/read", json=body)
        assert response.status_code == 200
        result = response.json()
        item = result["text_items"][0]
        resolved = client.post("/v1/intake/documents/resolve", json={
            **body, "source_sha256": result["source"]["source_sha256"],
            "parser_contract": result["parser_contract"], "locator": item["source_locator"],
            "quote_start": 0, "quote_end": 5, "quote_sha256": sha256(b"value").hexdigest()})
        assert resolved.json() == {"quote": "value"}
        assert client.post("/v1/intake/documents/read", json={**body, "unexpected": 1}).status_code == 422


def test_read_budget_and_huge_number():
    with pytest.raises(ValueError, match="DOCUMENT_OUTPUT_LIMIT"):
        read_document("sample.json", b'{"a":"long value"}', max_bytes=1)
    with pytest.raises(ValueError, match="JSON_NUMBER_DIGIT_LIMIT"):
        read_document("sample.json", b"9"*257)


def test_csv_v2_preserves_quoted_newlines():
    from prodocux_kernel.intake import extract_csv_continuable_projection
    raw = b'key,value\n1,"first\nsecond"\n'
    page = extract_csv_continuable_projection(raw, contract_version="2")
    assert page["rows"][0][1] == "first\nsecond"
    assert page["parser_contract"]["version"] == "2"


def test_xlsx_v2_exposes_visibility():
    from openpyxl import Workbook
    from prodocux_kernel.intake import extract_xlsx_continuable_projection
    book = Workbook()
    book.active["A1"] = "visible"
    book.create_sheet("Private").sheet_state = "veryHidden"
    out = BytesIO()
    book.save(out)
    page = extract_xlsx_continuable_projection(out.getvalue(), contract_version="2")
    assert page["range"]["sheet_visibility"] == "visible"
    hidden = extract_xlsx_continuable_projection(out.getvalue(), cursor=page["next_cursor"], contract_version="2")
    assert hidden["range"]["sheet_visibility"] == "veryHidden"


def test_http_office_v2_selection_is_explicit():
    with TestClient(app) as client:
        body = {"document_filename": "sample.csv",
                "document_b64": base64.b64encode(b'a,b'+bytes([13,10])+b'1,"first'+bytes([13,10])+b'second"'+bytes([13,10])).decode()}
        v1 = client.post("/v1/intake/profile-table/continue", json=body)
        assert v1.status_code == 200 and v1.json()["parser_contract"]["version"] == "1"
        v2 = client.post("/v1/intake/profile-table/continue", json={**body, "contract_version": "2"})
        assert v2.status_code == 200 and v2.json()["rows"][0][1] == "first"+chr(13)+chr(10)+"second"
        assert client.post("/v1/intake/profile-table/continue",
                           json={**body, "contract_version": "3"}).status_code == 422
