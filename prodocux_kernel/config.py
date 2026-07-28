"""Kernel path configuration (dataset locations).

Override with environment variables. Never commit held-out answers.
"""
from __future__ import annotations

import os
from pathlib import Path

# repo root (this file lives in prodocux_kernel/)
REPO_ROOT = Path(__file__).resolve().parent.parent

# dev golden records (local; typically gitignored JSON under datasets/dev)
DEV_DATASET_DIR = Path(
    os.environ.get("PRODOCUX_DEV_DIR", REPO_ROOT / "datasets" / "dev")
)

# held-out answers: require PRODOCUX_HELDOUT_DIR in production.
# Default is an in-repo placeholder directory that must stay empty / gitignored.
HELDOUT_ANSWERS_DIR = Path(
    os.environ.get("PRODOCUX_HELDOUT_DIR", REPO_ROOT / "datasets" / "heldout")
)


def dataset_dir(split: str) -> Path:
    return HELDOUT_ANSWERS_DIR if split == "heldout" else DEV_DATASET_DIR


def golden_path(split: str, doc_id: str) -> Path:
    return dataset_dir(split) / f"{doc_id}.json"
