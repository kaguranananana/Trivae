"""Query 真实执行事件到接口无关实时事件的薄投影。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from trivae.observability.contracts import NormalizedQueryEvent
from trivae.query.evidence import ToolResultRecord
from trivae.query.runtime.contracts import RuntimeEvent

_TOOL_DETAIL_MAX_ITEMS = 20
_TOOL_DETAIL_MAX_FIELD_CHARS = 800
_TOOL_DETAIL_MAX_TOTAL_CHARS = 16_000
_TOOL_DETAIL_FOOTER_RESERVE = 240

QueryStreamEventType = Literal[
    "query.started",
    "route.completed",
    "plan.completed",
    "plan.failed",
    "thinking.started",
    "thinking.delta",
    "thinking.completed",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "retrieval.started",
    "retrieval.completed",
    "retrieval.failed",
    "answer.delta",
    "answer.completed",
    "query.completed",
    "query.failed",
    "query.aborted",
    "usage.updated",
]


@dataclass(frozen=True)
class QueryStreamEvent:
    """CLI/UI 共用的 provider-neutral 实时事件。"""

    type: QueryStreamEventType
    sequence: int
    trace_id: str | None = None
    content: str | None = None
    # 只有 Runtime adapter 明确标记的 provider public summary 才允许进入用户过程展示。
    thinking_visibility: Literal["public_summary"] | None = None
    route: str | None = None
    plan: Mapping[str, object] | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    arguments: Mapping[str, object] | None = None
    result_summary: Mapping[str, object] | None = None
    result_detail: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: float | None = None
    usage: Mapping[str, int | float] | None = None
    source_operation: str | None = None
    source_sequence: int | None = None
    parent_operation_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


QueryStreamEventHandler = Callable[[QueryStreamEvent], None]


def project_tool_result_detail(record: ToolResultRecord) -> str:
    """把 canonical ToolResultRecord 投影为有界、provider-neutral 的 TUI 明细。"""

    item_texts: list[tuple[str, bool]] = []
    for index, item in enumerate(record.message_items, start=1):
        message = item.message
        sender = message.sender_name or message.sender_user_id or message.sender_platform_id or "未知发送者"
        session = message.session_display or message.session_id
        fields = (
            ("source", record.message_source_handle(item)),
            ("sender", sender),
            ("time", message.timestamp),
            ("session", session),
            ("content", message.normalized_content),
            ("hit", item.is_hit),
            ("urls", item.urls),
        )
        item_texts.append(_detail_item_text(index, fields))

    # field locator 是 row/aggregate 的可引用子项；TUI 结果列表展示完整父项即可，避免同一结果重复占位。
    primary_structured = tuple(item for item in record.structured_items if item.locator_kind != "field")
    for index, structured_item in enumerate(primary_structured, start=len(item_texts) + 1):
        structured_fields = (
            ("source", record.structured_source_handle(structured_item)),
            ("locator", structured_item.locator),
            ("kind", structured_item.locator_kind),
            ("value", structured_item.value_snapshot),
        )
        item_texts.append(_detail_item_text(index, structured_fields))

    available_count = len(item_texts)
    selected: list[str] = []
    used_chars = 0
    field_truncated = False
    body_budget = _TOOL_DETAIL_MAX_TOTAL_CHARS - _TOOL_DETAIL_FOOTER_RESERVE
    for text, truncated in item_texts[:_TOOL_DETAIL_MAX_ITEMS]:
        separator_chars = 2 if selected else 0
        if used_chars + separator_chars + len(text) > body_budget:
            break
        selected.append(text)
        used_chars += separator_chars + len(text)
        field_truncated = field_truncated or truncated

    displayed_count = len(selected)
    omitted_count = available_count - displayed_count
    sections = [*selected]
    if record.limitations:
        limitations = ", ".join(record.limitations)
        bounded, limitations_truncated = _bounded_detail_value(limitations)
        sections.append(f"限制: {bounded}")
        field_truncated = field_truncated or limitations_truncated
    if omitted_count:
        sections.append(f"仅显示 {displayed_count} / {available_count} 条；{omitted_count} 条未在 TUI 展示")
    if field_truncated:
        sections.append(f"部分字段已按 {_TOOL_DETAIL_MAX_FIELD_CHARS} 字符上限截断")
    if not sections:
        # 双空 record（如聚合型工具）也必须给出可读正文；expanded 视图不允许空白。
        sections.append(f"状态: {record.status}；结果无可展示正文（返回条目 0 条）")

    detail = "\n\n".join(sections)
    if len(detail) > _TOOL_DETAIL_MAX_TOTAL_CHARS:
        raise ValueError("tool result detail exceeded the declared TUI character budget")
    return detail


def _detail_item_text(index: int, fields: tuple[tuple[str, object], ...]) -> tuple[str, bool]:
    """逐字段限幅后生成一个稳定条目，并显式返回是否发生预览截断。"""

    lines = [f"[{index}]"]
    truncated = False
    for name, value in fields:
        bounded, was_truncated = _bounded_detail_value(value)
        lines.append(f"{name}: {bounded}")
        truncated = truncated or was_truncated
    return "\n".join(lines), truncated


def _bounded_detail_value(value: object) -> tuple[str, bool]:
    """只序列化普通 canonical 值；截断是 UI 预览事实，不改写业务完整性字段。"""

    if isinstance(value, (Mapping, list, tuple)):
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        rendered = str(value)
    if len(rendered) <= _TOOL_DETAIL_MAX_FIELD_CHARS:
        return rendered, False
    return f"{rendered[: _TOOL_DETAIL_MAX_FIELD_CHARS - 1]}…", True


class AnswerDeltaParseError(ValueError):
    """Provider 正文流不符合 final answer 的 JSON/plain-text lexical contract。"""


_JsonPathPart = str | int
_ObjectState = Literal["key_or_end", "key", "colon", "value", "comma_or_end"]
_ArrayState = Literal["value_or_end", "value", "comma_or_end"]


@dataclass
class _JsonFrame:
    """一个 JSON object/array 的最小增量解析状态。"""

    kind: Literal["object", "array"]
    path: tuple[_JsonPathPart, ...]
    state: _ObjectState | _ArrayState
    pending_key: str | None = None
    next_index: int = 0


class AnswerArtifactDeltaParser:
    """增量提取 ``content_blocks[*].text``，不承担 Finalizer 校验。"""

    def __init__(self) -> None:
        self._mode: Literal["unknown", "json", "plain"] = "unknown"
        self._leading_whitespace = ""
        self._plain_trailing_whitespace = ""
        self._frames: list[_JsonFrame] = []
        self._root_complete = False
        self._in_string = False
        self._string_role: Literal["key", "value"] | None = None
        self._string_buffer: list[str] = []
        self._string_is_target = False
        self._target_has_output = False
        self._escape_pending = False
        self._unicode_digits: str | None = None
        self._pending_high_surrogate: int | None = None
        self._primitive = ""
        self._target_count = 0
        self._output: list[str] = []

    def feed(self, chunk: str) -> str:
        """消费一个 provider chunk，并返回本 chunk 新解码出的用户正文。"""

        if not isinstance(chunk, str):
            raise TypeError("answer delta chunk must be a string")
        self._output = []
        for character in chunk:
            self._feed_character(character)
        return "".join(self._output)

    def finish(self) -> str:
        """在 Runtime completed 时验证 lexical stream，并丢弃 plain text 尾部空白。"""

        if self._mode == "unknown":
            return ""
        if self._mode == "plain":
            # parse_answer_output() 会 strip plain text；尾部空白因此不能成为正式 answer preview。
            self._plain_trailing_whitespace = ""
            return ""
        if self._in_string or self._escape_pending or self._unicode_digits is not None:
            raise AnswerDeltaParseError("answer JSON stream ended inside a string escape")
        if self._primitive:
            self._complete_primitive()
        if self._frames or not self._root_complete:
            raise AnswerDeltaParseError("answer JSON stream ended before the root value completed")
        return ""

    def _feed_character(self, character: str) -> None:
        """先确定 plain/JSON 模式，再把字符送进唯一对应的 lexical path。"""

        if self._mode == "unknown":
            if character.isspace():
                self._leading_whitespace += character
                return
            if character == "{":
                self._mode = "json"
                self._leading_whitespace = ""
                self._start_container("object")
                return
            # 现有 Finalizer 明确接受非结构化 plain text；该分支直接投影同一正式正文语义。
            self._mode = "plain"
            self._leading_whitespace = ""
            self._feed_plain(character)
            return
        if self._mode == "plain":
            self._feed_plain(character)
            return
        self._feed_json(character)

    def _feed_plain(self, character: str) -> None:
        """延迟 plain text 尾部空白，使 preview 与 Finalizer 的 strip 语义一致。"""

        if character.isspace():
            self._plain_trailing_whitespace += character
            return
        if self._plain_trailing_whitespace:
            self._output.append(self._plain_trailing_whitespace)
            self._plain_trailing_whitespace = ""
        self._output.append(character)

    def _feed_json(self, character: str) -> None:
        """按 string、primitive、container 的互斥状态逐字符推进 JSON。"""

        if self._in_string:
            self._feed_string(character)
            return
        if self._primitive:
            if character in ",]}" or character.isspace():
                self._complete_primitive()
                if not character.isspace():
                    self._feed_json(character)
                return
            self._primitive += character
            return
        if character.isspace():
            return
        if not self._frames:
            if self._root_complete:
                raise AnswerDeltaParseError("answer JSON stream has data after the root value")
            self._start_value(character)
            return

        frame = self._frames[-1]
        if frame.kind == "object":
            self._feed_object(frame, character)
        else:
            self._feed_array(frame, character)

    def _feed_object(self, frame: _JsonFrame, character: str) -> None:
        """推进 object 的 key/colon/value/comma 四个显式状态。"""

        if frame.state in {"key_or_end", "key"}:
            if character == "}" and frame.state == "key_or_end":
                self._close_container("object")
                return
            if character != '"':
                raise AnswerDeltaParseError("answer JSON object expected a string key")
            self._start_string("key", is_target=False)
            return
        if frame.state == "colon":
            if character != ":":
                raise AnswerDeltaParseError("answer JSON object expected ':' after a key")
            frame.state = "value"
            return
        if frame.state == "value":
            self._start_value(character)
            return
        if character == ",":
            # comma 后必须再有一个 key，不能把 trailing comma 当成合法 object。
            frame.state = "key"
            return
        if character == "}":
            self._close_container("object")
            return
        raise AnswerDeltaParseError("answer JSON object expected ',' or '}'")

    def _feed_array(self, frame: _JsonFrame, character: str) -> None:
        """推进 array 的 value/comma 状态，并由 frame 分配稳定元素下标。"""

        if frame.state in {"value_or_end", "value"}:
            if character == "]" and frame.state == "value_or_end":
                self._close_container("array")
                return
            self._start_value(character)
            return
        if character == ",":
            # comma 后必须再有一个 value，不能把 trailing comma 当成合法 array。
            frame.state = "value"
            return
        if character == "]":
            self._close_container("array")
            return
        raise AnswerDeltaParseError("answer JSON array expected ',' or ']'")

    def _start_value(self, character: str) -> None:
        """依据首字符启动 string/container/primitive，不解析无关字段的业务值。"""

        path = self._current_value_path()
        if character == '"':
            is_target = (
                len(path) == 3
                and path[0] == "content_blocks"
                and isinstance(path[1], int)
                and path[2] == "text"
            )
            self._start_string("value", is_target=is_target)
            return
        if character == "{":
            self._start_container("object")
            return
        if character == "[":
            self._start_container("array")
            return
        if character in "-0123456789tfn":
            self._primitive = character
            return
        raise AnswerDeltaParseError("answer JSON contains an invalid value token")

    def _start_container(self, kind: Literal["object", "array"]) -> None:
        """把新容器绑定到当前 value path；父容器只在该容器关闭后完成 value。"""

        path = self._current_value_path()
        state: _ObjectState | _ArrayState = "key_or_end" if kind == "object" else "value_or_end"
        self._frames.append(_JsonFrame(kind=kind, path=path, state=state))

    def _close_container(self, expected_kind: Literal["object", "array"]) -> None:
        """关闭当前容器并精确完成父级的一个 value。"""

        if not self._frames or self._frames[-1].kind != expected_kind:
            raise AnswerDeltaParseError("answer JSON container closing token does not match")
        frame = self._frames[-1]
        if frame.kind == "object" and frame.state not in {"key_or_end", "comma_or_end"}:
            raise AnswerDeltaParseError("answer JSON object closed before its value completed")
        if frame.kind == "array" and frame.state not in {"value_or_end", "comma_or_end"}:
            raise AnswerDeltaParseError("answer JSON array closed before its value completed")
        self._frames.pop()
        self._complete_value()

    def _start_string(self, role: Literal["key", "value"], *, is_target: bool) -> None:
        """开启一个 JSON string；key 完整缓存，目标 value 则边解码边输出。"""

        self._in_string = True
        self._string_role = role
        self._string_buffer = []
        self._string_is_target = is_target
        self._target_has_output = False
        self._escape_pending = False
        self._unicode_digits = None
        self._pending_high_surrogate = None

    def _feed_string(self, character: str) -> None:
        """解码普通字符、短 escape 和可跨 chunk 的 unicode escape。"""

        if self._unicode_digits is not None:
            if character not in "0123456789abcdefABCDEF":
                raise AnswerDeltaParseError("answer JSON contains an invalid unicode escape")
            self._unicode_digits += character
            if len(self._unicode_digits) == 4:
                codepoint = int(self._unicode_digits, 16)
                self._unicode_digits = None
                self._append_decoded_codepoint(codepoint)
            return
        if self._escape_pending:
            self._escape_pending = False
            if character == "u":
                # 空字符串表示 unicode escape 已开始，后续字符逐个补齐四位。
                self._unicode_digits = ""
                return
            escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
            decoded = escapes.get(character)
            if decoded is None:
                raise AnswerDeltaParseError("answer JSON contains an invalid string escape")
            self._append_decoded(decoded)
            return
        if character == "\\":
            self._escape_pending = True
            return
        if character == '"':
            self._finish_string()
            return
        if ord(character) < 0x20:
            raise AnswerDeltaParseError("answer JSON string contains an unescaped control character")
        self._append_decoded(character)

    def _append_decoded_codepoint(self, codepoint: int) -> None:
        """组合 UTF-16 surrogate pair，避免向终端输出半个 Unicode 字符。"""

        if 0xD800 <= codepoint <= 0xDBFF:
            if self._pending_high_surrogate is not None:
                raise AnswerDeltaParseError("answer JSON contains consecutive high surrogates")
            self._pending_high_surrogate = codepoint
            return
        if 0xDC00 <= codepoint <= 0xDFFF:
            if self._pending_high_surrogate is None:
                raise AnswerDeltaParseError("answer JSON contains an unmatched low surrogate")
            high = self._pending_high_surrogate
            self._pending_high_surrogate = None
            combined = 0x10000 + ((high - 0xD800) << 10) + (codepoint - 0xDC00)
            self._append_decoded(chr(combined))
            return
        if self._pending_high_surrogate is not None:
            raise AnswerDeltaParseError("answer JSON contains an unmatched high surrogate")
        self._append_decoded(chr(codepoint))

    def _append_decoded(self, value: str) -> None:
        """key 写入 buffer；目标 text 在第二个 block 前插入与 answer_text 相同的双换行。"""

        if self._string_role == "key" or not self._string_is_target:
            self._string_buffer.append(value)
            return
        if not self._target_has_output and self._target_count > 0:
            self._output.append("\n\n")
        self._target_has_output = True
        self._output.append(value)

    def _finish_string(self) -> None:
        """完成 key/value string，并把父容器推进到唯一后继状态。"""

        if self._pending_high_surrogate is not None:
            raise AnswerDeltaParseError("answer JSON string ended with an unmatched high surrogate")
        role = self._string_role
        value = "".join(self._string_buffer)
        self._in_string = False
        self._string_role = None
        self._string_buffer = []
        if role == "key":
            frame = self._frames[-1]
            if frame.kind != "object" or frame.state not in {"key_or_end", "key"}:
                raise AnswerDeltaParseError("answer JSON key appeared outside an object")
            frame.pending_key = value
            frame.state = "colon"
            return
        if self._string_is_target:
            self._target_count += 1
        self._string_is_target = False
        self._complete_value()

    def _complete_primitive(self) -> None:
        """用标准 JSON decoder 校验 primitive token，再完成父级 value。"""

        import json

        token = self._primitive
        self._primitive = ""
        try:
            decoded = json.loads(token)
        except json.JSONDecodeError as exc:
            raise AnswerDeltaParseError("answer JSON contains an invalid primitive") from exc
        if isinstance(decoded, (dict, list, str)):
            raise AnswerDeltaParseError("answer JSON primitive parser received a compound value")
        self._complete_value()

    def _current_value_path(self) -> tuple[_JsonPathPart, ...]:
        """从父容器状态确定当前值路径，不通过字段文本猜测层级。"""

        if not self._frames:
            return ()
        frame = self._frames[-1]
        if frame.kind == "object":
            if frame.state != "value" or frame.pending_key is None:
                raise AnswerDeltaParseError("answer JSON object is not ready for a value")
            return (*frame.path, frame.pending_key)
        if frame.state not in {"value_or_end", "value"}:
            raise AnswerDeltaParseError("answer JSON array is not ready for a value")
        return (*frame.path, frame.next_index)

    def _complete_value(self) -> None:
        """完成一个 scalar/container value，并更新 object key 或 array index。"""

        if not self._frames:
            if self._root_complete:
                raise AnswerDeltaParseError("answer JSON root completed more than once")
            self._root_complete = True
            return
        frame = self._frames[-1]
        if frame.kind == "object":
            if frame.state != "value":
                raise AnswerDeltaParseError("answer JSON object completed a value in the wrong state")
            frame.pending_key = None
            frame.state = "comma_or_end"
            return
        if frame.state not in {"value_or_end", "value"}:
            raise AnswerDeltaParseError("answer JSON array completed a value in the wrong state")
        frame.next_index += 1
        frame.state = "comma_or_end"


class QueryStreamAdapter:
    """把同次 Query 的 RuntimeEvent 与 normalized event 合并为单调 live stream。"""

    def __init__(self, handler: QueryStreamEventHandler, *, trace_id: str | None = None) -> None:
        self._handler = handler
        self._trace_id = trace_id
        self._sequence = 0
        self._answer_parser = AnswerArtifactDeltaParser()
        self._saw_content_delta = False
        self._turn_had_tool = False
        self._pending_answer_fragments: list[str] = []
        # Thinking 生命周期由 adapter 显式跟踪，确保每个模型回合形成独立过程段。
        self._thinking_active = False

    def handle_runtime_event(self, event: RuntimeEvent) -> None:
        """投影 reasoning/content/usage；persistent Trace mapper仍独立忽略 token delta。"""

        if event.type == "turn_started":
            # 每个模型 turn 拥有独立输出文档；Tool round 的 provisional output 不能污染最终 JSON parser。
            self._answer_parser = AnswerArtifactDeltaParser()
            self._saw_content_delta = False
            self._turn_had_tool = False
            self._pending_answer_fragments = []
            self._start_thinking(event.sequence)
            return
        if event.type in {"tool_started", "tool_completed"}:
            # 模型在发起 Tool 前可能先输出说明文字；这些不是最终答案，先标记后统一丢弃。
            self._complete_thinking(event.sequence)
            self._turn_had_tool = True
            if event.type == "tool_completed" and event.tool_result is not None:
                self._emit(
                    "tool.completed",
                    tool_name=event.tool_name,
                    tool_call_id=event.tool_call_id,
                    result_detail=project_tool_result_detail(event.tool_result),
                    source_sequence=event.sequence,
                )
            return
        if event.type == "thinking_delta":
            if event.text:
                self._start_thinking(event.sequence)
                self._emit(
                    "thinking.delta",
                    content=event.text,
                    thinking_visibility="public_summary",
                    source_sequence=event.sequence,
                )
            return
        if event.type == "thinking_completed":
            self._complete_thinking(event.sequence)
            return
        if event.type == "content_delta":
            if not event.text:
                return
            self._complete_thinking(event.sequence)
            self._saw_content_delta = True
            content = self._answer_parser.feed(event.text)
            if content:
                # 只有确认本 turn 没有 Tool 后才把正文交给 CLI；避免把模型中间叙述当成答案。
                self._pending_answer_fragments.append(content)
            return
        if event.type == "turn_completed":
            self._complete_thinking(event.sequence)
            self._flush_answer_turn(event.sequence)
            return
        if event.type == "usage_update" and event.usage:
            self._emit("usage.updated", usage=dict(event.usage), source_sequence=event.sequence)
            return
        if event.type in {"completed", "failed", "aborted"}:
            self._complete_thinking(event.sequence)
            if event.type == "completed" and self._saw_content_delta:
                self._answer_parser.finish()
                # SDK-independent injected runtimes may omit turn_completed；terminal boundary仍需 flush。
                self._flush_answer_turn(event.sequence)

    def _start_thinking(self, source_sequence: int) -> None:
        """在真实模型回合或公开摘要到达时只开启一个过程段。"""

        if self._thinking_active:
            return
        self._thinking_active = True
        self._emit("thinking.started", source_sequence=source_sequence)

    def _complete_thinking(self, source_sequence: int) -> None:
        """在 Tool、正文或终止边界关闭当前段，避免跨阶段粘连。"""

        if not self._thinking_active:
            return
        self._thinking_active = False
        self._emit("thinking.completed", source_sequence=source_sequence)

    def _flush_answer_turn(self, source_sequence: int) -> None:
        """只提交无 Tool turn 的正文；带 Tool 的模型说明保持在 provisional 边界内。"""

        fragments = self._pending_answer_fragments
        self._pending_answer_fragments = []
        if self._turn_had_tool:
            return
        for fragment in fragments:
            self._emit("answer.delta", content=fragment, source_sequence=source_sequence)

    def handle_normalized_event(self, event: NormalizedQueryEvent) -> None:
        """只映射已有真实业务边界；未知 operation 不产生伪造状态。"""

        self._trace_id = event.trace_id
        metadata = self._metadata(event)
        common: dict[str, object] = {
            "trace_id": event.trace_id,
            "duration_ms": event.duration_ms,
            "source_operation": event.operation,
            "source_sequence": event.sequence,
            "parent_operation_id": event.parent_operation_id,
            "metadata": metadata,
        }
        payload = event.payload
        if event.operation == "query.received":
            self._emit("query.started", **common)
        elif event.operation == "router.decision":
            self._emit("route.completed", route=self._text(payload.get("route")), **common)
        elif event.operation == "planner.completed":
            self._emit("plan.completed", plan=dict(payload), **common)
        elif event.operation == "planner.failed":
            self._emit_failure("plan.failed", event, common)
        elif event.operation == "tool.call.started":
            # normalized event 是跨 Runtime 的第二个事实来源，补记当前 turn 的 Tool 边界。
            self._complete_thinking(event.sequence)
            self._turn_had_tool = True
            request = payload.get("request")
            self._emit(
                "tool.started",
                tool_name=self._text(payload.get("tool_name")),
                tool_call_id=event.operation_id,
                arguments=dict(request) if isinstance(request, Mapping) else None,
                **common,
            )
        elif event.operation in {"tool.call.completed", "tool.call.failed"}:
            event_type: QueryStreamEventType = (
                "tool.failed" if event.operation.endswith("failed") else "tool.completed"
            )
            summary = {
                key: payload[key]
                for key in ("status", "error_code")
                if key in payload and payload[key] is not None
            }
            self._emit(
                event_type,
                tool_name=self._text(payload.get("tool_name")),
                tool_call_id=event.operation_id,
                result_summary=summary,
                error_code=self._failure_code(event),
                **common,
            )
        elif event.operation == "retrieval.search.started":
            query = payload.get("query")
            self._emit(
                "retrieval.started",
                tool_call_id=event.parent_operation_id,
                arguments=dict(query) if isinstance(query, Mapping) else None,
                **common,
            )
        elif event.operation == "retrieval.search.completed":
            expansion = payload.get("context_expansion")
            expanded_count = expansion.get("expanded_count") if isinstance(expansion, Mapping) else None
            summary = {
                key: payload[key]
                for key in (
                    "candidate_count",
                    "total_hits",
                    "returned_messages",
                    "coverage",
                    "partial",
                    "truncated",
                    "latency_ms",
                    "query",
                )
                if key in payload
            }
            if expanded_count is not None:
                summary["expanded_count"] = expanded_count
            self._emit(
                "retrieval.completed",
                tool_call_id=event.parent_operation_id,
                result_summary=summary,
                **common,
            )
        elif event.operation in {"retrieval.search.failed", "retrieval.search.skipped"}:
            self._emit_failure(
                "retrieval.failed",
                event,
                {**common, "tool_call_id": event.parent_operation_id},
            )
        elif event.operation == "answer.finalization.completed":
            self._complete_thinking(event.sequence)
            self._emit("answer.completed", content=self._text(payload.get("answer_text")), **common)
        elif event.operation in {"query.completed", "query.failed", "query.aborted"}:
            self._complete_thinking(event.sequence)
            terminal_type = cast(
                QueryStreamEventType,
                {
                    "query.completed": "query.completed",
                    "query.failed": "query.failed",
                    "query.aborted": "query.aborted",
                }[event.operation],
            )
            if terminal_type == "query.completed":
                self._emit(terminal_type, **common)
            else:
                self._emit_failure(terminal_type, event, common)

    def _emit_failure(
        self,
        event_type: QueryStreamEventType,
        event: NormalizedQueryEvent,
        common: Mapping[str, object],
    ) -> None:
        """统一从 normalized FailureInfo/payload 读取稳定错误码。"""

        self._emit(
            event_type,
            error_code=self._failure_code(event),
            error_message=self._text(event.payload.get("error_message")),
            **common,
        )

    def _emit(self, event_type: QueryStreamEventType, **kwargs: object) -> None:
        """由单一 writer 分配 query-scope sequence，再同步通知当前 consumer。"""

        self._sequence += 1
        values = {"type": event_type, "sequence": self._sequence, **kwargs}
        self._handler(QueryStreamEvent(**cast(Any, values)))

    @staticmethod
    def _failure_code(event: NormalizedQueryEvent) -> str | None:
        """FailureInfo 是首选 owner；无 FailureInfo 时只读显式 payload error_code。"""

        if event.failure is not None:
            return event.failure.error_code
        return QueryStreamAdapter._text(event.payload.get("error_code"))

    @staticmethod
    def _text(value: object) -> str | None:
        """只接受 normalized boundary 已给出的非空字符串，不做业务猜测。"""

        return value if isinstance(value, str) and value else None

    @staticmethod
    def _metadata(event: NormalizedQueryEvent) -> dict[str, object]:
        """提供 verbose 所需的 bounded normalized metadata，不传 raw SDK object。"""

        metadata: dict[str, object] = {
            "stage": event.stage,
            "phase": event.phase,
            "operation_id": event.operation_id,
            "limitations": event.limitations,
        }
        if event.parent_operation_id is not None:
            metadata["parent_operation_id"] = event.parent_operation_id
        if event.outcome is not None:
            metadata["outcome"] = event.outcome
        # Route/Planner 的结构化诊断只复制已 capture 的普通值，不把 raw SDK payload 带进实时接口。
        for key in (
            "source",
            "confidence",
            "reason",
            "provider",
            "model",
            "completion_request",
            "planner_latency_ms",
            "provider_latency_ms",
            "finish_reason",
            "usage",
            "output_tokens",
            "response_length",
            "parse_stage",
            "failure_detail_code",
            "diagnostic",
            # finalization 诊断沿用 normalized payload，避免 CLI 直接解析 raw event。
            "finalization_status",
            "user_answer_preserved",
            "error_code",
            "error_path",
            "degradation_codes",
            "dropped_field_count",
            "dropped_field_paths",
            "dropped_citation_count",
            "normalization_count",
            "validated_citation_count",
        ):
            if key in event.payload:
                metadata[key] = event.payload[key]
        return metadata
