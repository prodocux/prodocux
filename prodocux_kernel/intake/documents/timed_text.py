"""Bounded timed-text source snapshots."""

import re
from dataclasses import dataclass
from hashlib import sha256

PROFILES = {"markdown", "log", "srt", "webvtt"}
TIME = r"(?:[0-9]{2,}:)?[0-5][0-9]:[0-5][0-9][.,][0-9]{3}"
TIMING = re.compile(rf"({TIME}) --> ({TIME})(?:[ \t]+(.*))?")


def milliseconds(value):
    *parts, fraction = re.split(r"[:.,]", value)
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds * 1000 + int(fraction)


@dataclass(frozen=True)
class Locator:
    source_sha256: str
    profile: str
    ordinal: int
    start: int
    end: int


class Snapshot:
    def __init__(self, raw: bytes, profile: str):
        if profile not in PROFILES or len(raw) > 8 * 1024 * 1024:
            raise ValueError("UNSUPPORTED_PROFILE_OR_SIZE")
        self.raw = raw
        self.profile = profile
        self.digest = sha256(raw).hexdigest()
        decoded = raw.decode("utf-8-sig", errors="strict")
        if "\x00" in decoded:
            raise ValueError("BINARY_CONTENT")
        self.bom = 3 if raw.startswith(b"\xef\xbb\xbf") else 0
        self.records = []
        if profile in {"srt", "webvtt"}:
            self._parse_cues()
        else:
            for line in re.finditer(rb"[^\r\n]+(?:\r\n|\r|\n)?|\r\n|\r|\n", raw[self.bom:]):
                self.records.append((line.start() + self.bom, line.end() + self.bom, {}))

    def _parse_cues(self):
        offset = self.bom
        blocks = re.split(rb"((?:\r?\n){2,})", self.raw[offset:])
        if self.profile == "webvtt":
            if not re.fullmatch(rb"WEBVTT(?:[ \t][^\r\n]*)?", blocks[0]):
                raise ValueError("UNSUPPORTED_WEBVTT_HEADER")
            offset += len(blocks[0]) + (len(blocks[1]) if len(blocks) > 1 else 0)
            blocks = blocks[2:]
        for block, separator in zip(blocks[::2], blocks[1::2] + [b""]):
            if block:
                lines = block.decode("utf-8").splitlines()
                cue_id = None
                if "-->" not in lines[0]:
                    cue_id = lines.pop(0)
                match = TIMING.fullmatch(lines[0]) if lines else None
                if not match or len(lines) < 2:
                    raise ValueError("UNSUPPORTED_CUE")
                start, end, settings = match.groups()
                if self.profile == "srt":
                    if not cue_id or not cue_id.isascii() or not cue_id.isdecimal() or settings or any("," not in t or t.count(":") != 2 for t in (start, end)):
                        raise ValueError("UNSUPPORTED_SRT_CUE")
                elif any("." not in t for t in (start, end)):
                    raise ValueError("UNSUPPORTED_WEBVTT_CUE")
                start_ms, end_ms = map(milliseconds, (start, end))
                if start_ms >= end_ms:
                    raise ValueError("INVALID_TIME_RANGE")
                self.records.append((offset, offset + len(block), {
                    "cue_id": cue_id, "start_ms": start_ms, "end_ms": end_ms,
                    "settings": settings, "payload": "\n".join(lines[1:]),
                }))
            offset += len(block) + len(separator)

    def inspect(self):
        return {"sha256": self.digest, "size_bytes": len(self.raw), "profile": self.profile,
                "parser": "prodocux_timed_text_v1", "encoding": "utf-8", "bom_bytes": self.bom,
                "record_count": len(self.records)}

    def read(self, *, cursor=None, max_bytes=8192, max_records=64):
        if max_bytes < 1 or max_records < 1:
            raise ValueError("INVALID_BUDGET")
        index = 0 if cursor is None else self._validate(cursor) + 1
        output = []
        used = 0
        for ordinal in range(index, min(index + max_records, len(self.records))):
            start, end, metadata = self.records[ordinal]
            if used + end - start > max_bytes:
                if not output:
                    raise ValueError("RECORD_EXCEEDS_BUDGET")
                break
            locator = Locator(self.digest, self.profile, ordinal, start, end)
            output.append((locator, self.raw[start:end].decode("utf-8"), dict(metadata)))
            used += end - start
        complete = index + len(output) == len(self.records)
        return {"records": output, "returned_source_bytes": used,
                "next": None if complete else output[-1][0], "complete": complete}

    def _validate(self, locator):
        if (locator.source_sha256, locator.profile) != (self.digest, self.profile):
            raise ValueError("STALE_SOURCE_OR_PROFILE")
        if not 0 <= locator.ordinal < len(self.records):
            raise ValueError("INVALID_LOCATOR")
        start, end, _ = self.records[locator.ordinal]
        if (start, end) != (locator.start, locator.end):
            raise ValueError("INVALID_LOCATOR")
        return locator.ordinal

    def resolve(self, locator):
        self._validate(locator)
        return self.raw[locator.start:locator.end]
