"""EML metadata and body projection. Attachment payloads are never decoded."""

import re
from email import policy
from email.parser import BytesParser

from .structured import project_html

MAX_PARTS = 128
MAX_HEADER_BYTES = 64 * 1024
MAX_HEADER_LINES = 256
MAX_DEPTH = 8
MAX_DECODED_PART = 256 * 1024
HEADERS = frozenset({"subject", "from", "to", "cc", "date", "message-id"})
CHARSETS = frozenset({"utf-8", "utf8", "us-ascii", "ascii", "iso-8859-1", "latin-1"})
ENCODINGS = frozenset({"7bit", "8bit", "binary", "base64", "quoted-printable"})


def _body_text(part, encoding):
    if encoding not in ENCODINGS:
        raise ValueError("EML_UNSUPPORTED_TRANSFER_ENCODING")
    if encoding == "quoted-printable":
        raw = part.get_payload()
        if not isinstance(raw, str) or re.search(r"=(?![0-9a-fA-F]{2}|\r?\n)", raw):
            raise ValueError("EML_INVALID_QUOTED_PRINTABLE")
    charset = (part.get_content_charset() or "us-ascii").lower()
    if charset not in CHARSETS:
        raise ValueError("EML_UNSUPPORTED_CHARSET")
    decoded = part.get_payload(decode=True)
    if part.defects or decoded is None:
        raise ValueError("EML_MALFORMED_TRANSFER")
    if len(decoded) > MAX_DECODED_PART:
        raise ValueError("EML_DECODED_PART_LIMIT")
    return decoded.decode(charset, errors="strict")


def _guard_top_headers(payload):
    end = re.search(rb"\r?\n\r?\n", payload[:MAX_HEADER_BYTES + 4])
    if end is None:
        if len(payload) > MAX_HEADER_BYTES:
            raise ValueError("EML_HEADER_BYTE_LIMIT")
        end_offset = len(payload)
    else:
        end_offset = end.start()
    if end_offset > MAX_HEADER_BYTES:
        raise ValueError("EML_HEADER_BYTE_LIMIT")
    if payload.count(b"\n", 0, end_offset) >= MAX_HEADER_LINES:
        raise ValueError("EML_HEADER_LINE_LIMIT")


def project_eml(payload, emit, omissions):
    _guard_top_headers(payload)
    if b"\0" in payload:
        raise ValueError("EML_BINARY_CONTAINER")
    try:
        message = BytesParser(policy=policy.default).parsebytes(payload)
    except RecursionError as exc:
        raise ValueError("EML_DEPTH_LIMIT") from exc
    headers = {}
    if not message.keys():
        raise ValueError("EML_HEADERS_REQUIRED")
    for name, value in message.items():
        if getattr(value, "defects", ()):
            raise ValueError("EML_MALFORMED_HEADER")
        key = name.lower()
        if key in HEADERS:
            headers[key] = headers.get(key, 0) + 1
            emit(["eml-header", key, headers[key]], str(value))
    attachments = []
    stack = [(message, ())]
    count = 0
    while stack:
        part, path = stack.pop()
        count += 1
        if count > MAX_PARTS or len(path) > MAX_DEPTH:
            raise ValueError("EML_MIME_COMPLEXITY_LIMIT")
        if part.defects:
            raise ValueError("EML_MALFORMED_MIME")
        media = part.get_content_type()
        filename = part.get_filename()
        transfer = str(part.get("Content-Transfer-Encoding", "7bit")).strip().lower()
        if part.get_content_disposition() == "attachment" or filename or media.startswith("message/"):
            attachments.append({"part_path": list(path), "filename": filename,
                                "media_type": media, "transfer_encoding": transfer})
            omissions.add("eml_attachment_or_message_not_expanded")
        elif part.is_multipart():
            stack.extend(reversed([(child, (*path, index))
                                   for index, child in enumerate(part.iter_parts(), 1)]))
        elif media in {"text/plain", "text/html"}:
            text = _body_text(part, transfer)
            if media == "text/plain":
                emit(["eml-body", list(path), media, transfer], text)
            else:
                project_html(text, lambda locator, value, path=path, transfer=transfer: emit(
                    ["eml-html-body", list(path), transfer, locator], value
                ), omissions)
        else:
            omissions.add("eml_unsupported_inline_media")
    return {"attachments": attachments, "visited_parts": count}
