"""Internal nested archive and document replay over a controlled snapshot."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from tempfile import TemporaryFile
from unicodedata import normalize

import rfc8785

from .decoders import CHUNK, ArchiveError, open_container


@dataclass(frozen=True)
class MemberSelector:
    ordinal: int
    name: str


@dataclass(frozen=True)
class ChainStep:
    profile: str
    selector: MemberSelector


@contextmanager
def snapshot(source, budget):
    digest = sha256()
    with TemporaryFile() as stored:
        while chunk := source.read(CHUNK):
            budget.charge("source_bytes", len(chunk))
            digest.update(chunk)
            stored.write(chunk)
        stored.seek(0)
        yield stored, digest.hexdigest()


def selected_member(container, selector):
    if type(selector.ordinal) is not int or not 0 <= selector.ordinal < len(
        container.members
    ):
        raise ArchiveError("INVALID_RANGE")
    member = container.members[selector.ordinal]
    if member.name != selector.name:
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    return member


def _projection(name, data):
    if name.casefold().endswith(".pdf"):
        from prodocux_kernel.intake.pdf_projection import (
            extract_pdf_continuable_projection,
        )

        result = extract_pdf_continuable_projection(data)
        units = [
            (str(page["page_number"]), page["text"])
            for page in result["pages"]
            if not page["ocr_required"]
        ]
        return result["parser_contract"], result, units
    from prodocux_kernel.intake.documents import read_document

    result = read_document(name, data)
    units = [(item["source_locator"], item["text"]) for item in result["text_items"]]
    return result["parser_contract"], result, units


def resolve_member(
    source,
    expected_source_sha256,
    chain,
    budget,
    *,
    locator,
    start,
    end,
    expected_quote_sha256,
    expected_provenance=None,
):
    """Replay a quote and bind the exact parser result and all fully read members."""
    if not 1 <= len(chain) <= budget.max_depth:
        raise ArchiveError("BUDGET_EXHAUSTED")
    layers = []
    with ExitStack() as stack:
        current, source_sha256 = stack.enter_context(snapshot(source, budget))
        if source_sha256 != expected_source_sha256:
            raise ArchiveError("SOURCE_CHANGED")
        for step in chain:
            container = stack.enter_context(
                open_container(current, step.profile, budget)
            )
            member = selected_member(container, step.selector)
            result = container.read(member.ordinal, 0, member.size)
            layers.append(
                {
                    "profile": step.profile,
                    "ordinal": str(member.ordinal),
                    "name": member.name,
                    "member_sha256": result.member_sha256,
                }
            )
            current = BytesIO(result.data)
        parser, projection, units = _projection(member.name, result.data)
        budget.check_time()
    matches = [text for unit, text in units if unit == locator]
    if len(matches) != 1:
        raise ArchiveError("LOCATOR_UNAVAILABLE")
    text = normalize("NFC", matches[0])
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
    ):
        raise ArchiveError("INVALID_RANGE")
    quote = text[start:end]
    quote_digest = sha256(quote.encode()).hexdigest()
    if quote_digest != expected_quote_sha256:
        raise ArchiveError("QUOTE_DIGEST_MISMATCH")
    provenance = {
        "source_sha256": source_sha256,
        "layers": layers,
        "parser_contract": parser,
        "projection_sha256": sha256(rfc8785.dumps(projection)).hexdigest(),
        "locator": locator,
        "quote_start": str(start),
        "quote_end": str(end),
        "quote_sha256": quote_digest,
        "coverage": projection["coverage"],
    }
    if expected_provenance is not None and provenance != expected_provenance:
        raise ArchiveError("PROFILE_BINDING_CHANGED")
    return quote, provenance
