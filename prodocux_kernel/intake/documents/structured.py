"""Bounded inert HTML and bounded structured text projections."""

import json
from decimal import Decimal
from html.parser import HTMLParser

MAX_TEXT_SOURCE = 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 20_000
MAX_JSONL_RECORDS = 1024
MAX_RECORD_BYTES = 64 * 1024
MAX_NUMBER_DIGITS = 256
MAX_DECIMAL_EXPONENT = 308
VOID = frozenset(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"])
INERT = frozenset(["head", "script", "style", "template", "iframe", "object", "embed", "noscript"])


class InertHTML(HTMLParser):
    def __init__(self, emit, omissions):
        super().__init__(convert_charrefs=True)
        self.emit = emit
        self.omissions = omissions
        self.stack = []
        self.ordinal = 0
        self.saw_element = False

    def _tick(self):
        self.ordinal += 1
        if self.ordinal > MAX_NODES:
            raise ValueError("HTML_TOKEN_LIMIT")

    def handle_starttag(self, tag, attributes):
        self._start(tag, attributes, push=tag not in VOID)

    def handle_startendtag(self, tag, attributes):
        self._start(tag, attributes, push=False)

    def _start(self, tag, attributes, *, push):
        self._tick()
        self.saw_element = True
        attrs = dict(attributes)
        if any(key in attrs for key in ("src", "srcset", "href", "data", "poster")):
            self.omissions.add("html_linked_resources_not_loaded")
        style = "".join((attrs.get("style") or "").lower().split())
        suppressed = (tag in INERT or "hidden" in attrs
                      or (attrs.get("aria-hidden") or "").strip().lower() == "true"
                      or "display:none" in style or "visibility:hidden" in style)
        if suppressed:
            self.omissions.add("html_inert_or_hidden_subtree")
        if push:
            if len(self.stack) >= MAX_DEPTH:
                raise ValueError("HTML_DEPTH_LIMIT")
            self.stack.append((tag, self.ordinal, suppressed))

    def handle_endtag(self, tag):
        self._tick()
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError("HTML_UNBALANCED_EXPLICIT_TAGS")
        self.stack.pop()

    def handle_data(self, data):
        self._tick()
        if data.strip() and not any(entry[2] for entry in self.stack):
            line, column = self.getpos()
            self.emit(["html-text", [[name, index] for name, index, _ in self.stack],
                       self.ordinal, line, column], data)

    def handle_comment(self, data):
        self._tick()


def project_html(text, emit, omissions):
    parser = InertHTML(emit, omissions)
    parser.feed(text)
    parser.close()
    if parser.stack or not parser.saw_element:
        raise ValueError("HTML_UNBALANCED_OR_NO_ELEMENTS")
    omissions.add("html_css_layout_not_evaluated")


def _guard_json_depth(text):
    depth = 0
    inside_string = escaped = False
    for char in text:
        if inside_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                inside_string = False
        elif char == '"':
            inside_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError("JSON_DEPTH_LIMIT")
        elif char in "]}":
            depth -= 1


def _object(pairs):
    result = {}
    for key, value in pairs:
        key.encode("utf-8")
        if key in result:
            raise ValueError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("JSON_NONFINITE_NUMBER")


def _integer(token):
    if len(token.lstrip("-")) > MAX_NUMBER_DIGITS:
        raise ValueError("JSON_NUMBER_DIGIT_LIMIT")
    return int(token)


def _decimal(token):
    mantissa, separator, exponent = token.lower().partition("e")
    if sum(char.isdigit() for char in mantissa) > MAX_NUMBER_DIGITS:
        raise ValueError("JSON_NUMBER_DIGIT_LIMIT")
    if separator:
        magnitude = exponent.lstrip("+-")
        if len(magnitude) > 3 or int(magnitude) > MAX_DECIMAL_EXPONENT:
            raise ValueError("JSON_NUMBER_EXPONENT_LIMIT")
    value = Decimal(token)
    if abs(value.adjusted()) > MAX_DECIMAL_EXPONENT:
        raise ValueError("JSON_NUMBER_EXPONENT_LIMIT")
    return value


def _parse_json(text):
    _guard_json_depth(text)
    return json.loads(text, object_pairs_hook=_object, parse_float=_decimal, parse_int=_integer,
                      parse_constant=_reject_constant)


def _leaves(value, path, emit, budget):
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError("JSON_NODE_LIMIT")
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            _leaves(child, path + "/" + escaped, emit, budget)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _leaves(child, path + "/" + str(index), emit, budget)
    else:
        if isinstance(value, str):
            text = value
        elif isinstance(value, Decimal):
            text = str(value)
        else:
            text = json.dumps(value, ensure_ascii=False)
        emit(path, text)


def project_json(payload, emit, *, lines):
    budget = [MAX_NODES]
    if not lines:
        value = _parse_json(payload.decode("utf-8-sig"))
        _leaves(value, "", lambda path, text: emit(["json-pointer", path], text), budget)
        return
    start = 0
    ordinal = 0
    while start < len(payload):
        newline = payload.find(b"\n", start)
        end = len(payload) if newline < 0 else newline + 1
        ordinal += 1
        if ordinal > MAX_JSONL_RECORDS or end - start > MAX_RECORD_BYTES:
            raise ValueError("JSONL_RECORD_LIMIT")
        text = payload[start:end].decode("utf-8-sig" if start == 0 else "utf-8")
        if not text.strip():
            raise ValueError("JSONL_EMPTY_RECORD")
        value = _parse_json(text)
        _leaves(value, "", lambda path, cell, ordinal=ordinal, start=start, end=end: emit(["jsonl-record", ordinal, start, end, path], cell), budget)
        start = end
