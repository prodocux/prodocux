"""Apply evidence images into a rendered .docx per evidence spec."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from docx import Document

from ..docops import pagination, tables

PathLike = Union[str, Path]


def load_evidence_spec(path: PathLike) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "prodocux_evidence_v1":
        raise ValueError(f"unsupported evidence schema: {data.get('schema')}")
    return data


def apply_evidence_injections(
    docx_path: PathLike,
    spec: Dict[str, Any],
    image_paths: Dict[str, PathLike],
    *,
    heading_styles: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Inject extracted images into an assembled docx. Returns injection report."""
    path = Path(docx_path)
    doc = Document(str(path))
    stop_styles = heading_styles or set()
    applied = 0
    skipped = 0
    details: List[Dict[str, Any]] = []

    for inj in spec.get("inject", []):
        inj_type = inj.get("type")
        if inj_type == "table_row":
            image_id = inj["image_id"]
            img = image_paths.get(image_id)
            if not img or not Path(img).is_file():
                skipped += 1
                details.append({"type": inj_type, "image_id": image_id, "status": "skipped", "reason": "missing image"})
                continue
            ok = tables.fill_image_in_table_row_by_label(
                doc,
                inj["row_label"],
                img,
                cell_index=int(inj.get("cell_index", 1)),
                caption=inj.get("caption"),
                width_inches=float(inj.get("width_inches", 3.6)),
            )
            if ok:
                applied += 1
                details.append({"type": inj_type, "image_id": image_id, "status": "applied"})
            else:
                skipped += 1
                details.append({"type": inj_type, "image_id": image_id, "status": "skipped", "reason": "row not found"})
        elif inj_type == "appendix":
            rows = []
            for row in inj.get("rows", []):
                image_id = row["image_id"]
                img = image_paths.get(image_id)
                if img and Path(img).is_file():
                    rows.append((row.get("caption", image_id), img))
            if not rows:
                skipped += 1
                details.append({"type": inj_type, "heading": inj.get("heading"), "status": "skipped", "reason": "no images"})
                continue
            ok = tables.fill_appendix_images(
                doc,
                inj["heading"],
                rows,
                heading_styles=stop_styles,
                width_inches=float(inj.get("width_inches", 5.7)),
            )
            if ok:
                applied += 1
                details.append({"type": inj_type, "heading": inj.get("heading"), "status": "applied", "rows": len(rows)})
            else:
                skipped += 1
                details.append({"type": inj_type, "heading": inj.get("heading"), "status": "skipped", "reason": "table not found"})
        else:
            skipped += 1
            details.append({"type": inj_type, "status": "skipped", "reason": "unknown type"})

    pagination.remove_blank_page_breaks_before_headings(doc, stop_styles)
    doc.save(str(path))
    return {"applied": applied, "skipped": skipped, "details": details}
