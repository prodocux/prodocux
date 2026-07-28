"""Deterministic INCI / formula table extraction."""
import json
import os
from pathlib import Path

import pytest

from prodocux_kernel.intake.formula import (
    extract_formula_draft_from_pages,
    parse_formula_rows,
)


def _optional_formula_pages() -> Path | None:
    """Private fixture only via env (never hardcode customer product filenames)."""
    env = os.environ.get("PRODOCUX_FORMULA_PAGES")
    if not env:
        return None
    p = Path(env)
    return p if p.is_file() else None


_OPTIONAL_PAGES = _optional_formula_pages()


@pytest.mark.skipif(
    _OPTIONAL_PAGES is None,
    reason="set PRODOCUX_FORMULA_PAGES to a private *.pages.json for this optional check",
)
def test_parse_private_fixture_inci_rows():
    pages = json.loads(_OPTIONAL_PAGES.read_text(encoding="utf-8"))["pages"]
    draft = extract_formula_draft_from_pages(pages)
    rows = draft["03_formula"]["table"]["rows"]
    assert len(rows) >= 15
    names = [r[0] for r in rows]
    assert "Alcohol denat." in names
    assert "Parfum" in names
    assert "Aqua" in names
    assert "7732-18-5" in [r[2] for r in rows]


def test_inci_block_ignores_composition_table():
    text = (
        "Composizione quali-quantitativa\n"
        "Materie prime Fornitori % Ingredienti CAS#\n"
        "-- 80,0000 Alcohol denat. 64-17-5\n"
        "Presentazione degli ingredienti (INCI)\n"
        "Ingredienti % CAS# EINECS# Funzioni\n"
        "1. Alcohol denat. 72,00000 64-17-5 200-578-6 Solvent\n"
        "2. Parfum 25,00000\n"
        "3. Aqua 3,00000 7732-18-5 231-791-2 Solvent\n"
        "Totale 100,0000\n"
    )
    rows = parse_formula_rows(text)
    assert len(rows) == 3
    assert rows[0]["ingredient"] == "Alcohol denat."
