"""#14 Multi-document contract clause diff + i18n template tests."""
from docx import Document

from prodocux_kernel.docdiff import clauses as cc
from skills.clause_diff import clause_diff as cd
from skills.common.i18n import Catalog, resolve_lang


def _contract(tmp_path, paragraphs, name):
    d = Document()
    for p in paragraphs:
        d.add_paragraph(p)
    out = tmp_path / f"{name}.docx"
    d.save(str(out))
    return str(out)


# ---- i18n template ----
def test_resolve_lang_default_en(monkeypatch):
    for v in ("PRODOCUX_LANG", "LC_ALL", "LANG"):
        monkeypatch.delenv(v, raising=False)
    assert resolve_lang(None) == "en"
    assert resolve_lang("zh-TW") == "zh-TW"
    assert resolve_lang("zh_TW") == "zh-TW"
    assert resolve_lang("English") == "en"


def test_resolve_lang_env(monkeypatch):
    monkeypatch.setenv("PRODOCUX_LANG", "zh-TW")
    assert resolve_lang(None) == "zh-TW"


def test_catalog_format_and_fallback():
    cat = Catalog({"k": {"en": "Hi {name}", "zh-TW": "嗨 {name}"}})
    assert cat.t("k", "en", name="A") == "Hi A"
    assert cat.t("k", "zh-TW", name="A") == "嗨 A"
    assert cat.t("missing", "en") == "missing"  # missing key falls back to the key itself


# ---- engine ----
def test_clause_extract_and_compare(tmp_path):
    a = _contract(tmp_path, [
        "第1條 名稱。", "第2條 範圍。", "第3條 付款條件：30日。",
    ], "a")
    b = _contract(tmp_path, [
        "第1條 名稱。", "第2條 範圍。", "第3條 付款條件：45日。",
        "第4條 電子簽章。",
    ], "b")
    res = cc.compare_clauses([a, b])
    by_key = {c["clause"]: c["status"] for c in res["clauses"]}
    assert by_key["第1條"] == "same"
    assert by_key["第3條"] == "differs"
    assert by_key["第4條"] == "missing_in_some"
    assert res["has_diff"] is True


def test_clause_all_same(tmp_path):
    a = _contract(tmp_path, ["第1條 甲。", "第2條 乙。"], "x")
    b = _contract(tmp_path, ["第1條 甲。", "第2條 乙。"], "y")
    res = cc.compare_clauses([a, b])
    assert res["has_diff"] is False


# ---- CLI ----
def test_cli_lang_and_exit(tmp_path, capsys):
    a = _contract(tmp_path, ["第1條 甲。", "第2條 付款 30 日。"], "v1")
    b = _contract(tmp_path, ["第1條 甲。", "第2條 付款 45 日。"], "v2")

    assert cd.main([a, b]) == 0           # does not fail on differences by default
    out_en = capsys.readouterr().out
    assert "DIFFERS" in out_en            # defaults to English

    assert cd.main([a, b, "--lang", "zh-TW"]) == 0
    out_zh = capsys.readouterr().out
    assert "不同" in out_zh

    assert cd.main([a, b, "--fail-on-diff"]) == 1
