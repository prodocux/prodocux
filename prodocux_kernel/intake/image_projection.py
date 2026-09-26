"""Deterministic image tile inventory with explicit OCR evaluation state."""

from __future__ import annotations

import hashlib
import io
import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from PIL import Image, UnidentifiedImageError

from prodocux_kernel.intake.errors import SourceTooLargeError
from prodocux_kernel.intake.image import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS
from prodocux_kernel.intake.projection_validate import validate_continuable_projection

MAX_TILE_EDGE = 2048
MAX_TILES_PER_RANGE = 16
PARSER_CONTRACT_NAME = "prodocux_image_tile_projection_v1"
PARSER_CONTRACT_VERSION = "1"


def extract_image_tile_projection(
    payload: bytes,
    *,
    filename: str,
    cursor: Mapping[str, Any] | None = None,
    max_tiles: int = MAX_TILES_PER_RANGE,
    tile_edge: int = MAX_TILE_EDGE,
    ocr_requested: bool = False,
) -> dict[str, Any]:
    if not payload:
        raise ValueError("image is empty")
    if len(payload) > MAX_IMAGE_BYTES:
        raise SourceTooLargeError("image exceeds inline intake limit")
    if not 1 <= max_tiles <= MAX_TILES_PER_RANGE:
        raise ValueError("max_tiles must be between 1 and 16")
    if not 256 <= tile_edge <= MAX_TILE_EDGE:
        raise ValueError("tile_edge must be between 256 and 2048")
    suffix = filename.casefold().rsplit(".", 1)[-1]
    if suffix not in {"jpg", "jpeg", "png"}:
        raise ValueError("image filename must end with .jpg, .jpeg, or .png")
    source_sha256 = hashlib.sha256(payload).hexdigest()
    try:
        image = Image.open(io.BytesIO(payload))
        image.load()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise ValueError("image is not a valid bounded JPEG or PNG") from exc
    if (
        image.format not in {"JPEG", "PNG"}
        or image.width * image.height > MAX_IMAGE_PIXELS
    ):
        raise ValueError("image format or pixel count exceeds supported boundary")
    columns = math.ceil(image.width / tile_edge)
    rows = math.ceil(image.height / tile_edge)
    total_tiles = columns * rows
    start_tile = 0
    if cursor is not None:
        expected = {
            "schema_version": "prodocux_projection_cursor_v1",
            "source_sha256": source_sha256,
            "parser_contract_name": PARSER_CONTRACT_NAME,
            "parser_contract_version": PARSER_CONTRACT_VERSION,
            "tile_edge": tile_edge,
        }
        for name, value in expected.items():
            if cursor.get(name) != value:
                raise ValueError(f"cursor {name} does not match source projection")
        start_tile = cursor.get("next_tile")
        if (
            not isinstance(start_tile, int)
            or isinstance(start_tile, bool)
            or start_tile < 0
        ):
            raise ValueError("cursor next_tile must be a non-negative integer")
    if start_tile >= total_tiles:
        raise ValueError("cursor next_tile exceeds image tile count")
    end_tile = min(start_tile + max_tiles, total_tiles)
    tiles: list[dict[str, Any]] = []
    normalized = image.convert("RGBA")
    for tile_index in range(start_tile, end_tile):
        column, row = tile_index % columns, tile_index // columns
        x, y = column * tile_edge, row * tile_edge
        width, height = (
            min(tile_edge, image.width - x),
            min(tile_edge, image.height - y),
        )
        tile = normalized.crop((x, y, x + width, y + height))
        tiles.append(
            {
                "tile_index": tile_index,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "rgba_sha256": hashlib.sha256(tile.tobytes()).hexdigest(),
            }
        )
    next_cursor = None
    if end_tile < total_tiles:
        next_cursor = {
            "schema_version": "prodocux_projection_cursor_v1",
            "source_sha256": source_sha256,
            "parser_contract_name": PARSER_CONTRACT_NAME,
            "parser_contract_version": PARSER_CONTRACT_VERSION,
            "tile_edge": tile_edge,
            "next_tile": end_tile,
        }
    result = {
        "schema_version": "prodocux_image_tile_projection_v1",
        "source_sha256": source_sha256,
        "parser_contract": {
            "name": PARSER_CONTRACT_NAME,
            "version": PARSER_CONTRACT_VERSION,
        },
        "image": {"width": image.width, "height": image.height, "mode": image.mode},
        "range": {
            "unit": "tile",
            "start": start_tile,
            "end": end_tile,
            "requested_max_tiles": max_tiles,
            "tile_edge": tile_edge,
        },
        "tiles": tiles,
        "next_cursor": deepcopy(next_cursor),
        "coverage": {
            "disposition": "partial_known" if next_cursor else "complete",
            "known_total_tiles": total_tiles,
            "continuation_available": next_cursor is not None,
            "omitted_content_classes": [],
        },
        "ocr": {
            "requested": ocr_requested,
            "status": "unavailable" if ocr_requested else "not_evaluated",
            "regions": [],
        },
        "counts": {"returned_tiles": len(tiles)},
    }
    validate_continuable_projection(result)
    return result
