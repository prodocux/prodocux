"""Cross-field validation for bounded continuation responses."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


class ProjectionValidationError(ValueError):
    """A producer response violates continuation invariants."""


def validate_continuable_projection(value: Mapping[str, Any]) -> None:
    schema = value.get("schema_version")
    handlers = {
        "prodocux_pdf_continuable_projection_v1": _pdf,
        "prodocux_csv_continuable_projection_v1": _csv,
        "prodocux_xlsx_continuable_projection_v1": _xlsx,
        "prodocux_pptx_continuable_projection_v1": _pptx,
        "prodocux_image_tile_projection_v1": _image,
    }
    if schema not in handlers:
        raise ProjectionValidationError("unsupported continuation schema")
    source = value.get("source_sha256")
    contract = value.get("parser_contract")
    range_value = value.get("range")
    coverage = value.get("coverage")
    counts = value.get("counts")
    if not all(
        isinstance(item, Mapping) for item in (contract, range_value, coverage, counts)
    ):
        raise ProjectionValidationError("projection envelope objects are required")
    if not isinstance(source, str) or len(source) != 64:
        raise ProjectionValidationError("source digest is invalid")
    start, end = range_value.get("start"), range_value.get("end")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or end < start
        or (end == start and schema != "prodocux_csv_continuable_projection_v1")
    ):
        raise ProjectionValidationError("range must be a valid half-open interval")
    requested_names = {
        "prodocux_pdf_continuable_projection_v1": "requested_max_pages",
        "prodocux_csv_continuable_projection_v1": "requested_max_rows",
        "prodocux_xlsx_continuable_projection_v1": "requested_max_rows",
        "prodocux_pptx_continuable_projection_v1": "requested_max_slides",
        "prodocux_image_tile_projection_v1": "requested_max_tiles",
    }
    requested = range_value.get(requested_names[schema])
    if not isinstance(requested, int) or isinstance(requested, bool) or end - start > requested:
        raise ProjectionValidationError("returned range exceeds requested maximum")
    next_value = value.get("next_cursor")
    continuation = coverage.get("continuation_available")
    if continuation != (next_value is not None):
        raise ProjectionValidationError(
            "coverage continuation flag disagrees with descriptor"
        )
    disposition = coverage.get("disposition")
    omissions = coverage.get("omitted_content_classes")
    if not isinstance(omissions, list):
        raise ProjectionValidationError("omitted content classes must be an array")
    if omissions and disposition != "partial_unknown":
        raise ProjectionValidationError(
            "unquantified omissions require partial_unknown"
        )
    if not omissions and next_value is None and disposition != "complete":
        raise ProjectionValidationError("final omission-free range must be complete")
    if not omissions and next_value is not None and disposition != "partial_known":
        raise ProjectionValidationError(
            "continuable omission-free range must be partial_known"
        )
    if next_value is not None:
        if not isinstance(next_value, Mapping):
            raise ProjectionValidationError("next descriptor must be an object")
        expected = {
            "source_sha256": source,
            "parser_contract_name": contract.get("name"),
            "parser_contract_version": contract.get("version"),
        }
        if any(
            next_value.get(name) != expected_value
            for name, expected_value in expected.items()
        ):
            raise ProjectionValidationError(
                "next descriptor authority binding mismatch"
            )
    handlers[schema](value)


def _pdf(value: Mapping[str, Any]) -> None:
    pages = value.get("pages")
    range_value, counts = value["range"], value["counts"]
    if (
        not isinstance(pages, list)
        or len(pages) != counts.get("returned_pages")
        or len(pages) != range_value["end"] - range_value["start"]
    ):
        raise ProjectionValidationError("PDF returned page count disagrees with range")
    if [page.get("page_number") for page in pages] != list(
        range(range_value["start"], range_value["end"])
    ):
        raise ProjectionValidationError("PDF page identities are not contiguous")
    if (
        value.get("next_cursor") is not None
        and value["next_cursor"].get("next_page") != range_value["end"]
    ):
        raise ProjectionValidationError("PDF next page is not range end")
    total = value["coverage"].get("known_total_pages")
    if (
        not isinstance(total, int)
        or range_value["end"] - 1 > total
        or (value.get("next_cursor") is None and range_value["end"] != total + 1)
    ):
        raise ProjectionValidationError("PDF range disagrees with known total")
    ocr = value.get("ocr")
    required_pages = [page.get("page_number") for page in pages if page.get("ocr_required")]
    if not isinstance(ocr, Mapping) or ocr.get("pages_requiring_ocr") != required_pages:
        raise ProjectionValidationError("PDF OCR disclosure disagrees with pages")
    if required_pages and (
        value["coverage"].get("disposition") != "partial_unknown"
        or "ocr_required_not_performed" not in value["coverage"].get("omitted_content_classes", [])
        or ocr.get("disposition") not in {"not_performed", "unavailable"}
    ):
        raise ProjectionValidationError("unperformed required OCR must be disclosed")


def _csv(value: Mapping[str, Any]) -> None:
    rows, columns = value.get("rows"), value.get("columns")
    range_value, counts = value["range"], value["counts"]
    if (
        not isinstance(rows, list)
        or not isinstance(columns, list)
        or len(rows) != counts.get("returned_rows")
        or len(rows) != range_value["end"] - range_value["start"]
    ):
        raise ProjectionValidationError("CSV returned row count disagrees with range")
    if len(columns) != counts.get("returned_columns"):
        raise ProjectionValidationError(
            "CSV returned column count disagrees with columns"
        )
    if (
        value.get("next_cursor") is not None
        and value["next_cursor"].get("next_row") != range_value["end"]
    ):
        raise ProjectionValidationError("CSV next row is not range end")
    total = value["coverage"].get("known_total_rows")
    if (
        not isinstance(total, int)
        or range_value["end"] > total
        or (value.get("next_cursor") is None and range_value["end"] != total)
    ):
        raise ProjectionValidationError("CSV range disagrees with known total")
    if range_value["start"] == range_value["end"] and (
        total != 0 or rows or value.get("next_cursor") is not None
    ):
        raise ProjectionValidationError("empty CSV range is only valid for zero data rows")


def _xlsx(value: Mapping[str, Any]) -> None:
    rows = value.get("rows")
    range_value, counts = value["range"], value["counts"]
    if (
        not isinstance(rows, list)
        or len(rows) != counts.get("returned_rows")
        or len(rows) != range_value["end"] - range_value["start"]
    ):
        raise ProjectionValidationError("XLSX returned row count disagrees with range")
    next_value = value.get("next_cursor")
    if next_value is not None and next_value.get("next_sheet_index") == range_value.get(
        "sheet_index"
    ):
        if (
            next_value.get("next_sheet_name") != range_value.get("sheet_name")
            or next_value.get("next_row") != range_value["end"]
        ):
            raise ProjectionValidationError(
                "XLSX same-sheet continuation is not contiguous"
            )
    elif next_value is not None and (
        next_value.get("next_sheet_index") != range_value.get("sheet_index") + 1
        or next_value.get("next_row") != 1
    ):
        raise ProjectionValidationError("XLSX next-sheet continuation is invalid")
    total_rows = value["coverage"].get("known_sheet_rows")
    if not isinstance(total_rows, int) or range_value["end"] - 1 > total_rows:
        raise ProjectionValidationError("XLSX range disagrees with sheet row total")
    total_sheets = value["coverage"].get("known_total_sheets")
    if not isinstance(total_sheets, int) or range_value.get("sheet_index") >= total_sheets:
        raise ProjectionValidationError("XLSX sheet index disagrees with sheet total")
    if next_value is None and (
        range_value.get("sheet_index") != total_sheets - 1
        or range_value["end"] != total_rows + 1
    ):
        raise ProjectionValidationError("XLSX terminal range is not workbook terminal")


def _pptx(value: Mapping[str, Any]) -> None:
    slides = value.get("slides")
    range_value, counts = value["range"], value["counts"]
    if (
        not isinstance(slides, list)
        or len(slides) != counts.get("returned_slides")
        or len(slides) != range_value["end"] - range_value["start"]
    ):
        raise ProjectionValidationError(
            "PPTX returned slide count disagrees with range"
        )
    if [slide.get("slide_number") for slide in slides] != list(
        range(range_value["start"], range_value["end"])
    ):
        raise ProjectionValidationError("PPTX slide identities are not contiguous")
    if (
        value.get("next_cursor") is not None
        and value["next_cursor"].get("next_slide") != range_value["end"]
    ):
        raise ProjectionValidationError("PPTX next slide is not range end")
    total = value["coverage"].get("known_total_slides")
    if (
        not isinstance(total, int)
        or range_value["end"] - 1 > total
        or (value.get("next_cursor") is None and range_value["end"] != total + 1)
    ):
        raise ProjectionValidationError("PPTX range disagrees with known total")


def _image(value: Mapping[str, Any]) -> None:
    tiles, image, range_value, counts = (
        value.get("tiles"),
        value.get("image"),
        value["range"],
        value["counts"],
    )
    if (
        not isinstance(tiles, list)
        or not isinstance(image, Mapping)
        or len(tiles) != counts.get("returned_tiles")
        or len(tiles) != range_value["end"] - range_value["start"]
    ):
        raise ProjectionValidationError(
            "image returned tile count disagrees with range"
        )
    edge = range_value.get("tile_edge")
    columns = math.ceil(image["width"] / edge)
    for expected_index, tile in zip(
        range(range_value["start"], range_value["end"]), tiles, strict=True
    ):
        column, row = expected_index % columns, expected_index // columns
        if (
            tile.get("tile_index") != expected_index
            or tile.get("x") != column * edge
            or tile.get("y") != row * edge
        ):
            raise ProjectionValidationError("image tile topology is not contiguous")
        if (
            tile["x"] + tile["width"] > image["width"]
            or tile["y"] + tile["height"] > image["height"]
        ):
            raise ProjectionValidationError("image tile exceeds source bounds")
        expected_width = min(edge, image["width"] - tile["x"])
        expected_height = min(edge, image["height"] - tile["y"])
        if tile.get("width") != expected_width or tile.get("height") != expected_height:
            raise ProjectionValidationError("image tile dimensions do not match topology")
    if value.get("next_cursor") is not None:
        next_value = value["next_cursor"]
        if (
            next_value.get("next_tile") != range_value["end"]
            or next_value.get("tile_edge") != edge
        ):
            raise ProjectionValidationError("image next tile is not range end")
    total = value["coverage"].get("known_total_tiles")
    if (
        not isinstance(total, int)
        or range_value["end"] > total
        or (value.get("next_cursor") is None and range_value["end"] != total)
    ):
        raise ProjectionValidationError("image range disagrees with known total")
