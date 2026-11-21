"""Deterministic, narrowly scoped JSON repair for unescaped ASCII quotes inside string values.

Providers in ``json_object`` mode (notably DeepSeek when quoting Chinese/English phrases)
occasionally emit an unescaped ``"`` inside a JSON string value, prematurely terminating the
string and causing ``AnswerDeltaParseError`` / ``JSONDecodeError``.

This module repairs *only* that exact syntax defect and refuses all other malformed JSON
shapes (truncated streams, trailing commas, broken escapes, invalid keys, non-object roots).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Literal

_ContainerKind = Literal["object", "array"]
_ObjectExpect = Literal["key_or_end", "key", "colon", "value", "comma_or_end"]
_ArrayExpect = Literal["value_or_end", "value", "comma_or_end"]

# Valid JSON object keys in Trivae final answers are short single-line identifiers.
_OBJECT_KEY_AFTER_COMMA_RE = re.compile(r'"([A-Za-z_][A-Za-z0-9_-]{0,63})"\s*:')


def _next_non_ws(text: str, start: int) -> int:
    length = len(text)
    index = start
    while index < length and text[index] in " \t\r\n":
        index += 1
    return index


def _looks_like_value_terminator(text: str, quote_index: int, container: _ContainerKind) -> bool:
    """Return True only when the quote at ``quote_index`` plausibly terminates a string value."""

    nxt = _next_non_ws(text, quote_index + 1)
    if nxt >= len(text):
        return False
    ch = text[nxt]
    if container == "object":
        if ch == "}":
            after_close = _next_non_ws(text, nxt + 1)
            if after_close >= len(text) or text[after_close] in "}]":
                return True
            if text[after_close] == ",":
                after_comma = _next_non_ws(text, after_close + 1)
                return after_comma < len(text) and text[after_comma] in '{"'
            return False
        if ch == ",":
            after_comma = _next_non_ws(text, nxt + 1)
            return bool(_OBJECT_KEY_AFTER_COMMA_RE.match(text, after_comma))
        return False
    # container == "array"
    if ch == "]":
        after_close = _next_non_ws(text, nxt + 1)
        return after_close >= len(text) or text[after_close] in ",}]"
    if ch == ",":
        after_comma = _next_non_ws(text, nxt + 1)
        if after_comma >= len(text):
            return False
        # In string arrays (e.g. sources / limitations), the next element must begin with a valid JSON value token.
        return text[after_comma] in '"{[-0123456789tfn'
    return False


def repair_unescaped_json_quotes(raw: str) -> tuple[str, int] | None:
    """Escape unescaped ASCII ``"`` inside JSON string values of an object payload.

    Returns ``(repaired_json, escaped_quote_count)`` if and only if:
    1. ``raw`` is a JSON-object-like string that fails strict ``json.loads``;
    2. Escaping inner value quotes produces a string that strictly parses via ``json.loads``
       into a JSON object (``dict``);
    3. At least one quote was escaped.

    Returns ``None`` if ``raw`` is already valid JSON or cannot be repaired strictly by
    escaping inner value quotes.
    """

    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    if not stripped.startswith("{"):
        return None
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        pass
    else:
        return None

    length = len(stripped)
    out: list[str] = []
    stack: list[tuple[_ContainerKind, _ObjectExpect | _ArrayExpect]] = []
    index = 0
    repaired_count = 0

    def _complete_value() -> None:
        if not stack:
            return
        kind, _ = stack[-1]
        stack[-1] = (kind, "comma_or_end")

    while index < length:
        ch = stripped[index]
        if ch in " \t\r\n":
            out.append(ch)
            index += 1
            continue

        if not stack:
            if ch != "{":
                return None
            stack.append(("object", "key_or_end"))
            out.append(ch)
            index += 1
            continue

        kind, expect = stack[-1]
        if kind == "object":
            if expect in {"key_or_end", "key"}:
                if ch == "}" and expect == "key_or_end":
                    stack.pop()
                    out.append(ch)
                    index += 1
                    _complete_value()
                    continue
                if ch != '"':
                    return None
                # Parse key string strictly without repair.
                out.append(ch)
                index += 1
                escaped = False
                closed = False
                while index < length:
                    c = stripped[index]
                    out.append(c)
                    index += 1
                    if escaped:
                        escaped = False
                    elif c == "\\":
                        escaped = True
                    elif c == '"':
                        closed = True
                        break
                    elif ord(c) < 0x20:
                        return None
                if not closed:
                    return None
                stack[-1] = ("object", "colon")
                continue

            if expect == "colon":
                if ch != ":":
                    return None
                out.append(ch)
                index += 1
                stack[-1] = ("object", "value")
                continue

            if expect == "comma_or_end":
                if ch == ",":
                    out.append(ch)
                    index += 1
                    stack[-1] = ("object", "key")
                    continue
                if ch == "}":
                    stack.pop()
                    out.append(ch)
                    index += 1
                    _complete_value()
                    continue
                return None

        else:  # array
            if expect == "comma_or_end":
                if ch == ",":
                    out.append(ch)
                    index += 1
                    stack[-1] = ("array", "value")
                    continue
                if ch == "]":
                    stack.pop()
                    out.append(ch)
                    index += 1
                    _complete_value()
                    continue
                return None
            if expect == "value_or_end" and ch == "]":
                stack.pop()
                out.append(ch)
                index += 1
                _complete_value()
                continue

        # Expecting a value (inside object or array)
        if ch == "{":
            stack.append(("object", "key_or_end"))
            out.append(ch)
            index += 1
            continue
        if ch == "[":
            stack.append(("array", "value_or_end"))
            out.append(ch)
            index += 1
            continue
        if ch == '"':
            out.append(ch)
            index += 1
            escaped = False
            closed = False
            while index < length:
                c = stripped[index]
                if escaped:
                    out.append(c)
                    escaped = False
                    index += 1
                    continue
                if c == "\\":
                    out.append(c)
                    escaped = True
                    index += 1
                    continue
                if ord(c) < 0x20:
                    return None
                if c == '"':
                    if _looks_like_value_terminator(stripped, index, kind):
                        out.append(c)
                        index += 1
                        closed = True
                        break
                    out.append('\\"')
                    repaired_count += 1
                    index += 1
                    continue
                out.append(c)
                index += 1
            if not closed:
                return None
            _complete_value()
            continue

        # Primitive value (number, true, false, null)
        if ch in "-0123456789tfn":
            start = index
            while index < length and stripped[index] not in " \t\r\n,}]":
                index += 1
            out.append(stripped[start:index])
            _complete_value()
            continue

        return None

    if stack or repaired_count == 0:
        return None
    repaired = "".join(out)
    try:
        decoded = json.loads(repaired)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, Mapping):
        return None
    return repaired, repaired_count
