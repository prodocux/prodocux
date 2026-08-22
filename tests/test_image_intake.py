from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from PIL import Image

from api.main import app
from prodocux_kernel.intake import profile_image_bytes

ROOT = Path(__file__).resolve().parents[1]


def _image_bytes(format_name: str = "PNG", *, orientation: int | None = None) -> bytes:
    image = Image.new("RGB", (12, 8), color=(20, 40, 60))
    output = BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    image.save(output, format=format_name, exif=exif)
    return output.getvalue()


def test_image_profile_is_deterministic_and_privacy_safe() -> None:
    raw = _image_bytes("JPEG", orientation=6)
    first = profile_image_bytes(raw, filename="photo.jpg")
    second = profile_image_bytes(raw, filename="photo.jpg")
    assert first == second
    assert first["media_type"] == "image/jpeg"
    assert first["orientation"] == {
        "exif_value": 6,
        "rotation_degrees": 90,
        "mirrored": False,
    }
    assert first["exif"] == {"present": True, "gps_present": False}
    assert "gps" not in json.dumps(first["exif"]).casefold().replace("gps_present", "")


def test_image_api_accepts_png_and_discloses_unavailable_ocr() -> None:
    raw = _image_bytes()
    response = TestClient(app).post(
        "/v1/intake/profile-image",
        json={
            "document_filename": "front.png",
            "document_b64": base64.b64encode(raw).decode("ascii"),
            "ocr_requested": True,
        },
    )
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["width_pixels"] == 12
    assert profile["height_pixels"] == 8
    assert profile["ocr_required"] is True
    assert profile["ocr"]["status"] == "unavailable"
    assert profile["review_flags"] == ["OCR_REQUIRED", "OCR_UNAVAILABLE"]


class FakeOcr:
    backend_id = "deterministic.fake"
    backend_version = "1"

    def extract_regions(self, image: Image.Image) -> list[dict]:
        return [
            {"x": index % 10, "y": index % 6, "width": 1, "height": 1, "text": f"r{index}"}
            for index in range(101)
        ]


def test_explicit_ocr_backend_is_bounded_and_sorted() -> None:
    profile = profile_image_bytes(
        _image_bytes(),
        filename="back.png",
        ocr_requested=True,
        ocr_backend=FakeOcr(),
    )
    assert profile["ocr"]["status"] == "completed"
    assert profile["ocr"]["backend"] == "deterministic.fake"
    assert len(profile["ocr"]["regions"]) == 100
    assert profile["ocr"]["truncated"] is True
    assert profile["review_flags"] == ["TEXT_REGIONS_TRUNCATED"]


def test_invalid_image_mismatch_path_and_unknown_fields_fail_closed() -> None:
    client = TestClient(app)
    invalid = client.post(
        "/v1/intake/profile-image",
        json={
            "document_filename": "bad.png",
            "document_b64": base64.b64encode(b"not-an-image").decode("ascii"),
        },
    )
    assert invalid.status_code == 400
    mismatch = client.post(
        "/v1/intake/profile-image",
        json={
            "document_filename": "wrong.jpg",
            "document_b64": base64.b64encode(_image_bytes()).decode("ascii"),
        },
    )
    assert mismatch.status_code == 400
    path = client.post(
        "/v1/intake/profile-image",
        json={
            "document_filename": "../front.png",
            "document_b64": base64.b64encode(_image_bytes()).decode("ascii"),
        },
    )
    assert path.status_code == 400
    unknown = client.post(
        "/v1/intake/profile-image",
        json={
            "document_filename": "front.png",
            "document_b64": base64.b64encode(_image_bytes()).decode("ascii"),
            "url": "https://example.invalid/image.png",
        },
    )
    assert unknown.status_code == 422


def test_image_profile_example_matches_schema() -> None:
    schema = json.loads(
        (ROOT / "prodocux_kernel/schemas/prodocux_image_profile_v1.json").read_text(
            encoding="utf-8"
        )
    )
    example = json.loads(
        (ROOT / "examples/contracts/image_profile_v1.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(example)
