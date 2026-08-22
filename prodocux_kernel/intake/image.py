"""Bounded, model-free JPEG/PNG profiling with optional host OCR."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from io import BytesIO
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_TEXT_REGIONS = 100
MAX_REGION_TEXT = 2_000
IMAGE_PROFILE_SCHEMA = "prodocux_image_profile_v1"

_ORIENTATION = {
    1: (0, False),
    2: (0, True),
    3: (180, False),
    4: (180, True),
    5: (90, True),
    6: (90, False),
    7: (270, True),
    8: (270, False),
}


class ImageOcrBackend(Protocol):
    """Optional host-installed deterministic OCR boundary."""

    @property
    def backend_id(self) -> str: ...

    @property
    def backend_version(self) -> str: ...

    def extract_regions(self, image: Image.Image) -> list[Mapping[str, Any]]: ...


def _validated_regions(
    raw_regions: list[Mapping[str, Any]], *, width: int, height: int
) -> tuple[list[dict[str, Any]], bool]:
    regions: list[dict[str, Any]] = []
    for raw in raw_regions:
        allowed = {"x", "y", "width", "height", "text", "confidence"}
        if set(raw) - allowed:
            raise ValueError("OCR region contains unknown fields")
        x, y = raw.get("x"), raw.get("y")
        region_width, region_height = raw.get("width"), raw.get("height")
        text = raw.get("text")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (x, y, region_width, region_height)):
            raise ValueError("OCR region coordinates must be integers")
        if x < 0 or y < 0 or region_width < 1 or region_height < 1:
            raise ValueError("OCR region bounds must be positive")
        if x + region_width > width or y + region_height > height:
            raise ValueError("OCR region exceeds image bounds")
        if not isinstance(text, str) or len(text) > MAX_REGION_TEXT:
            raise ValueError("OCR region text exceeds limit")
        region: dict[str, Any] = {
            "x": x,
            "y": y,
            "width": region_width,
            "height": region_height,
            "text": text,
        }
        if "confidence" in raw:
            confidence = raw["confidence"]
            if (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not 0 <= confidence <= 1
            ):
                raise ValueError("OCR region confidence must be between zero and one")
            region["confidence"] = float(confidence)
        regions.append(region)
    regions.sort(key=lambda item: (item["y"], item["x"], item["text"]))
    return regions[:MAX_TEXT_REGIONS], len(regions) > MAX_TEXT_REGIONS


def profile_image_bytes(
    raw: bytes,
    *,
    filename: str,
    ocr_requested: bool = False,
    ocr_backend: ImageOcrBackend | None = None,
) -> dict[str, Any]:
    """Return a deterministic privacy-safe image profile."""
    if not raw:
        raise ValueError("image is empty")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image exceeds intake limit")
    suffix = filename.casefold().rsplit(".", 1)[-1]
    if suffix not in {"jpg", "jpeg", "png"}:
        raise ValueError("image filename must end with .jpg, .jpeg, or .png")
    try:
        with Image.open(BytesIO(raw)) as probe:
            if probe.format not in {"JPEG", "PNG"}:
                raise ValueError("image must decode as JPEG or PNG")
            if probe.width * probe.height > MAX_IMAGE_PIXELS:
                raise ValueError("image pixel count exceeds limit")
            probe.verify()
        with Image.open(BytesIO(raw)) as image:
            image.load()
            detected = image.format
            if detected not in {"JPEG", "PNG"}:
                raise ValueError("image must decode as JPEG or PNG")
            if (detected == "PNG") != (suffix == "png"):
                raise ValueError("image filename does not match decoded format")
            width, height = image.size
            mode = image.mode
            exif = image.getexif()
            orientation_value = int(exif.get(274, 1))
            if orientation_value not in _ORIENTATION:
                orientation_value = 1
            rotation, mirrored = _ORIENTATION[orientation_value]
            gps_present = 34853 in exif
            ocr: dict[str, Any] = {
                "requested": ocr_requested,
                "available": ocr_backend is not None,
                "status": "not_requested",
                "regions": [],
                "truncated": False,
            }
            review_flags: list[str] = []
            if ocr_requested and ocr_backend is None:
                ocr["status"] = "unavailable"
                review_flags.extend(["OCR_REQUIRED", "OCR_UNAVAILABLE"])
            elif ocr_requested and ocr_backend is not None:
                backend_id = ocr_backend.backend_id
                backend_version = ocr_backend.backend_version
                if not backend_id or len(backend_id) > 128:
                    raise ValueError("OCR backend identity is invalid")
                if not backend_version or len(backend_version) > 64:
                    raise ValueError("OCR backend version is invalid")
                regions, truncated = _validated_regions(
                    ocr_backend.extract_regions(image.copy()),
                    width=width,
                    height=height,
                )
                ocr.update(
                    {
                        "status": "completed",
                        "backend": backend_id,
                        "backend_version": backend_version,
                        "regions": regions,
                        "truncated": truncated,
                    }
                )
                if truncated:
                    review_flags.append("TEXT_REGIONS_TRUNCATED")
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise ValueError("image is not a valid bounded JPEG or PNG") from exc

    return {
        "schema_version": IMAGE_PROFILE_SCHEMA,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "media_type": "image/jpeg" if detected == "JPEG" else "image/png",
        "file_size_bytes": len(raw),
        "width_pixels": width,
        "height_pixels": height,
        "mode": mode,
        "orientation": {
            "exif_value": orientation_value,
            "rotation_degrees": rotation,
            "mirrored": mirrored,
        },
        "valid": True,
        "exif": {"present": bool(exif), "gps_present": gps_present},
        "ocr_required": ocr_requested and ocr_backend is None,
        "ocr": ocr,
        "review_flags": review_flags,
    }
