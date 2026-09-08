"""Published Kernel rc5 evidence; never update historical records in place."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "compatibility" / "pdx_prodocux_release_rc5.json"


def test_published_rc5_source_pin_and_assets() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert record["status"] == "published"
    assert record["prodocux"] == {
        "distribution": "prodocux",
        "version": "0.3.0rc5",
        "tag": "v0.3.0rc5",
        "release_commit": "e09684059519c16c8ec517e8f988e440ad3c9d09",
        "github_release": "https://github.com/prodocux/prodocux/releases/tag/v0.3.0rc5",
        "pypi_release": "https://pypi.org/project/prodocux/0.3.0rc5/",
        "workflow_run": "https://github.com/prodocux/prodocux/actions/runs/34213120573",
        "files": {
            "prodocux-0.3.0rc5-py3-none-any.whl": (
                "58ff5622188d337ba4aa0f049eeaaa502b08e0500bc9d4d9aa045943930377d6"
            ),
            "prodocux-0.3.0rc5.tar.gz": (
                "e262a3e41d174404fea3d46b9749e8fe19ae9fb477d0a73db9d82f93f5a51e32"
            ),
        },
    }


def test_rc5_keeps_downstream_promotion_separate() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    assert "separately pin" in record["downstream_boundary"]["studiotower"]
    assert "No downstream pin" in record["downstream_boundary"]["other_consumers"]
