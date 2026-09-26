from __future__ import annotations

import base64
import json
from copy import deepcopy
from importlib.resources import files
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from PIL import Image

from api.main import app
from prodocux_kernel.intake import (
    ProjectionValidationError,
    extract_image_tile_projection,
    validate_continuable_projection,
)


def _image() -> bytes:
    image = Image.new("RGB", (600, 600), color=(20, 40, 60))
    image.putpixel((599, 599), (255, 0, 0))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_image_tiles_cover_source_without_gap_and_bind_tail_pixel() -> None:
    raw = _image()
    first = extract_image_tile_projection(
        raw, filename="large.png", max_tiles=2, tile_edge=256
    )
    second = extract_image_tile_projection(
        raw,
        filename="large.png",
        cursor=first["next_cursor"],
        max_tiles=2,
        tile_edge=256,
    )
    third = extract_image_tile_projection(
        raw,
        filename="large.png",
        cursor=second["next_cursor"],
        max_tiles=2,
        tile_edge=256,
    )
    fourth = extract_image_tile_projection(
        raw,
        filename="large.png",
        cursor=third["next_cursor"],
        max_tiles=2,
        tile_edge=256,
    )
    final = extract_image_tile_projection(
        raw,
        filename="large.png",
        cursor=fourth["next_cursor"],
        max_tiles=2,
        tile_edge=256,
    )
    results = [first, second, third, fourth, final]
    assert [
        tile["tile_index"] for result in results for tile in result["tiles"]
    ] == list(range(9))
    assert final["tiles"][-1]["x"] == 512 and final["tiles"][-1]["y"] == 512
    assert final["coverage"]["disposition"] == "complete"
    schema = json.loads(
        files("prodocux_kernel.schemas")
        .joinpath("prodocux_image_tile_projection_v1.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(final)


def test_image_tile_http_discloses_ocr_unavailable_and_capability() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/intake/profile-image/tiles",
        json={
            "document_filename": "large.png",
            "document_b64": base64.b64encode(_image()).decode(),
            "tile_edge": 256,
            "max_tiles": 2,
            "ocr_requested": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["ocr"]["status"] == "unavailable"
    profiles = {
        item["format"]: item
        for item in client.get("/v1/intake/projection-capabilities").json()["profiles"]
    }
    assert profiles["image"]["range_units"] == ["tile"]


def test_image_semantics_reject_overlap_and_descriptor_drift() -> None:
    result = extract_image_tile_projection(
        _image(), filename="large.png", max_tiles=2, tile_edge=256
    )
    invalid = deepcopy(result)
    invalid["tiles"][1]["x"] = 0
    with pytest.raises(ProjectionValidationError, match="topology"):
        validate_continuable_projection(invalid)
    invalid = deepcopy(result)
    invalid["next_cursor"]["tile_edge"] = 512
    with pytest.raises(ProjectionValidationError, match="next tile"):
        validate_continuable_projection(invalid)
