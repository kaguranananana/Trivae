"""Evidence、Citation 与 Answer Finalization 的 Trivae-owned contract。

本模块只保存 bounded 的业务投影，不保存 SDK raw item、SQLite connection 或原始数据库转储。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping, TypeAlias

from trivae.capabilities.contracts import ExecutionScope, ToolEnvelope
from trivae.retrieval.structured import (
    Coverage,
    MessageProjection,
    RetrievalResult,
    StructuredAggregateResult,
    StructuredMessageResult,
)

SourceRelation = Literal["supports", "contradicts", "context"]
EvidenceSufficiency = Literal["sufficient", "partial", "insufficient"]
StructuredLocatorKind = Literal["scalar", "row", "field", "aggregate"]
ToolResultStatus = Literal["ok", "partial", "error"]

# 这些是第一版可校准的保守上限；超限输入显式失败，不把无界 payload 带入答案。
MAX_CONTENT_BLOCKS = 40
MAX_EVIDENCE_ITEMS = 20
MAX_SOURCES_PER_EVIDENCE = 20
MAX_CITATION_BINDINGS = 40
MAX_LIMITATIONS = 20
MAX_FIELD_CHARS = 4_000
MAX_ANSWER_CHARS = 20_000
MAX_SAFE_EXCERPT_CHARS = 1_000
MAX_DISPLAY_CHARS = 200
MAX_TOOL_RESULT_ITEMS = 100
MAX_VALUE_NESTING = 6


class AnswerContractError(ValueError):
    """Answer/Evidence 领域 contract 无效。"""


class AnswerFinalizationError(AnswerContractError):
    """模型输出无法通过确定性 finalization。"""

    def __init__(self, code: str, message: str, path: str | None = None) -> None:
        # 只保留稳定错误码、静态消息和字段路径，避免把模型正文或 provider payload 带入诊断。
        self.code = code
        self.message = message
        self.path = path
        super().__init__(message)


@dataclass(frozen=True)
class FinalizationErrorInfo:
    """Query 对外暴露的 secret-safe finalization failure。"""

    code: str
    message: str
    path: str | None = None


def _text(name: str, value: object, *, max_chars: int = MAX_FIELD_CHARS) -> str:
    """校验 bounded 文本；所有模型生成的文本都先经过这一条入口。"""

    if not isinstance(value, str) or not value.strip():
        raise AnswerContractError(f"{name} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_chars:
        raise AnswerContractError(f"{name} exceeds {max_chars} characters")
    return normalized


def _optional_text(name: str, value: object, *, max_chars: int = MAX_FIELD_CHARS) -> str | None:
    """允许 canonical projection 中确实不存在的可选显示字段。"""

    if value is None:
        return None
    return _text(name, value, max_chars=max_chars)


def _limitations(name: str, values: tuple[str, ...], maximum: int = MAX_LIMITATIONS) -> tuple[str, ...]:
    """统一校验限制项数量和文本长度，避免错误信息本身无界增长。"""

    if not isinstance(values, tuple):
        raise AnswerContractError(f"{name} must be a tuple")
    if len(values) > maximum:
        raise AnswerContractError(f"{name} exceeds {maximum} items")
    return tuple(_text(f"{name}[{index}]", value) for index, value in enumerate(values))


def _check_bounded_value(name: str, value: object, *, depth: int = 0) -> None:
    """校验 structured value 只能由 bounded JSON-like 值组成。"""

    if depth > MAX_VALUE_NESTING:
        raise AnswerContractError(f"{name} exceeds {MAX_VALUE_NESTING} nesting levels")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AnswerContractError(f"{name} must contain finite numbers")
        return
    if isinstance(value, str):
        if len(value) > MAX_FIELD_CHARS:
            raise AnswerContractError(f"{name} contains oversized text")
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_TOOL_RESULT_ITEMS:
            raise AnswerContractError(f"{name} contains too many object fields")
        for key, nested in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise AnswerContractError(f"{name} contains an invalid object key")
            _check_bounded_value(f"{name}.{key}", nested, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_TOOL_RESULT_ITEMS:
            raise AnswerContractError(f"{name} contains too many array items")
        for index, nested in enumerate(value):
            _check_bounded_value(f"{name}[{index}]", nested, depth=depth + 1)
        return
    raise AnswerContractError(f"{name} contains an unsupported value type")


def scope_snapshot(scope: ExecutionScope) -> dict[str, object]:
    """将 trusted scope 转成可比较的普通快照，不把 scope 对象泄漏到 Answer Artifact。"""

    return {
        "allowed_session_ids": scope.allowed_session_ids,
        "start_timestamp": scope.start_timestamp,
        "end_timestamp": scope.end_timestamp,
        "max_results": scope.max_results,
    }


@dataclass(frozen=True)
class MessageDisplaySnapshot:
    """由可信 Canonical projection hydrate 的人工复核信息。"""

    session_display: str
    author_display: str | None
    timestamp_ms: int
    timezone: str
    excerpt: str
    excerpt_truncated: bool
    source_message_id: str | None

    def __post_init__(self) -> None:
        # session display、timezone 和 excerpt 都来自 trusted projection，仍需限制长度。
        object.__setattr__(self, "session_display", _text("session_display", self.session_display, max_chars=MAX_DISPLAY_CHARS))
        object.__setattr__(self, "author_display", _optional_text("author_display", self.author_display, max_chars=MAX_DISPLAY_CHARS))
        if isinstance(self.timestamp_ms, bool) or not isinstance(self.timestamp_ms, int):
            raise AnswerContractError("timestamp_ms must be an integer")
        object.__setattr__(self, "timezone", _text("timezone", self.timezone, max_chars=64))
        object.__setattr__(self, "excerpt", _text("excerpt", self.excerpt, max_chars=MAX_SAFE_EXCERPT_CHARS))
        if not isinstance(self.excerpt_truncated, bool):
            raise AnswerContractError("excerpt_truncated must be a boolean")
        object.__setattr__(
            self,
            "source_message_id",
            _optional_text("source_message_id", self.source_message_id, max_chars=512),
        )


@dataclass(frozen=True)
class MessageSource:
    """Message citation 的模型 locator 与 finalizer 生成的 trusted snapshot。"""

    run_id: str
    tool_call_id: str
    tool_result_id: str
    result_item_id: str
    session_id: str
    internal_message_id: str
    snapshot: MessageDisplaySnapshot | None = None

    def __post_init__(self) -> None:
        # 模型只能提出这些稳定 locator；snapshot 会在 finalizer 中被 trusted projection 覆盖。
        for name in (
            "run_id",
            "tool_call_id",
            "tool_result_id",
            "result_item_id",
            "session_id",
            "internal_message_id",
        ):
            object.__setattr__(self, name, _text(name, getattr(self, name), max_chars=512))
        if self.snapshot is not None and not isinstance(self.snapshot, MessageDisplaySnapshot):
            raise AnswerContractError("snapshot must be a MessageDisplaySnapshot")


@dataclass(frozen=True)
class StructuredSource:
    """Structured Result citation；不允许把统计值伪装成 Message Source。"""

    run_id: str
    tool_call_id: str
    tool_result_id: str
    locator_kind: StructuredLocatorKind
    locator: str
    value_snapshot: object
    query_scope_snapshot: Mapping[str, object] | None = None
    execution_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # locator/value 是模型提出的候选，finalizer 会按 tool result 的可信值重新 hydrate。
        for name in ("run_id", "tool_call_id", "tool_result_id", "locator"):
            object.__setattr__(self, name, _text(name, getattr(self, name), max_chars=512))
        if self.locator_kind not in ("scalar", "row", "field", "aggregate"):
            raise AnswerContractError("locator_kind must be scalar, row, field, or aggregate")
        if self.query_scope_snapshot is not None and not isinstance(self.query_scope_snapshot, Mapping):
            raise AnswerContractError("query_scope_snapshot must be a mapping")
        _check_bounded_value("value_snapshot", self.value_snapshot)
        if self.query_scope_snapshot is not None:
            _check_bounded_value("query_scope_snapshot", self.query_scope_snapshot)
        object.__setattr__(
            self,
            "execution_limitations",
            _limitations("execution_limitations", self.execution_limitations),
        )


SourceReference: TypeAlias = MessageSource | StructuredSource


@dataclass(frozen=True)
class EvidenceSource:
    """一个 source 相对当前 finding 的关系。"""

    relation: SourceRelation
    reference: SourceReference

    def __post_init__(self) -> None:
        # relation 属于 Evidence 语义，不能复用 Retrieval 的 included/excluded 状态。
        if self.relation not in ("supports", "contradicts", "context"):
            raise AnswerContractError("relation must be supports, contradicts, or context")
        if not isinstance(self.reference, (MessageSource, StructuredSource)):
            raise AnswerContractError("reference must be MessageSource or StructuredSource")


@dataclass(frozen=True)
class EvidenceItem:
    """按 finding/criterion 组织的 Evidence，而不是一条消息一个 Evidence。"""

    evidence_id: str
    finding: str
    criterion: str
    sufficiency: EvidenceSufficiency
    sources: tuple[EvidenceSource, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _text("evidence_id", self.evidence_id, max_chars=256))
        object.__setattr__(self, "finding", _text("finding", self.finding))
        object.__setattr__(self, "criterion", _text("criterion", self.criterion))
        if self.sufficiency not in ("sufficient", "partial", "insufficient"):
            raise AnswerContractError("sufficiency must be sufficient, partial, or insufficient")
        if not isinstance(self.sources, tuple):
            raise AnswerContractError("sources must be a tuple")
        if len(self.sources) > MAX_SOURCES_PER_EVIDENCE:
            raise AnswerContractError(f"sources exceeds {MAX_SOURCES_PER_EVIDENCE} items")
        if any(not isinstance(source, EvidenceSource) for source in self.sources):
            raise AnswerContractError("sources must contain EvidenceSource values")
        object.__setattr__(self, "limitations", _limitations("limitations", self.limitations))


@dataclass(frozen=True)
class AnswerContentBlock:
    """可被 renderer 独立标记的回答内容块。"""

    block_id: str
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "block_id", _text("block_id", self.block_id, max_chars=256))
        object.__setattr__(self, "text", _text("content block text", self.text))


@dataclass(frozen=True)
class CitationBinding:
    """Answer content block 到一个或多个 Evidence Item 的结构化绑定。"""

    content_block_id: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_block_id", _text("content_block_id", self.content_block_id, max_chars=256))
        if not isinstance(self.evidence_ids, tuple) or not self.evidence_ids:
            raise AnswerContractError("evidence_ids must be a non-empty tuple")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise AnswerContractError("evidence_ids must not contain duplicates")
        object.__setattr__(
            self,
            "evidence_ids",
            tuple(_text(f"evidence_ids[{index}]", value, max_chars=256) for index, value in enumerate(self.evidence_ids)),
        )


@dataclass(frozen=True)
class AnswerArtifact:
    """最终对外暴露的结构化回答事实载体。"""

    content_blocks: tuple[AnswerContentBlock, ...]
    citation_bindings: tuple[CitationBinding, ...] = ()
    evidence_items: tuple[EvidenceItem, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # 先验证内容块 identity，后续 citation 才能确定性地指向一个内容单元。
        if not isinstance(self.content_blocks, tuple) or not self.content_blocks:
            raise AnswerContractError("content_blocks must be a non-empty tuple")
        if len(self.content_blocks) > MAX_CONTENT_BLOCKS:
            raise AnswerContractError(f"content_blocks exceeds {MAX_CONTENT_BLOCKS} items")
        if any(not isinstance(block, AnswerContentBlock) for block in self.content_blocks):
            raise AnswerContractError("content_blocks must contain AnswerContentBlock values")
        block_ids = tuple(block.block_id for block in self.content_blocks)
        if len(set(block_ids)) != len(block_ids):
            raise AnswerContractError("content block IDs must be unique")

        # Evidence ID 必须在 Artifact 内唯一，避免 renderer 和 validator 对同一 ID 产生歧义。
        if not isinstance(self.evidence_items, tuple):
            raise AnswerContractError("evidence_items must be a tuple")
        if len(self.evidence_items) > MAX_EVIDENCE_ITEMS:
            raise AnswerContractError(f"evidence_items exceeds {MAX_EVIDENCE_ITEMS} items")
        if any(not isinstance(item, EvidenceItem) for item in self.evidence_items):
            raise AnswerContractError("evidence_items must contain EvidenceItem values")
        evidence_ids = tuple(item.evidence_id for item in self.evidence_items)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise AnswerContractError("evidence IDs must be unique")

        # binding 的目标 content block 和 evidence ID 都必须在同一个 artifact 中存在。
        if not isinstance(self.citation_bindings, tuple):
            raise AnswerContractError("citation_bindings must be a tuple")
        if len(self.citation_bindings) > MAX_CITATION_BINDINGS:
            raise AnswerContractError(f"citation_bindings exceeds {MAX_CITATION_BINDINGS} items")
        if any(not isinstance(binding, CitationBinding) for binding in self.citation_bindings):
            raise AnswerContractError("citation_bindings must contain CitationBinding values")
        binding_blocks = [binding.content_block_id for binding in self.citation_bindings]
        if len(set(binding_blocks)) != len(binding_blocks):
            raise AnswerContractError("each content block may have only one citation binding")
        for binding in self.citation_bindings:
            if binding.content_block_id not in block_ids:
                raise AnswerContractError("citation binding references an unknown content block")
            if any(evidence_id not in evidence_ids for evidence_id in binding.evidence_ids):
                raise AnswerContractError("citation binding references an unknown evidence ID")

        object.__setattr__(self, "limitations", _limitations("answer limitations", self.limitations))
        if len(self.answer_text) > MAX_ANSWER_CHARS:
            raise AnswerContractError(f"answer content exceeds {MAX_ANSWER_CHARS} characters")

    @property
    def answer_text(self) -> str:
        """为 CLI 等纯文本消费者提供内容投影；citation identity 仍保留在结构字段中。"""

        return "\n\n".join(block.text for block in self.content_blocks)


@dataclass(frozen=True)
class ToolMessageItem:
    """Tool Result 中一个可引用的 bounded canonical message projection。"""

    result_item_id: str
    message: MessageProjection
    content_truncated: bool = False

    def __post_init__(self) -> None:
        # Tool Result 只保留有界 canonical projection；过长正文必须在建 record 时显式截断。
        object.__setattr__(self, "result_item_id", _text("result_item_id", self.result_item_id, max_chars=512))
        if not isinstance(self.message, MessageProjection):
            raise AnswerContractError("message must be a MessageProjection")
        if not isinstance(self.message.normalized_content, str):
            raise AnswerContractError("message normalized_content must be text")
        if len(self.message.normalized_content) > MAX_SAFE_EXCERPT_CHARS:
            raise AnswerContractError("tool message content must be bounded")
        if not isinstance(self.content_truncated, bool):
            raise AnswerContractError("content_truncated must be a boolean")


@dataclass(frozen=True)
class ToolStructuredItem:
    """Tool Result 中一个可引用的 structured locator/value projection。"""

    locator_kind: StructuredLocatorKind
    locator: str
    value_snapshot: object

    def __post_init__(self) -> None:
        object.__setattr__(self, "locator", _text("structured locator", self.locator, max_chars=512))
        if self.locator_kind not in ("scalar", "row", "field", "aggregate"):
            raise AnswerContractError("structured locator kind is invalid")
        _check_bounded_value("structured value_snapshot", self.value_snapshot)


@dataclass(frozen=True)
class ToolResultRecord:
    """当前 Run 取得的一个 Tool Result 的最小 provenance 和 bounded 内容。"""

    run_id: str
    tool_call_id: str
    tool_result_id: str
    tool_name: str
    status: ToolResultStatus
    scope_snapshot: Mapping[str, object]
    query_scope_snapshot: Mapping[str, object]
    message_items: tuple[ToolMessageItem, ...] = ()
    structured_items: tuple[ToolStructuredItem, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # identity 是 finalizer 建索引的主键，重复 identity 必须在 record 边界暴露。
        for name in ("run_id", "tool_call_id", "tool_result_id", "tool_name"):
            object.__setattr__(self, name, _text(name, getattr(self, name), max_chars=512))
        if self.status not in ("ok", "partial", "error"):
            raise AnswerContractError("tool result status is invalid")
        if not isinstance(self.scope_snapshot, Mapping) or not isinstance(self.query_scope_snapshot, Mapping):
            raise AnswerContractError("tool result scope snapshots must be mappings")
        _check_bounded_value("scope_snapshot", self.scope_snapshot)
        _check_bounded_value("query_scope_snapshot", self.query_scope_snapshot)
        if not isinstance(self.message_items, tuple) or not isinstance(self.structured_items, tuple):
            raise AnswerContractError("tool result items must be tuples")
        if any(not isinstance(item, ToolMessageItem) for item in self.message_items):
            raise AnswerContractError("message_items must contain ToolMessageItem values")
        if any(not isinstance(item, ToolStructuredItem) for item in self.structured_items):
            raise AnswerContractError("structured_items must contain ToolStructuredItem values")
        if len(self.message_items) + len(self.structured_items) > MAX_TOOL_RESULT_ITEMS:
            raise AnswerContractError(f"tool result items exceeds {MAX_TOOL_RESULT_ITEMS}")
        if self.status == "error" and (self.message_items or self.structured_items):
            raise AnswerContractError("error tool results cannot contain source items")
        message_ids = [item.result_item_id for item in self.message_items]
        if len(set(message_ids)) != len(message_ids):
            raise AnswerContractError("tool result message item IDs must be unique")
        structured_ids = [(item.locator_kind, item.locator) for item in self.structured_items]
        if len(set(structured_ids)) != len(structured_ids):
            raise AnswerContractError("tool result structured locators must be unique")
        object.__setattr__(self, "limitations", _limitations("tool result limitations", self.limitations))

    def to_model_provenance(self) -> dict[str, object]:
        """只向模型暴露 source locator，不暴露 trusted snapshot 或 scope 对象。"""

        return {
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool_result_id": self.tool_result_id,
            "message_sources": [
                {
                    "type": "message",
                    # 每个 entry 都携带完整父级 identity，避免模型从多个 Tool Result 拼接 locator。
                    "run_id": self.run_id,
                    "tool_call_id": self.tool_call_id,
                    "tool_result_id": self.tool_result_id,
                    "result_item_id": item.result_item_id,
                    "session_id": item.message.session_id,
                    "internal_message_id": item.message.internal_message_id,
                }
                for item in self.message_items
            ],
            "structured_sources": [
                {
                    "type": "structured",
                    # structured source 同样使用自包含 locator，保持两类 provenance 的投影规则一致。
                    "run_id": self.run_id,
                    "tool_call_id": self.tool_call_id,
                    "tool_result_id": self.tool_result_id,
                    "locator_kind": item.locator_kind,
                    "locator": item.locator,
                    "value_snapshot": item.value_snapshot,
                }
                for item in self.structured_items
            ],
        }


def _message_items(messages: tuple[MessageProjection, ...]) -> tuple[ToolMessageItem, ...]:
    """按 internal message identity 去重，保留 Tool Result 中第一次出现的顺序。"""

    items: list[ToolMessageItem] = []
    seen: set[str] = set()
    for message in messages:
        if message.internal_message_id in seen:
            continue
        seen.add(message.internal_message_id)
        content = message.normalized_content
        if len(content) > MAX_SAFE_EXCERPT_CHARS:
            # Record 内只留可供人工复核的 bounded excerpt，并用标记保留“发生过截断”的事实。
            bounded_message = replace(message, normalized_content=content[: MAX_SAFE_EXCERPT_CHARS - 1] + "…")
            items.append(ToolMessageItem(f"message/{message.internal_message_id}", bounded_message, True))
        else:
            items.append(ToolMessageItem(f"message/{message.internal_message_id}", message))
    return tuple(items)


def _retrieval_limitations(status: ToolResultStatus, data: object | None, error_code: str | None) -> tuple[str, ...]:
    """把 Tool/execution completeness 保留为限制，不折叠为 Evidence sufficiency。"""

    limitations: list[str] = []
    if status == "partial":
        limitations.append("tool_result_partial")
    if status == "error" and error_code:
        limitations.append(f"tool_error:{error_code}")
    if data is not None:
        partial = bool(getattr(data, "partial", False))
        truncated = bool(getattr(data, "truncated", False))
        coverage = getattr(data, "coverage", None)
        if partial:
            limitations.append("retrieval_partial")
        if truncated:
            limitations.append("retrieval_truncated")
        if isinstance(coverage, Coverage) and coverage.status != "complete":
            limitations.append(f"coverage:{coverage.status}")
    return tuple(limitations)


def build_tool_result_record(
    *,
    run_id: str,
    tool_call_id: str,
    tool_result_id: str,
    tool_name: str,
    envelope: ToolEnvelope,
    scope: ExecutionScope,
) -> ToolResultRecord:
    """把既有 ToolEnvelope 转换为 bounded current-run provenance record。"""

    data = envelope.data
    message_items: tuple[ToolMessageItem, ...] = ()
    structured_items: tuple[ToolStructuredItem, ...] = ()
    query_snapshot: Mapping[str, object] = {}

    if isinstance(data, RetrievalResult):
        # hits 和 expanded context 都是当前 Tool Result 的可见候选；finalizer 仍会重新做 scope 校验。
        messages = tuple(hit.message for hit in data.hits) + data.expanded_messages
        message_items = _message_items(messages)
        query_snapshot = data.query.to_dict()
    elif isinstance(data, StructuredMessageResult):
        message_items = _message_items(data.messages)
        query_snapshot = data.query.to_dict()
    elif isinstance(data, StructuredAggregateResult):
        query_snapshot = data.query.to_dict()
        structured_items = _aggregate_items(data)

    error_code = envelope.error.code if envelope.error is not None else None
    return ToolResultRecord(
        run_id=run_id,
        tool_call_id=tool_call_id,
        tool_result_id=tool_result_id,
        tool_name=tool_name,
        status=envelope.status,
        scope_snapshot=scope_snapshot(scope),
        query_scope_snapshot=query_snapshot,
        message_items=message_items,
        structured_items=structured_items,
        limitations=_retrieval_limitations(envelope.status, data, error_code),
    )


def _aggregate_items(result: StructuredAggregateResult) -> tuple[ToolStructuredItem, ...]:
    """为 aggregate 建立 aggregate/row/field 三类确定性 locator。"""

    items: list[ToolStructuredItem] = [
        ToolStructuredItem("aggregate", "total_count", result.total_count),
    ]
    for index, bucket in enumerate(result.buckets):
        row_locator = f"buckets[{index}]"
        row_value = {"group_key": bucket.group_key, "count": bucket.count}
        items.append(ToolStructuredItem("row", row_locator, row_value))
        items.append(ToolStructuredItem("field", f"{row_locator}.group_key", bucket.group_key))
        items.append(ToolStructuredItem("field", f"{row_locator}.count", bucket.count))
    return tuple(items)


def _model_error(code: str, message: str, path: str | None = None) -> AnswerFinalizationError:
    """把 parser/contract 错误统一成不含原始模型输出的 finalization failure。"""

    return AnswerFinalizationError(code, message, path)


def _payload_list(payload: Mapping[str, Any], name: str) -> list[Any]:
    """读取 structured output 数组并拒绝隐式字符串/映射转换。"""

    value = payload.get(name, [])
    if not isinstance(value, list):
        raise _model_error("INVALID_ANSWER_ARTIFACT", f"{name} must be an array", name)
    return value


def _parse_source(raw: object, path: str) -> SourceReference:
    """只解析模型提出的 locator/value；display metadata 不从模型输入构造。"""

    if not isinstance(raw, Mapping):
        raise _model_error("INVALID_SOURCE", "source must be an object", path)
    source_type = raw.get("type")
    try:
        if source_type == "message":
            return MessageSource(
                run_id=raw["run_id"],
                tool_call_id=raw["tool_call_id"],
                tool_result_id=raw["tool_result_id"],
                result_item_id=raw["result_item_id"],
                session_id=raw["session_id"],
                internal_message_id=raw["internal_message_id"],
            )
        if source_type == "structured":
            if "value_snapshot" not in raw:
                raise _model_error("INVALID_SOURCE", "structured source requires value_snapshot", path)
            return StructuredSource(
                run_id=raw["run_id"],
                tool_call_id=raw["tool_call_id"],
                tool_result_id=raw["tool_result_id"],
                locator_kind=raw["locator_kind"],
                locator=raw["locator"],
                value_snapshot=raw["value_snapshot"],
            )
    except KeyError as exc:
        raise _model_error("INVALID_SOURCE", "source is missing a required locator field", f"{path}.{exc.args[0]}") from exc
    except AnswerContractError as exc:
        raise _model_error("INVALID_SOURCE", str(exc), path) from exc
    raise _model_error("INVALID_SOURCE", "source type must be message or structured", f"{path}.type")


def _parse_candidate(payload: Mapping[str, Any]) -> AnswerArtifact:
    """将 JSON final synthesis 转成候选 Artifact，之后仍需 trusted finalization。"""

    content_blocks_raw = payload.get("content_blocks")
    if content_blocks_raw is None:
        # 允许一个简短 answer 字段作为结构化 contract 的单 block 形式。
        if "answer" not in payload:
            raise _model_error("INVALID_ANSWER_ARTIFACT", "answer artifact requires content_blocks or answer", "answer")
        content_blocks_raw = [{"block_id": "answer", "text": payload["answer"]}]
    if not isinstance(content_blocks_raw, list):
        raise _model_error("INVALID_ANSWER_ARTIFACT", "content_blocks must be an array", "content_blocks")
    blocks: list[AnswerContentBlock] = []
    for index, raw_block in enumerate(content_blocks_raw):
        if not isinstance(raw_block, Mapping):
            raise _model_error("INVALID_ANSWER_ARTIFACT", "content block must be an object", f"content_blocks[{index}]")
        try:
            blocks.append(AnswerContentBlock(raw_block["block_id"], raw_block["text"]))
        except KeyError as exc:
            raise _model_error("INVALID_ANSWER_ARTIFACT", "content block is missing a required field", f"content_blocks[{index}]") from exc
        except AnswerContractError as exc:
            raise _model_error("INVALID_ANSWER_ARTIFACT", str(exc), f"content_blocks[{index}]") from exc

    evidence: list[EvidenceItem] = []
    for index, raw_item in enumerate(_payload_list(payload, "evidence_items")):
        path = f"evidence_items[{index}]"
        if not isinstance(raw_item, Mapping):
            raise _model_error("INVALID_EVIDENCE", "evidence item must be an object", path)
        raw_sources = raw_item.get("sources", [])
        if not isinstance(raw_sources, list):
            raise _model_error("INVALID_EVIDENCE", "sources must be an array", f"{path}.sources")
        sources: list[EvidenceSource] = []
        for source_index, raw_evidence_source in enumerate(raw_sources):
            source_path = f"{path}.sources[{source_index}]"
            if not isinstance(raw_evidence_source, Mapping):
                raise _model_error("INVALID_SOURCE", "evidence source must be an object", source_path)
            try:
                relation = raw_evidence_source["relation"]
                reference = _parse_source(raw_evidence_source["source"], f"{source_path}.source")
                sources.append(EvidenceSource(relation, reference))
            except KeyError as exc:
                raise _model_error("INVALID_SOURCE", "evidence source is missing a required field", source_path) from exc
            except AnswerContractError as exc:
                raise _model_error("INVALID_SOURCE", str(exc), source_path) from exc
        try:
            raw_limitations = raw_item.get("limitations", [])
            if not isinstance(raw_limitations, list):
                raise _model_error("INVALID_EVIDENCE", "limitations must be an array", f"{path}.limitations")
            evidence.append(
                EvidenceItem(
                    evidence_id=raw_item["evidence_id"],
                    finding=raw_item["finding"],
                    criterion=raw_item["criterion"],
                    sufficiency=raw_item["sufficiency"],
                    sources=tuple(sources),
                    limitations=tuple(raw_limitations),
                )
            )
        except KeyError as exc:
            raise _model_error("INVALID_EVIDENCE", "evidence item is missing a required field", path) from exc
        except (AnswerContractError, TypeError) as exc:
            raise _model_error("INVALID_EVIDENCE", str(exc), path) from exc

    bindings: list[CitationBinding] = []
    for index, raw_binding in enumerate(_payload_list(payload, "citation_bindings")):
        path = f"citation_bindings[{index}]"
        if not isinstance(raw_binding, Mapping):
            raise _model_error("INVALID_CITATION_BINDING", "citation binding must be an object", path)
        try:
            raw_evidence_ids = raw_binding["evidence_ids"]
            if not isinstance(raw_evidence_ids, list):
                raise _model_error("INVALID_CITATION_BINDING", "evidence_ids must be an array", f"{path}.evidence_ids")
            bindings.append(
                CitationBinding(
                    content_block_id=raw_binding["content_block_id"],
                    evidence_ids=tuple(raw_evidence_ids),
                )
            )
        except KeyError as exc:
            raise _model_error("INVALID_CITATION_BINDING", "citation binding is missing a required field", path) from exc
        except (AnswerContractError, TypeError) as exc:
            raise _model_error("INVALID_CITATION_BINDING", str(exc), path) from exc

    raw_answer_limitations = payload.get("limitations", [])
    if not isinstance(raw_answer_limitations, list):
        raise _model_error("INVALID_ANSWER_ARTIFACT", "limitations must be an array", "limitations")
    try:
        return AnswerArtifact(
            content_blocks=tuple(blocks),
            citation_bindings=tuple(bindings),
            evidence_items=tuple(evidence),
            limitations=tuple(raw_answer_limitations),
        )
    except (AnswerContractError, TypeError) as exc:
        raise _model_error("INVALID_ANSWER_ARTIFACT", str(exc)) from exc


def parse_answer_output(output: str) -> AnswerArtifact:
    """解析模型 final synthesis；plain text 只能形成无 citation 的内容块。"""

    if not isinstance(output, str) or not output.strip():
        raise _model_error("INVALID_FINAL_OUTPUT", "final answer must be non-empty text")
    normalized = output.strip()
    try:
        decoded = json.loads(normalized)
    except json.JSONDecodeError as exc:
        # 结构化输出若以对象/数组/代码围栏开头却无法解析，必须失败，不能悄悄丢掉 citation。
        if normalized.startswith(("{", "[", "```")):
            raise _model_error("INVALID_ANSWER_ARTIFACT", "structured final answer is not valid JSON") from exc
        return AnswerArtifact(content_blocks=(AnswerContentBlock("answer", normalized),))
    if not isinstance(decoded, Mapping):
        raise _model_error("INVALID_ANSWER_ARTIFACT", "structured final answer must be an object")
    return _parse_candidate(decoded)


def _record_index(
    records: tuple[ToolResultRecord, ...],
    run_id: str,
    accepted_run_ids: tuple[str, ...] = (),
) -> dict[tuple[str, str], ToolResultRecord]:
    """只索引当前 run；accepted alias 仅兼容 M5 已持久化的旧 locator 前缀。"""

    indexed: dict[tuple[str, str], ToolResultRecord] = {}
    aliases = tuple(alias for alias in accepted_run_ids if alias and alias != run_id)
    for record in records:
        if record.run_id != run_id:
            continue
        keys = [(record.tool_call_id, record.tool_result_id)]
        for alias in aliases:
            alias_key = (
                _replace_identity_prefix(record.tool_call_id, run_id, alias),
                _replace_identity_prefix(record.tool_result_id, run_id, alias),
            )
            if alias_key not in keys:
                keys.append(alias_key)
        for key in keys:
            if key in indexed:
                raise _model_error("INVALID_PROVENANCE", "duplicate current-run tool result identity")
            indexed[key] = record
    return indexed


def _replace_identity_prefix(identity: str, actual: str, alias: str) -> str:
    """只替换 Trivae-owned identity 的完整前缀，避免模糊字符串替换。"""

    prefix = actual + "/"
    return alias + identity[len(actual) :] if identity.startswith(prefix) else identity


def _scope_allows_message(message: MessageProjection, scope: ExecutionScope) -> bool:
    """在 finalizer 再做一次 scope 检查，防止 context expansion 越过 trusted 时间范围。"""

    if scope.allowed_session_ids is not None and message.session_id not in scope.allowed_session_ids:
        return False
    if scope.start_timestamp is not None and message.timestamp < scope.start_timestamp:
        return False
    if scope.end_timestamp is not None and message.timestamp >= scope.end_timestamp:
        return False
    return True


def _hydrate_snapshot(message: MessageProjection, *, content_truncated: bool = False) -> MessageDisplaySnapshot:
    """从 canonical projection 生成 bounded snapshot；不使用模型提供的 author/time/session。"""

    if not message.session_display:
        raise _model_error("TRUSTED_METADATA_UNAVAILABLE", "canonical session display is unavailable")
    content = message.normalized_content
    truncated = content_truncated or len(content) > MAX_SAFE_EXCERPT_CHARS
    excerpt = content[: MAX_SAFE_EXCERPT_CHARS - 1] + "…" if truncated else content
    if not excerpt:
        raise _model_error("TRUSTED_METADATA_UNAVAILABLE", "canonical message excerpt is empty")
    author = message.sender_name or message.sender_user_id
    return MessageDisplaySnapshot(
        session_display=message.session_display,
        author_display=author,
        timestamp_ms=message.timestamp,
        timezone="UTC",
        excerpt=excerpt,
        excerpt_truncated=truncated,
        source_message_id=message.source_message_id,
    )


def _finalize_source(
    source: EvidenceSource,
    *,
    run_id: str,
    accepted_run_ids: tuple[str, ...],
    records: dict[tuple[str, str], ToolResultRecord],
    scope: ExecutionScope,
) -> EvidenceSource:
    """验证一个 source 的 provenance/locator/scope，并从可信 record hydrate metadata。"""

    reference = source.reference
    source_run_id = reference.run_id
    if source_run_id != run_id and source_run_id not in accepted_run_ids:
        raise _model_error("INVALID_PROVENANCE", "source does not belong to the current run")
    record = records.get((reference.tool_call_id, reference.tool_result_id))
    if record is None:
        raise _model_error("INVALID_PROVENANCE", "source tool result was not obtained in the current run")
    if record.scope_snapshot != scope_snapshot(scope):
        raise _model_error("SCOPE_VIOLATION", "source result scope does not match the current trusted scope")

    if isinstance(reference, MessageSource):
        item = next((item for item in record.message_items if item.result_item_id == reference.result_item_id), None)
        if item is None:
            raise _model_error("UNRESOLVED_MESSAGE_SOURCE", "message result item does not exist")
        message = item.message
        if message.session_id != reference.session_id or message.internal_message_id != reference.internal_message_id:
            raise _model_error("MESSAGE_SOURCE_MISMATCH", "message locator does not match the tool result")
        if not _scope_allows_message(message, scope):
            raise _model_error("SCOPE_VIOLATION", "message source is outside the trusted execution scope")
        return EvidenceSource(
            source.relation,
            replace(reference, snapshot=_hydrate_snapshot(message, content_truncated=item.content_truncated)),
        )

    structured_item = next(
        (
            item
            for item in record.structured_items
            if item.locator_kind == reference.locator_kind and item.locator == reference.locator
        ),
        None,
    )
    if structured_item is None:
        raise _model_error("UNRESOLVED_STRUCTURED_SOURCE", "structured locator does not exist")
    if structured_item.value_snapshot != reference.value_snapshot:
        raise _model_error("STRUCTURED_VALUE_MISMATCH", "structured source value does not match the tool result")
    return EvidenceSource(
        source.relation,
        replace(
            reference,
            value_snapshot=structured_item.value_snapshot,
            query_scope_snapshot=record.query_scope_snapshot,
            execution_limitations=record.limitations,
        ),
    )


def validate_answer_artifact(
    artifact: AnswerArtifact,
    *,
    run_id: str | None,
    tool_results: tuple[ToolResultRecord, ...],
    scope: ExecutionScope,
    accepted_run_ids: tuple[str, ...] = (),
) -> AnswerArtifact:
    """执行确定性 validation/hydration；不判断自然语言 claim 的语义蕴含。"""

    if not artifact.evidence_items:
        # 没有 Evidence 的普通回答不需要 current-run provenance，但仍已经是结构化 Artifact。
        return artifact
    if run_id is None or not run_id:
        raise _model_error("INVALID_PROVENANCE", "current run identity is unavailable")
    records = _record_index(tool_results, run_id, accepted_run_ids)
    finalized_items: list[EvidenceItem] = []
    for item in artifact.evidence_items:
        finalized_sources = tuple(
            _finalize_source(
                source,
                run_id=run_id,
                accepted_run_ids=accepted_run_ids,
                records=records,
                scope=scope,
            )
            for source in item.sources
        )
        finalized_items.append(replace(item, sources=finalized_sources))
    try:
        return replace(artifact, evidence_items=tuple(finalized_items))
    except AnswerContractError as exc:
        raise _model_error("INVALID_ANSWER_ARTIFACT", str(exc)) from exc


def finalize_answer(
    output: str,
    *,
    run_id: str | None,
    tool_results: tuple[ToolResultRecord, ...],
    scope: ExecutionScope,
    accepted_run_ids: tuple[str, ...] = (),
) -> AnswerArtifact:
    """完成“解析 → 结构校验 → provenance 校验 → trusted hydrate”的提交前流程。"""

    candidate = parse_answer_output(output)
    if tool_results and not output.strip().startswith("{"):
        # 只要本轮实际调用过工具，最终合成必须走结构化 contract；不能把 citation 丢成裸文本。
        raise _model_error(
            "INVALID_ANSWER_ARTIFACT",
            "final answer after tool execution must be a JSON object",
        )
    return validate_answer_artifact(
        candidate,
        run_id=run_id,
        tool_results=tool_results,
        scope=scope,
        accepted_run_ids=accepted_run_ids,
    )
