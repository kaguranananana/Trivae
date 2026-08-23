"""Query 真实执行事件到接口无关实时事件的薄投影。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from trivae.observability.contracts import NormalizedQueryEvent
from trivae.query.runtime.contracts import RuntimeEvent

QueryStreamEventType = Literal[
    "query.started",
    "route.completed",
    "plan.completed",
    "plan.failed",
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
    route: str | None = None
    plan: Mapping[str, object] | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    arguments: Mapping[str, object] | None = None
    result_summary: Mapping[str, object] | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: float | None = None
    usage: Mapping[str, int | float] | None = None
    source_operation: str | None = None
    source_sequence: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


QueryStreamEventHandler = Callable[[QueryStreamEvent], None]


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

    def handle_runtime_event(self, event: RuntimeEvent) -> None:
        """投影 reasoning/content/usage；persistent Trace mapper仍独立忽略 token delta。"""

        if event.type == "turn_started":
            # 每个模型 turn 拥有独立输出文档；Tool round 的 provisional output 不能污染最终 JSON parser。
            self._answer_parser = AnswerArtifactDeltaParser()
            self._saw_content_delta = False
            return
        if event.type == "thinking_delta":
            if event.text:
                self._emit("thinking.delta", content=event.text, source_sequence=event.sequence)
            return
        if event.type == "thinking_completed":
            self._emit("thinking.completed", source_sequence=event.sequence)
            return
        if event.type == "content_delta":
            if not event.text:
                return
            self._saw_content_delta = True
            content = self._answer_parser.feed(event.text)
            if content:
                self._emit("answer.delta", content=content, source_sequence=event.sequence)
            return
        if event.type == "usage_update" and event.usage:
            self._emit("usage.updated", usage=dict(event.usage), source_sequence=event.sequence)
            return
        if event.type == "completed" and self._saw_content_delta:
            self._answer_parser.finish()

    def handle_normalized_event(self, event: NormalizedQueryEvent) -> None:
        """只映射已有真实业务边界；未知 operation 不产生伪造状态。"""

        self._trace_id = event.trace_id
        metadata = self._metadata(event)
        common: dict[str, object] = {
            "trace_id": event.trace_id,
            "duration_ms": event.duration_ms,
            "source_operation": event.operation,
            "source_sequence": event.sequence,
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
                )
                if key in payload
            }
            if expanded_count is not None:
                summary["expanded_count"] = expanded_count
            self._emit("retrieval.completed", result_summary=summary, **common)
        elif event.operation in {"retrieval.search.failed", "retrieval.search.skipped"}:
            self._emit_failure("retrieval.failed", event, common)
        elif event.operation == "answer.finalization.completed":
            self._emit("answer.completed", content=self._text(payload.get("answer_text")), **common)
        elif event.operation in {"query.completed", "query.failed", "query.aborted"}:
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
        for key in ("source", "confidence", "reason"):
            if key in event.payload:
                metadata[key] = event.payload[key]
        return metadata
