"""Evidence、Citation 与 Answer Finalization 的 Trivae-owned contract。

本模块只保存 bounded 的业务投影，不保存 SDK raw item、SQLite connection 或原始数据库转储。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping, TypeAlias

from trivae.capabilities.contracts import ExecutionScope, ToolEnvelope
from trivae.config.limits import (
    DEFAULT_TOOL_RESULT_TOKEN_BUDGET,
    MAX_LEXICAL_RESULT_LIMIT,
    MAX_STRUCTURED_RESULT_ITEMS,
)
from trivae.retrieval.context import MessageContextResult
from trivae.retrieval.identity import FindMembersResult
from trivae.retrieval.semantic.contracts import SemanticRetrievalResult
from trivae.retrieval.sql import SchemaResult, SQLQueryResult
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
# message provenance 必须能承载 lexical hard cap；structured/value provenance 继续保持独立小边界。
MAX_TOOL_RESULT_MESSAGE_ITEMS = MAX_LEXICAL_RESULT_LIMIT
MAX_TOOL_RESULT_STRUCTURED_ITEMS = MAX_STRUCTURED_RESULT_ITEMS
MAX_VALUE_NESTING = 6
MAX_SOURCE_URLS = 12
MAX_SOURCE_URL_CHARS = 2_000
MAX_MODEL_MESSAGE_CHARS = 600
MODEL_TOKEN_CHAR_RATIO = 3

_URL_PATTERN = re.compile(r"https?://[^\s<>\"'，。；：！？、]+")
_URL_TRAILING_PUNCTUATION = ".,;:!?，。；：！？、)]}"
_MISSING_STRUCTURED_VALUE = object()


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


class SourceInspectionError(AnswerContractError):
    """来源查看无法在当前可信 scope 内完成时的显式错误。"""


class ToolResultProjectionError(AnswerContractError):
    """Canonical Tool Result 无法在独立模型预算内形成合法 projection。"""


@dataclass(frozen=True)
class FinalizationErrorInfo:
    """Query 对外暴露的 secret-safe finalization failure。"""

    code: str
    message: str
    path: str | None = None


FinalizationStatus = Literal["valid", "degraded", "failed"]
MAX_FINALIZATION_DIAGNOSTIC_ITEMS = 20


@dataclass(frozen=True)
class FinalizationDiagnostics:
    """最终化结果的 bounded、secret-safe 诊断，不复制模型原始输出。"""

    status: FinalizationStatus
    user_answer_preserved: bool
    error_code: str | None = None
    error_path: str | None = None
    degradation_codes: tuple[str, ...] = ()
    dropped_field_count: int = 0
    dropped_field_paths: tuple[str, ...] = ()
    dropped_citation_count: int = 0
    normalization_count: int = 0
    validated_citation_count: int = 0

    def __post_init__(self) -> None:
        """校验状态与计数，只允许有限的静态诊断字段进入 Trace/Evaluation。"""

        if self.status not in {"valid", "degraded", "failed"}:
            raise AnswerContractError("finalization status is invalid")
        if not isinstance(self.user_answer_preserved, bool):
            raise AnswerContractError("user_answer_preserved must be a boolean")
        object.__setattr__(self, "error_code", _optional_text("finalization error_code", self.error_code, max_chars=128))
        object.__setattr__(self, "error_path", _optional_text("finalization error_path", self.error_path, max_chars=256))
        object.__setattr__(
            self,
            "degradation_codes",
            _diagnostic_texts(self.degradation_codes, "degradation_codes", max_chars=128),
        )
        object.__setattr__(
            self,
            "dropped_field_paths",
            _diagnostic_texts(self.dropped_field_paths, "dropped_field_paths", max_chars=256),
        )
        for name in (
            "dropped_field_count",
            "dropped_citation_count",
            "normalization_count",
            "validated_citation_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AnswerContractError(f"{name} must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        """将诊断转换成可写入 Trace/Evaluation 的普通 bounded 字典。"""

        return {
            "status": self.status,
            "user_answer_preserved": self.user_answer_preserved,
            "error_code": self.error_code,
            "error_path": self.error_path,
            "degradation_codes": list(self.degradation_codes),
            "dropped_field_count": self.dropped_field_count,
            "dropped_field_paths": list(self.dropped_field_paths),
            "dropped_citation_count": self.dropped_citation_count,
            "normalization_count": self.normalization_count,
            "validated_citation_count": self.validated_citation_count,
        }


@dataclass(frozen=True)
class FinalizationResult:
    """最终化的 typed outcome：可提交 Artifact 或 secret-safe fatal error。"""

    artifact: AnswerArtifact | None
    diagnostics: FinalizationDiagnostics
    error: FinalizationErrorInfo | None = None

    def __post_init__(self) -> None:
        """保持 status、artifact、error 三者一致，避免调用方自行猜测边界。"""

        if not isinstance(self.diagnostics, FinalizationDiagnostics):
            raise AnswerContractError("finalization diagnostics are invalid")
        if self.diagnostics.status == "failed":
            if self.artifact is not None or self.error is None:
                raise AnswerContractError("failed finalization requires error and no artifact")
        elif self.artifact is None or self.error is not None:
            raise AnswerContractError("valid or degraded finalization requires an artifact and no error")


def _diagnostic_texts(values: tuple[str, ...], name: str, *, max_chars: int) -> tuple[str, ...]:
    """规范化有限诊断文本，避免错误路径本身造成无界增长。"""

    if not isinstance(values, tuple):
        raise AnswerContractError(f"{name} must be a tuple")
    if len(values) > MAX_FINALIZATION_DIAGNOSTIC_ITEMS:
        raise AnswerContractError(f"{name} exceeds {MAX_FINALIZATION_DIAGNOSTIC_ITEMS} items")
    normalized: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise AnswerContractError(f"{name}[{index}] must be a non-empty string")
        item = value.strip()
        if len(item) > max_chars:
            raise AnswerContractError(f"{name}[{index}] exceeds {max_chars} characters")
        if item not in normalized:
            normalized.append(item)
    return tuple(normalized)


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
        if len(value) > MAX_TOOL_RESULT_STRUCTURED_ITEMS:
            raise AnswerContractError(f"{name} contains too many object fields")
        for key, nested in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise AnswerContractError(f"{name} contains an invalid object key")
            _check_bounded_value(f"{name}.{key}", nested, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_TOOL_RESULT_STRUCTURED_ITEMS:
            raise AnswerContractError(f"{name} contains too many array items")
        for index, nested in enumerate(value):
            _check_bounded_value(f"{name}[{index}]", nested, depth=depth + 1)
        return
    raise AnswerContractError(f"{name} contains an unsupported value type")


def extract_urls(value: object) -> tuple[str, ...]:
    """从可信 bounded projection 提取去重 URL，不把模型重新抄写的链接当作来源。"""

    urls: list[str] = []
    seen: set[str] = set()

    def visit(candidate: object) -> None:
        """递归读取普通字符串容器，并在统一入口施加数量和长度上限。"""

        if len(urls) >= MAX_SOURCE_URLS:
            return
        if isinstance(candidate, str):
            for match in _URL_PATTERN.findall(candidate):
                url = match.rstrip(_URL_TRAILING_PUNCTUATION)
                if not url or len(url) > MAX_SOURCE_URL_CHARS or url in seen:
                    continue
                seen.add(url)
                urls.append(url)
                if len(urls) >= MAX_SOURCE_URLS:
                    return
            return
        if isinstance(candidate, Mapping):
            for nested in candidate.values():
                visit(nested)
                if len(urls) >= MAX_SOURCE_URLS:
                    return
            return
        if isinstance(candidate, (list, tuple)):
            for nested in candidate:
                visit(nested)
                if len(urls) >= MAX_SOURCE_URLS:
                    return

    visit(value)
    return tuple(urls)


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
    urls: tuple[str, ...] = ()

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
        if not isinstance(self.urls, tuple):
            raise AnswerContractError("urls must be a tuple")
        if len(self.urls) > MAX_SOURCE_URLS:
            raise AnswerContractError(f"urls exceeds {MAX_SOURCE_URLS} items")
        object.__setattr__(
            self,
            "urls",
            tuple(
                _text(f"urls[{index}]", url, max_chars=MAX_SOURCE_URL_CHARS)
                for index, url in enumerate(self.urls)
            ),
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
    value_snapshot: object = _MISSING_STRUCTURED_VALUE
    query_scope_snapshot: Mapping[str, object] | None = None
    execution_limitations: tuple[str, ...] = ()
    source_id: str | None = None

    def __post_init__(self) -> None:
        # locator/value 是模型提出的候选，finalizer 会按 tool result 的可信值重新 hydrate。
        for name in ("run_id", "tool_call_id", "tool_result_id", "locator"):
            object.__setattr__(self, name, _text(name, getattr(self, name), max_chars=512))
        if self.locator_kind not in ("scalar", "row", "field", "aggregate"):
            raise AnswerContractError("locator_kind must be scalar, row, field, or aggregate")
        if self.query_scope_snapshot is not None and not isinstance(self.query_scope_snapshot, Mapping):
            raise AnswerContractError("query_scope_snapshot must be a mapping")
        if self.value_snapshot is _MISSING_STRUCTURED_VALUE:
            # identity-only candidate 只允许在 Finalizer 读取 current Tool Result 前暂存。
            if self.source_id is None:
                raise AnswerContractError("structured source requires value_snapshot or source_id")
        else:
            _check_bounded_value("value_snapshot", self.value_snapshot)
        if self.query_scope_snapshot is not None:
            _check_bounded_value("query_scope_snapshot", self.query_scope_snapshot)
        object.__setattr__(
            self,
            "source_id",
            _optional_text("source_id", self.source_id, max_chars=512),
        )
        object.__setattr__(
            self,
            "execution_limitations",
            _limitations("execution_limitations", self.execution_limitations),
        )


@dataclass(frozen=True)
class SourceHandleReference:
    """finalization 临时使用的短 source handle，不允许直接持久化。"""

    source_id: str

    def __post_init__(self) -> None:
        # handle 是模型提出的唯一输入；它不携带任何可伪造的父级 provenance。
        object.__setattr__(self, "source_id", _text("source_id", self.source_id, max_chars=256))


SourceReference: TypeAlias = MessageSource | StructuredSource | SourceHandleReference


@dataclass(frozen=True)
class AnswerSourceSummary:
    """AnswerArtifact 中一条去重后的来源摘要。"""

    index: int
    reference: SourceReference
    evidence_ids: tuple[str, ...]
    relations: tuple[SourceRelation, ...]


def source_reference_key(reference: SourceReference) -> tuple[str, ...]:
    """使用 canonical locator 去重，不把正文或一次执行 provenance 当作 identity。"""

    if isinstance(reference, MessageSource):
        return (
            "message",
            reference.session_id,
            reference.internal_message_id,
        )
    if isinstance(reference, SourceHandleReference):
        return ("handle", reference.source_id)
    return (
        "structured",
        reference.run_id,
        reference.tool_call_id,
        reference.tool_result_id,
        reference.locator_kind,
        reference.locator,
    )


def answer_source_summaries(artifact: AnswerArtifact) -> tuple[AnswerSourceSummary, ...]:
    """按 Evidence/source 原始顺序生成 bounded、去重且可复用的来源列表。"""

    if not isinstance(artifact, AnswerArtifact):
        raise SourceInspectionError("source list requires a finalized AnswerArtifact")

    summaries: list[AnswerSourceSummary] = []
    positions: dict[tuple[str, ...], int] = {}
    evidence_ids: list[list[str]] = []
    relations: list[list[SourceRelation]] = []
    for evidence in artifact.evidence_items:
        for evidence_source in evidence.sources:
            key = source_reference_key(evidence_source.reference)
            position = positions.get(key)
            if position is None:
                position = len(summaries)
                positions[key] = position
                summaries.append(
                    AnswerSourceSummary(
                        index=position + 1,
                        reference=evidence_source.reference,
                        evidence_ids=(evidence.evidence_id,),
                        relations=(evidence_source.relation,),
                    )
                )
                evidence_ids.append([evidence.evidence_id])
                relations.append([evidence_source.relation])
                continue
            if evidence.evidence_id not in evidence_ids[position]:
                evidence_ids[position].append(evidence.evidence_id)
            if evidence_source.relation not in relations[position]:
                relations[position].append(evidence_source.relation)

    return tuple(
        replace(
            summary,
            evidence_ids=tuple(evidence_ids[index]),
            relations=tuple(relations[index]),
        )
        for index, summary in enumerate(summaries)
    )


@dataclass(frozen=True)
class EvidenceSource:
    """一个 source 相对当前 finding 的关系。"""

    relation: SourceRelation
    reference: SourceReference

    def __post_init__(self) -> None:
        # relation 属于 Evidence 语义，不能复用 Retrieval 的 included/excluded 状态。
        if self.relation not in ("supports", "contradicts", "context"):
            raise AnswerContractError("relation must be supports, contradicts, or context")
        if not isinstance(self.reference, (MessageSource, StructuredSource, SourceHandleReference)):
            raise AnswerContractError("reference must be MessageSource, StructuredSource, or SourceHandleReference")


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
class ModelAnswerClaim:
    """模型只提交一条语义 claim 及其 source handle，不生成 Artifact bookkeeping。"""

    text: str
    finding: str
    criterion: str
    sufficiency: EvidenceSufficiency
    sources: tuple[tuple[str, SourceRelation], ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Host compiler 会按 claim 顺序生成 block/evidence ID，因此模型无需复制这些 ID。
        object.__setattr__(self, "text", _text("claim text", self.text))
        object.__setattr__(self, "finding", _text("claim finding", self.finding))
        object.__setattr__(self, "criterion", _text("claim criterion", self.criterion))
        if self.sufficiency not in ("sufficient", "partial", "insufficient"):
            raise AnswerContractError("claim sufficiency is invalid")
        if not isinstance(self.sources, tuple):
            raise AnswerContractError("claim sources must be a tuple")
        if len(self.sources) > MAX_SOURCES_PER_EVIDENCE:
            raise AnswerContractError(f"claim sources exceeds {MAX_SOURCES_PER_EVIDENCE} items")
        normalized_sources: list[tuple[str, SourceRelation]] = []
        seen: set[str] = set()
        for index, item in enumerate(self.sources):
            if not isinstance(item, tuple) or len(item) != 2:
                raise AnswerContractError(f"claim sources[{index}] must be a handle/relation pair")
            source_id, relation = item
            source_id = _text(f"claim sources[{index}].source_id", source_id, max_chars=256)
            if relation not in ("supports", "contradicts", "context"):
                raise AnswerContractError(f"claim sources[{index}].relation is invalid")
            if source_id in seen:
                raise AnswerContractError("claim sources must not contain duplicate handles")
            seen.add(source_id)
            normalized_sources.append((source_id, relation))
        object.__setattr__(self, "sources", tuple(normalized_sources))
        object.__setattr__(self, "limitations", _limitations("claim limitations", self.limitations))


@dataclass(frozen=True)
class ModelAnswerCandidate:
    """final synthesis 的 semantic candidate；validated AnswerArtifact 由 Host 编译。"""

    claims: tuple[ModelAnswerClaim, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # claim 数量受同一 Evidence budget 约束，避免模型用大量空壳 claim 挤压 finalizer。
        if not isinstance(self.claims, tuple) or not self.claims:
            raise AnswerContractError("model answer candidate requires claims")
        if len(self.claims) > MAX_CONTENT_BLOCKS:
            raise AnswerContractError(f"model answer candidate exceeds {MAX_CONTENT_BLOCKS} claims")
        if any(not isinstance(claim, ModelAnswerClaim) for claim in self.claims):
            raise AnswerContractError("model answer candidate claims are invalid")
        object.__setattr__(self, "limitations", _limitations("candidate limitations", self.limitations))


@dataclass(frozen=True)
class ToolMessageItem:
    """Tool Result 中一个可引用的 bounded canonical message projection。"""

    result_item_id: str
    message: MessageProjection
    content_truncated: bool = False
    urls: tuple[str, ...] = ()
    is_hit: bool = True

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
        if not isinstance(self.is_hit, bool):
            raise AnswerContractError("is_hit must be a boolean")
        if not isinstance(self.urls, tuple):
            raise AnswerContractError("tool message urls must be a tuple")
        if len(self.urls) > MAX_SOURCE_URLS:
            raise AnswerContractError(f"tool message urls exceeds {MAX_SOURCE_URLS} items")
        object.__setattr__(
            self,
            "urls",
            tuple(
                _text(f"tool message urls[{index}]", url, max_chars=MAX_SOURCE_URL_CHARS)
                for index, url in enumerate(self.urls)
            ),
        )


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

    @property
    def source_id(self) -> str:
        """返回当前 Tool Result 内稳定、短且可复制的 structured source identity。"""

        return f"{self.locator_kind}:{self.locator}"


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
        if len(self.message_items) > MAX_TOOL_RESULT_MESSAGE_ITEMS:
            raise AnswerContractError(
                f"tool result message items exceeds {MAX_TOOL_RESULT_MESSAGE_ITEMS}"
            )
        if len(self.structured_items) > MAX_TOOL_RESULT_STRUCTURED_ITEMS:
            raise AnswerContractError(
                f"tool result structured items exceeds {MAX_TOOL_RESULT_STRUCTURED_ITEMS}"
            )
        if self.status == "error" and (self.message_items or self.structured_items):
            raise AnswerContractError("error tool results cannot contain source items")
        message_ids = [item.result_item_id for item in self.message_items]
        if len(set(message_ids)) != len(message_ids):
            raise AnswerContractError("tool result message item IDs must be unique")
        structured_ids = [(item.locator_kind, item.locator) for item in self.structured_items]
        if len(set(structured_ids)) != len(structured_ids):
            raise AnswerContractError("tool result structured locators must be unique")
        object.__setattr__(self, "limitations", _limitations("tool result limitations", self.limitations))

    @property
    def model_scope_id(self) -> str:
        """从 Trivae-owned tool-call ordinal 生成当前 Tool Result 的短 scope label。"""

        # Runtime 生成的 identity 末段是单调 tool-call ordinal；保留末段即可避免重复父级 JSON。
        return self.tool_call_id.rsplit("/", 1)[-1]

    def message_source_handle(self, item: ToolMessageItem) -> str:
        """为当前 Tool Result 内的 message 生成稳定、短且不跨 run 的 handle。"""

        try:
            index = self.message_items.index(item)
        except ValueError as exc:
            raise AnswerContractError("message item does not belong to the tool result") from exc
        return f"m{self.model_scope_id}-{index + 1}"

    def structured_source_handle(self, item: ToolStructuredItem) -> str:
        """为当前 Tool Result 内的 structured item 生成稳定 source handle。"""

        try:
            index = self.structured_items.index(item)
        except ValueError as exc:
            raise AnswerContractError("structured item does not belong to the tool result") from exc
        return f"s{self.model_scope_id}-{index + 1}"

    def resolve_source_handle(
        self,
        source_id: str,
    ) -> tuple[Literal["message", "structured"], ToolMessageItem | ToolStructuredItem] | None:
        """只在当前 Tool Result scope 内解析 handle，不尝试跨 record 猜测。"""

        # 直接使用 enumerate 生成 ordinal，避免每个候选再次在线性 tuple 中查 index。
        for index, message_item in enumerate(self.message_items):
            if f"m{self.model_scope_id}-{index + 1}" == source_id:
                return "message", message_item
        # structured source 也按同样的 ordinal 规则解析，保持两类 locator 的边界一致。
        for index, structured_item in enumerate(self.structured_items):
            if f"s{self.model_scope_id}-{index + 1}" == source_id:
                return "structured", structured_item
        return None

    def message_item_by_internal_id(self, internal_message_id: str) -> ToolMessageItem:
        """把 canonical message identity 解析为当前 record item，缺失时显式暴露 record bug。"""

        for item in self.message_items:
            if item.message.internal_message_id == internal_message_id:
                return item
        raise ToolResultProjectionError("message projection is missing from the canonical tool record")

    def structured_item_by_locator(self, locator_kind: str, locator: str) -> ToolStructuredItem:
        """把 structured locator 解析为当前 record item，避免模型自行拼 row identity。"""

        for item in self.structured_items:
            if item.locator_kind == locator_kind and item.locator == locator:
                return item
        raise ToolResultProjectionError("structured projection is missing from the canonical tool record")

    def to_model_provenance(self, *, source_ids: set[str] | None = None) -> dict[str, object]:
        """只向模型暴露短 source handle，不重复 full provenance 或 trusted snapshot。"""

        # source_ids 由当前 model data projection 派生；canonical record 仍保留全部 items。
        message_sources = []
        # 使用 enumerate 直接得到稳定 ordinal，避免大结果集下 O(n²) 的 tuple.index。
        for index, _message_item in enumerate(self.message_items):
            source_id = f"m{self.model_scope_id}-{index + 1}"
            if source_ids is None or source_id in source_ids:
                message_sources.append({"type": "message", "source_id": source_id})
        structured_sources = []
        # structured item 同样直接按位置生成 handle，保持 provenance 顺序且不扫描前缀。
        for index, structured_item in enumerate(self.structured_items):
            source_id = f"s{self.model_scope_id}-{index + 1}"
            if source_ids is None or source_id in source_ids:
                structured_sources.append(
                    {
                        "type": "structured",
                        "source_id": source_id,
                        "locator_kind": structured_item.locator_kind,
                        "locator": structured_item.locator,
                    }
                )
        return {
            "tool_result_scope": self.model_scope_id,
            "message_sources": message_sources,
            "structured_sources": structured_sources,
        }


def _message_items(
    messages: tuple[MessageProjection, ...],
    *,
    hit_ids: set[str] | None = None,
) -> tuple[ToolMessageItem, ...]:
    """按 internal identity 去重，并保留 hit/context 角色供模型预算 trimming 使用。"""

    items: list[ToolMessageItem] = []
    seen: set[str] = set()
    for message in messages:
        if message.internal_message_id in seen:
            continue
        seen.add(message.internal_message_id)
        content = message.normalized_content
        urls = extract_urls(content)
        if len(content) > MAX_SAFE_EXCERPT_CHARS:
            # Record 内只留可供人工复核的 bounded excerpt，并用标记保留“发生过截断”的事实。
            bounded_message = replace(message, normalized_content=content[: MAX_SAFE_EXCERPT_CHARS - 1] + "…")
            items.append(
                ToolMessageItem(
                    f"message/{message.internal_message_id}",
                    bounded_message,
                    True,
                    urls,
                    hit_ids is None or message.internal_message_id in hit_ids,
                )
            )
        else:
            items.append(
                ToolMessageItem(
                    f"message/{message.internal_message_id}",
                    message,
                    False,
                    urls,
                    hit_ids is None or message.internal_message_id in hit_ids,
                )
            )
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
        hit_ids = {hit.message.internal_message_id for hit in data.hits}
        message_items = _message_items(messages, hit_ids=hit_ids)
        query_snapshot = data.query.to_dict()
    elif isinstance(data, SemanticRetrievalResult):
        # semantic chunk 只作为 candidate provenance；可引用内容必须是恢复后的 canonical messages。
        message_items = _message_items(data.expanded_messages, hit_ids=set(data.primary_message_ids))
        query_snapshot = data.query.to_dict()
    elif isinstance(data, StructuredMessageResult):
        message_items = _message_items(data.messages)
        query_snapshot = data.query.to_dict()
    elif isinstance(data, MessageContextResult):
        # Explicit context 的所有消息都属于当前 Tool Result，可继续使用 MessageSource citation。
        message_items = _message_items(data.messages)
        raw_scope = data.metadata.filters.get("scope", {})
        query_snapshot = {
            "message_id": data.message_id,
            "session_id": data.session_id,
            "requested_before": data.requested_before,
            "requested_after": data.requested_after,
            "scope": dict(raw_scope) if isinstance(raw_scope, Mapping) else {},
        }
    elif isinstance(data, FindMembersResult):
        # 成员候选以 bounded structured row 暴露，复用现有 StructuredSource 校验机制。
        structured_items = _member_items(data)
        query_snapshot = data.query.to_dict()
    elif isinstance(data, StructuredAggregateResult):
        query_snapshot = data.query.to_dict()
        structured_items = _aggregate_items(data)
    elif isinstance(data, SchemaResult):
        # Schema table row 是可验证的 structured source，不伪装成 message citation。
        query_snapshot = {
            "schema_tables": tuple(table.name for table in data.tables),
            "scope": dict(data.metadata.filters),
        }
        structured_items = _schema_items(data)
    elif isinstance(data, SQLQueryResult):
        # SQL 结果保留原始 query、scope 和 bound，finalizer 只接受 record 中的精确 row value。
        query_snapshot = {
            "query": data.query.to_dict(),
            "scope": dict(data.metadata.filters),
        }
        structured_items = _sql_items(data)

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


def _member_items(result: FindMembersResult) -> tuple[ToolStructuredItem, ...]:
    """为每个成员候选建立可验证的 row locator，并保留完整匹配依据。"""

    return tuple(
        ToolStructuredItem("row", f"candidates[{index}]", candidate.to_dict())
        for index, candidate in enumerate(result.candidates)
    )


def _schema_items(result: SchemaResult) -> tuple[ToolStructuredItem, ...]:
    """为 schema inspection 建立稳定 table row locator。"""

    return tuple(
        ToolStructuredItem("row", f"tables[{index}]", table.to_dict())
        for index, table in enumerate(result.tables)
    )


def _sql_items(result: SQLQueryResult) -> tuple[ToolStructuredItem, ...]:
    """为每一条 bounded SQL row 建立可复核 locator，不把 query 改写成 citation。"""

    return tuple(
        ToolStructuredItem("row", f"rows[{index}]", dict(row))
        for index, row in enumerate(result.rows)
    )


def _model_content(content: str, maximum: int = MAX_MODEL_MESSAGE_CHARS) -> tuple[str, bool]:
    """把 canonical bounded excerpt再投影为 model budget 内的内容。"""

    if len(content) <= maximum:
        return content, False
    return content[: maximum - 1] + "…", True


def _model_message_projection(
    record: ToolResultRecord,
    item: ToolMessageItem,
    source_id: str,
) -> tuple[dict[str, object], tuple[dict[str, object], bool, str, bool]]:
    """生成不含内部 provenance 的消息 projection，并返回 budget trimming slot。"""

    message = item.message
    content, model_content_truncated = _model_content(message.normalized_content)
    entry: dict[str, object] = {
        "source_id": source_id,
        "timestamp": message.timestamp,
        "author": message.sender_name or message.sender_user_id,
        "content": content,
        "session": message.session_display or message.session_id,
        "message_type": message.message_type,
        "urls": item.urls,
        "content_truncated": item.content_truncated or model_content_truncated,
        "hit": item.is_hit,
    }
    # slot 只存在 Host 内存中，full_content 不会随 model payload 返回。
    return entry, (entry, item.is_hit, message.normalized_content, item.content_truncated)


def _project_model_data(
    data: object,
    record: ToolResultRecord,
) -> tuple[object, list[tuple[list[dict[str, object]], dict[str, object], dict[str, object], bool, str, bool]]]:
    """把 canonical envelope data 转成 slim model data，同时保留 Host trimming 索引。"""

    if not isinstance(data, Mapping):
        return data, []
    projected = dict(data)
    # 先建立 canonical identity 索引；大 lexical 结果不应因逐项线性查找退化为 O(n²)。
    message_items_by_internal_id = {
        item.message.internal_message_id: (index, item)
        for index, item in enumerate(record.message_items)
    }
    structured_items_by_locator = {
        (item.locator_kind, item.locator): (index, item)
        for index, item in enumerate(record.structured_items)
    }
    slots: list[
        tuple[list[dict[str, object]], dict[str, object], dict[str, object], bool, str, bool]
    ] = []

    if projected.get("strategy") == "semantic":
        # chunk/parent/index identity 是 Host provenance，不是模型回答语义；只保留排序和质量摘要。
        raw_hits = projected.get("hits")
        if isinstance(raw_hits, list):
            projected["hits"] = [
                {
                    "score": hit.get("score"),
                    "score_type": hit.get("score_type"),
                    "dense_rank": hit.get("dense_rank"),
                }
                for hit in raw_hits
                if isinstance(hit, Mapping)
            ]
        raw_metadata = projected.get("metadata")
        if isinstance(raw_metadata, Mapping):
            metadata = dict(raw_metadata)
            raw_details = metadata.get("details")
            if isinstance(raw_details, Mapping):
                visible_detail_names = {
                    "index_status",
                    "canonical_message_count",
                    "indexed_message_count",
                    "indexed_chunk_count",
                    "dense_candidate_pool",
                    "dense_candidates_returned",
                    "accepted_candidates",
                    "candidate_scores",
                    "score_type",
                    "context_before",
                    "context_after",
                    "expanded_candidate_messages",
                    "known_gaps",
                }
                metadata["details"] = {
                    name: value for name, value in raw_details.items() if name in visible_detail_names
                }
            projected["metadata"] = metadata

    raw_hits = projected.get("hits")
    hit_message_ids: set[str] = set()
    if isinstance(raw_hits, list):
        projected_hits: list[dict[str, object]] = []
        for index, raw_hit in enumerate(raw_hits):
            if not isinstance(raw_hit, Mapping):
                raise ToolResultProjectionError(f"canonical hit {index} is not an object")
            hit = dict(raw_hit)
            raw_message = hit.get("message")
            if isinstance(raw_message, Mapping):
                internal_id = raw_message.get("internal_message_id")
                if not isinstance(internal_id, str) or not internal_id:
                    raise ToolResultProjectionError(f"canonical hit {index} has no message identity")
                indexed_item = message_items_by_internal_id.get(internal_id)
                if indexed_item is None:
                    raise ToolResultProjectionError("message projection is missing from the canonical tool record")
                message_index, item = indexed_item
                entry, slot = _model_message_projection(
                    record,
                    item,
                    f"m{record.model_scope_id}-{message_index + 1}",
                )
                hit["message"] = entry
                hit_message_ids.add(internal_id)
                projected_hits.append(hit)
                # hit 的可编辑 message entry 与可移除的 hit wrapper 是两个不同字典。
                slots.append((projected_hits, entry, hit, *slot[1:]))
            else:
                # semantic hit 是 range candidate，没有 message body；canonical range metadata 仍可审计。
                projected_hits.append(hit)
        projected["hits"] = projected_hits

    def project_message_list(name: str, *, skip_hit_messages: bool = False) -> None:
        """转换指定列表，并让 lexical hit 不在 expanded context 中重复搬运正文。"""

        raw_messages = projected.get(name)
        if not isinstance(raw_messages, list):
            return
        projected_messages: list[dict[str, object]] = []
        for index, raw_message in enumerate(raw_messages):
            if not isinstance(raw_message, Mapping):
                raise ToolResultProjectionError(f"canonical {name}[{index}] is not an object")
            internal_id = raw_message.get("internal_message_id")
            if not isinstance(internal_id, str) or not internal_id:
                raise ToolResultProjectionError(f"canonical {name}[{index}] has no message identity")
            if skip_hit_messages and internal_id in hit_message_ids:
                continue
            indexed_item = message_items_by_internal_id.get(internal_id)
            if indexed_item is None:
                raise ToolResultProjectionError("message projection is missing from the canonical tool record")
            message_index, item = indexed_item
            entry, slot = _model_message_projection(
                record,
                item,
                f"m{record.model_scope_id}-{message_index + 1}",
            )
            projected_messages.append(entry)
            slots.append((projected_messages, entry, entry, *slot[1:]))
        projected[name] = projected_messages

    if "expanded_messages" in projected:
        project_message_list("expanded_messages", skip_hit_messages=bool(hit_message_ids))
    if "messages" in projected:
        project_message_list("messages")

    raw_candidates = projected.get("candidates")
    if isinstance(raw_candidates, list):
        projected_candidates: list[dict[str, object]] = []
        for index, raw_candidate in enumerate(raw_candidates):
            if not isinstance(raw_candidate, Mapping):
                raise ToolResultProjectionError(f"candidate {index} is not an object")
            candidate = dict(raw_candidate)
            structured_indexed_item = structured_items_by_locator.get(("row", f"candidates[{index}]"))
            if structured_indexed_item is None:
                raise ToolResultProjectionError("structured projection is missing from the canonical tool record")
            structured_index, _structured_item = structured_indexed_item
            candidate["source_id"] = f"s{record.model_scope_id}-{structured_index + 1}"
            projected_candidates.append(candidate)
        projected["candidates"] = projected_candidates

    raw_tables = projected.get("tables")
    if isinstance(raw_tables, list):
        projected_tables: list[dict[str, object]] = []
        for index, raw_table in enumerate(raw_tables):
            if not isinstance(raw_table, Mapping):
                raise ToolResultProjectionError(f"table {index} is not an object")
            table = dict(raw_table)
            structured_indexed_item = structured_items_by_locator.get(("row", f"tables[{index}]"))
            if structured_indexed_item is None:
                raise ToolResultProjectionError("structured projection is missing from the canonical tool record")
            structured_index, _structured_item = structured_indexed_item
            table["source_id"] = f"s{record.model_scope_id}-{structured_index + 1}"
            projected_tables.append(table)
        projected["tables"] = projected_tables

    raw_rows = projected.get("rows")
    if isinstance(raw_rows, list):
        projected_rows: list[dict[str, object]] = []
        for index, raw_row in enumerate(raw_rows):
            if not isinstance(raw_row, Mapping):
                raise ToolResultProjectionError(f"SQL row {index} is not an object")
            row = dict(raw_row)
            structured_indexed_item = structured_items_by_locator.get(("row", f"rows[{index}]"))
            if structured_indexed_item is None:
                raise ToolResultProjectionError("structured projection is missing from the canonical tool record")
            structured_index, _structured_item = structured_indexed_item
            row["source_id"] = f"s{record.model_scope_id}-{structured_index + 1}"
            projected_rows.append(row)
        projected["rows"] = projected_rows

    return projected, slots


def _projection_size(payload: Mapping[str, object]) -> int:
    """以 UTF-8 byte 数估算 transport size；不把估算值冒充 provider token usage。"""

    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _projected_source_ids(value: object) -> set[str]:
    """收集当前 model data 中真正可见的 source handle，过滤被省略的 context locator。"""

    source_ids: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key == "source_id" and isinstance(nested, str):
                source_ids.add(nested)
            else:
                source_ids.update(_projected_source_ids(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            source_ids.update(_projected_source_ids(nested))
    return source_ids


def _set_projection_metrics(
    payload: dict[str, object],
    *,
    token_budget: int,
    truncated: bool,
    omitted_context_messages: int,
    omitted_hit_messages: int,
) -> None:
    """写入公开 projection 预算事实，避免 Host 侧 trim 变成 hidden truncation。"""

    payload["model_projection"] = {
        "token_budget": token_budget,
        "estimated_tokens": (_projection_size(payload) + MODEL_TOKEN_CHAR_RATIO - 1) // MODEL_TOKEN_CHAR_RATIO,
        "truncated": truncated,
        "omitted_context_messages": omitted_context_messages,
        "omitted_hit_messages": omitted_hit_messages,
    }


def project_tool_result_for_model(
    envelope: ToolEnvelope,
    record: ToolResultRecord,
    *,
    token_budget: int = DEFAULT_TOOL_RESULT_TOKEN_BUDGET,
) -> dict[str, object]:
    """保留 canonical host record，同时向模型返回独立、有界且可审计的 slim projection。"""

    if isinstance(token_budget, bool) or not isinstance(token_budget, int) or token_budget <= 0:
        raise ToolResultProjectionError("tool result token budget must be positive")
    canonical_payload = envelope.to_dict()
    projected_data, slots = _project_model_data(canonical_payload.get("data"), record)
    payload: dict[str, object] = {
        "status": canonical_payload["status"],
        "data": projected_data,
        "meta": canonical_payload["meta"],
        "error": canonical_payload["error"],
        "provenance": record.to_model_provenance(),
    }
    max_bytes = token_budget * MODEL_TOKEN_CHAR_RATIO
    truncated = False
    omitted_context_messages = 0
    omitted_hit_messages = 0

    def fits() -> bool:
        """每次检查都包含 projection metrics，保证公开 payload 本身不越预算。"""

        # context trim 后同步缩小 model provenance；Host canonical record 不受此 projection 变化影响。
        payload["provenance"] = record.to_model_provenance(source_ids=_projected_source_ids(payload["data"]))
        payload.pop("model_projection", None)
        _set_projection_metrics(
            payload,
            token_budget=token_budget,
            truncated=truncated,
            omitted_context_messages=omitted_context_messages,
            omitted_hit_messages=omitted_hit_messages,
        )
        return _projection_size(payload) <= max_bytes

    if not fits():
        # 第一阶段只删除 context；所有真实 retrieval hits 必须继续留在 model projection。
        retained_slots: list[
            tuple[list[dict[str, object]], dict[str, object], dict[str, object], bool, str, bool]
        ] = []
        for container, entry, remove_entry, is_hit, full_content, canonical_truncated in slots:
            if is_hit:
                retained_slots.append(
                    (container, entry, remove_entry, is_hit, full_content, canonical_truncated)
                )
                continue
            container.remove(remove_entry)
            omitted_context_messages += 1
        slots = retained_slots
        truncated = omitted_context_messages > 0

    if not fits():
        # 第二阶段只缩短正文；source handle、timestamp、author、URL 和 hit identity 不被删除。
        for maximum in (512, 384, 256, 192, 128, 96, 64, 32):
            for _container, entry, _remove_entry, _is_hit, full_content, canonical_truncated in slots:
                content, content_truncated = _model_content(full_content, maximum)
                entry["content"] = content
                entry["content_truncated"] = canonical_truncated or content_truncated
            truncated = True
            if fits():
                break
        else:
            # 直击仍无法容纳时，按 retrieval 稳定顺序从尾部省略 direct hit；
            # canonical record 保留完整候选，model-visible provenance 随 payload 同步收缩。
            hit_slots = tuple(slot for slot in slots if slot[3])
            if not hit_slots:
                raise ToolResultProjectionError(
                    "canonical tool result cannot fit the independent model token budget"
                )

            # 省略数量对 payload 大小单调递减，用二分搜索避免逐条 remove + JSON 序列化退化为 O(n²)。
            base_contents = {
                id(container): (container, list(container))
                for container, _entry, _remove_entry, _is_hit, _full_content, _canonical_truncated in slots
            }

            def apply_hit_omission(count: int) -> None:
                """从当前 context-trim 基线重建列表，只移除稳定顺序尾部 hit。"""

                omitted_entries = {
                    id(slot[2])
                    for slot in hit_slots[len(hit_slots) - count :]
                }
                for container, original in base_contents.values():
                    # 通过 identity 过滤可避免 list.remove 对每个尾部 hit 重复扫描前缀。
                    container[:] = [entry for entry in original if id(entry) not in omitted_entries]

            low = 0
            high = len(hit_slots)
            while low < high:
                candidate = (low + high) // 2
                apply_hit_omission(candidate)
                omitted_hit_messages = candidate
                truncated = True
                if fits():
                    high = candidate
                else:
                    low = candidate + 1

            apply_hit_omission(low)
            omitted_hit_messages = low
            truncated = True
            slots = [slot for slot in slots if slot[3] and id(slot[2]) not in {
                id(hit_slot[2]) for hit_slot in hit_slots[len(hit_slots) - low :]
            }]
            if not fits():
                # 所有 direct hit 都移除仍不能满足最低 projection 时，必须显式报告 contract 错误。
                raise ToolResultProjectionError(
                    "canonical tool result cannot fit the independent model token budget"
                )

    # fits() 已把 metrics 写入 payload；最后一次 size check 防止修改后产生隐式超限。
    if _projection_size(payload) > max_bytes:
        raise ToolResultProjectionError("model tool result projection exceeds its token budget")
    return payload


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
        if source_type == "handle":
            return SourceHandleReference(source_id=raw["source_id"])
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
            value_snapshot = raw.get("value_snapshot", _MISSING_STRUCTURED_VALUE)
            return StructuredSource(
                run_id=raw["run_id"],
                tool_call_id=raw["tool_call_id"],
                tool_result_id=raw["tool_result_id"],
                locator_kind=raw["locator_kind"],
                locator=raw["locator"],
                value_snapshot=value_snapshot,
                source_id=raw.get("source_id"),
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


def _parse_model_source(raw: object, path: str) -> tuple[str, SourceRelation]:
    """解析 semantic candidate 的短 handle；relation 只表达语义，不复制 provenance。"""

    source_id: object
    if isinstance(raw, str):
        source_id = raw
        relation: object = "supports"
    elif isinstance(raw, Mapping):
        source_id = raw.get("source_id")
        relation = raw.get("relation", "supports")
    else:
        raise _model_error("INVALID_SOURCE", "model source must be a handle string or object", path)
    try:
        normalized_source_id = _text(f"{path}.source_id", source_id, max_chars=256)
    except AnswerContractError as exc:
        raise _model_error("INVALID_SOURCE", str(exc), path) from exc
    if relation not in ("supports", "contradicts", "context"):
        raise _model_error("INVALID_SOURCE", "source relation is invalid", f"{path}.relation")
    return normalized_source_id, relation


def parse_model_answer_candidate(output: str) -> ModelAnswerCandidate:
    """解析新的 semantic-only final contract，不接受 host-owned Artifact bookkeeping。"""

    if not isinstance(output, str) or not output.strip():
        raise _model_error("INVALID_FINAL_OUTPUT", "final answer must be non-empty text")
    try:
        decoded = json.loads(output.strip())
    except json.JSONDecodeError as exc:
        raise _model_error("INVALID_MODEL_CANDIDATE", "model answer candidate is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise _model_error("INVALID_MODEL_CANDIDATE", "model answer candidate must be an object")
    claims: list[ModelAnswerClaim] = []
    for index, raw_claim in enumerate(_payload_list(decoded, "claims")):
        path = f"claims[{index}]"
        if not isinstance(raw_claim, Mapping):
            raise _model_error("INVALID_MODEL_CANDIDATE", "claim must be an object", path)
        raw_sources = raw_claim.get("sources", [])
        if not isinstance(raw_sources, list):
            raise _model_error("INVALID_MODEL_CANDIDATE", "sources must be an array", f"{path}.sources")
        sources = tuple(
            _parse_model_source(raw_source, f"{path}.sources[{source_index}]")
            for source_index, raw_source in enumerate(raw_sources)
        )
        raw_limitations = raw_claim.get("limitations", [])
        if not isinstance(raw_limitations, list):
            raise _model_error("INVALID_MODEL_CANDIDATE", "limitations must be an array", f"{path}.limitations")
        try:
            claims.append(
                ModelAnswerClaim(
                    text=raw_claim["text"],
                    finding=raw_claim["finding"],
                    criterion=raw_claim["criterion"],
                    sufficiency=raw_claim["sufficiency"],
                    sources=sources,
                    limitations=tuple(raw_limitations),
                )
            )
        except KeyError as exc:
            raise _model_error("INVALID_MODEL_CANDIDATE", "claim is missing a required field", f"{path}.{exc.args[0]}") from exc
        except (AnswerContractError, TypeError) as exc:
            raise _model_error("INVALID_MODEL_CANDIDATE", str(exc), path) from exc

    raw_limitations = decoded.get("limitations", [])
    if not isinstance(raw_limitations, list):
        raise _model_error("INVALID_MODEL_CANDIDATE", "limitations must be an array", "limitations")
    try:
        return ModelAnswerCandidate(tuple(claims), tuple(raw_limitations))
    except (AnswerContractError, TypeError) as exc:
        raise _model_error("INVALID_MODEL_CANDIDATE", str(exc)) from exc


def compile_model_answer_candidate(
    candidate: ModelAnswerCandidate,
    *,
    has_tool_results: bool,
) -> AnswerArtifact:
    """由 Host 确定性生成 block/evidence/binding identity，再交给同一 strict finalizer。"""

    blocks = tuple(
        AnswerContentBlock(f"claim-{index + 1}", claim.text)
        for index, claim in enumerate(candidate.claims)
    )
    if not has_tool_results:
        claim_limitations = tuple(limit for claim in candidate.claims for limit in claim.limitations)
        return AnswerArtifact(
            content_blocks=blocks,
            limitations=tuple((*candidate.limitations, *claim_limitations)),
        )

    evidence_items: list[EvidenceItem] = []
    bindings: list[CitationBinding] = []
    for index, claim in enumerate(candidate.claims):
        evidence_id = f"e{index + 1}"
        sources = tuple(
            EvidenceSource(relation, SourceHandleReference(source_id))
            for source_id, relation in claim.sources
        )
        evidence_items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                finding=claim.finding,
                criterion=claim.criterion,
                sufficiency=claim.sufficiency,
                sources=sources,
                limitations=claim.limitations,
            )
        )
        bindings.append(CitationBinding(f"claim-{index + 1}", (evidence_id,)))
    return AnswerArtifact(
        content_blocks=blocks,
        citation_bindings=tuple(bindings),
        evidence_items=tuple(evidence_items),
        limitations=candidate.limitations,
    )


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


def _hydrate_snapshot(
    message: MessageProjection,
    *,
    content_truncated: bool = False,
    source_urls: tuple[str, ...] = (),
) -> MessageDisplaySnapshot:
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
        urls=source_urls or extract_urls(content),
    )


def _resolve_source_handle(
    source_id: str,
    records: Mapping[tuple[str, str], ToolResultRecord],
    source_path: str,
) -> tuple[ToolResultRecord, Literal["message", "structured"], ToolMessageItem | ToolStructuredItem]:
    """在当前 run 的 unique Tool Result 集合内解析短 handle，拒绝缺失或歧义。"""

    matches: list[tuple[ToolResultRecord, Literal["message", "structured"], ToolMessageItem | ToolStructuredItem]] = []
    seen_records: set[int] = set()
    for record in records.values():
        if id(record) in seen_records:
            continue
        seen_records.add(id(record))
        resolved = record.resolve_source_handle(source_id)
        if resolved is not None:
            matches.append((record, resolved[0], resolved[1]))
    if not matches:
        raise _model_error("UNRESOLVED_SOURCE_HANDLE", "source handle does not exist in the current run", source_path)
    if len(matches) > 1:
        raise _model_error("AMBIGUOUS_SOURCE_HANDLE", "source handle resolves to multiple tool results", source_path)
    return matches[0]


def _finalize_source(
    source: EvidenceSource,
    *,
    run_id: str,
    accepted_run_ids: tuple[str, ...],
    records: dict[tuple[str, str], ToolResultRecord],
    scope: ExecutionScope,
    source_path: str,
) -> EvidenceSource:
    """验证一个 source 的 provenance/locator/scope，并从可信 record hydrate metadata。"""

    reference = source.reference
    if isinstance(reference, SourceHandleReference):
        # 先把短 handle 映射回 full host locator，再复用原有 strict source 主链路。
        record, source_type, item = _resolve_source_handle(reference.source_id, records, source_path)
        if source_type == "message":
            if not isinstance(item, ToolMessageItem):
                raise _model_error("INVALID_PROVENANCE", "resolved message source item is invalid", source_path)
            concrete_reference: SourceReference = MessageSource(
                run_id=record.run_id,
                tool_call_id=record.tool_call_id,
                tool_result_id=record.tool_result_id,
                result_item_id=item.result_item_id,
                session_id=item.message.session_id,
                internal_message_id=item.message.internal_message_id,
            )
        else:
            if not isinstance(item, ToolStructuredItem):
                raise _model_error("INVALID_PROVENANCE", "resolved structured source item is invalid", source_path)
            concrete_reference = StructuredSource(
                run_id=record.run_id,
                tool_call_id=record.tool_call_id,
                tool_result_id=record.tool_result_id,
                locator_kind=item.locator_kind,
                locator=item.locator,
                source_id=item.source_id,
            )
        return _finalize_source(
            EvidenceSource(source.relation, concrete_reference),
            run_id=run_id,
            accepted_run_ids=accepted_run_ids,
            records=records,
            scope=scope,
            source_path=source_path,
        )
    source_run_id = reference.run_id
    if source_run_id != run_id and source_run_id not in accepted_run_ids:
        raise _model_error("INVALID_PROVENANCE", "source does not belong to the current run", f"{source_path}.run_id")
    matched_record = records.get((reference.tool_call_id, reference.tool_result_id))
    if matched_record is None:
        raise _model_error("INVALID_PROVENANCE", "source tool result was not obtained in the current run", source_path)
    if matched_record.scope_snapshot != scope_snapshot(scope):
        raise _model_error("SCOPE_VIOLATION", "source result scope does not match the current trusted scope", source_path)

    if isinstance(reference, MessageSource):
        matched_message_item: ToolMessageItem | None = next(
            (item for item in matched_record.message_items if item.result_item_id == reference.result_item_id),
            None,
        )
        if matched_message_item is None:
            raise _model_error("UNRESOLVED_MESSAGE_SOURCE", "message result item does not exist", f"{source_path}.result_item_id")
        message = matched_message_item.message
        if message.session_id != reference.session_id or message.internal_message_id != reference.internal_message_id:
            raise _model_error("MESSAGE_SOURCE_MISMATCH", "message locator does not match the tool result", source_path)
        if not _scope_allows_message(message, scope):
            raise _model_error("SCOPE_VIOLATION", "message source is outside the trusted execution scope", source_path)
        return EvidenceSource(
            source.relation,
            replace(
                reference,
                snapshot=_hydrate_snapshot(
                    message,
                    content_truncated=matched_message_item.content_truncated,
                    source_urls=matched_message_item.urls,
                ),
            ),
        )

    structured_item = next(
        (
            item
            for item in matched_record.structured_items
            if item.locator_kind == reference.locator_kind and item.locator == reference.locator
        ),
        None,
    )
    if structured_item is None:
        raise _model_error("UNRESOLVED_STRUCTURED_SOURCE", "structured locator does not exist", f"{source_path}.locator")
    if reference.source_id is not None and reference.source_id != structured_item.source_id:
        raise _model_error(
            "STRUCTURED_SOURCE_ID_MISMATCH",
            "structured source identity does not match the tool result",
            f"{source_path}.source_id",
        )
    if reference.value_snapshot is not _MISSING_STRUCTURED_VALUE and reference.value_snapshot != structured_item.value_snapshot:
        raise _model_error(
            "STRUCTURED_VALUE_MISMATCH",
            "structured source value does not match the tool result",
            f"{source_path}.value_snapshot",
        )
    return EvidenceSource(
        source.relation,
        replace(
            reference,
            value_snapshot=structured_item.value_snapshot,
            query_scope_snapshot=matched_record.query_scope_snapshot,
            execution_limitations=matched_record.limitations,
            source_id=structured_item.source_id,
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

    if tool_results and not artifact.evidence_items:
        # 本轮已经调用 Tool 时，空 Evidence 会把检索事实降级成无法复核的裸总结。
        raise _model_error(
            "MISSING_EVIDENCE",
            "tool-backed answer must include evidence items",
            "evidence_items",
        )
    if tool_results and not artifact.citation_bindings:
        # 至少需要一条 claim→evidence 绑定，CLI 才能展示答案依据而不是只展示孤立来源。
        raise _model_error(
            "MISSING_EVIDENCE",
            "tool-backed answer must bind content blocks to evidence",
            "citation_bindings",
        )
    if tool_results:
        for item_index, item in enumerate(artifact.evidence_items):
            if not item.sources:
                # Evidence 不能只保留语义摘要而省略真实 source，避免不可审计的静默降级。
                raise _model_error(
                    "MISSING_EVIDENCE",
                    "tool-backed evidence must include at least one source",
                    f"evidence_items[{item_index}].sources",
                )
    if not artifact.evidence_items:
        # 没有 Tool 事实的普通回答不需要 current-run provenance，但仍已经是结构化 Artifact。
        return artifact
    if run_id is None or not run_id:
        raise _model_error("INVALID_PROVENANCE", "current run identity is unavailable")
    records = _record_index(tool_results, run_id, accepted_run_ids)
    finalized_items: list[EvidenceItem] = []
    for item_index, item in enumerate(artifact.evidence_items):
        finalized_sources = tuple(
            _finalize_source(
                source,
                run_id=run_id,
                accepted_run_ids=accepted_run_ids,
                records=records,
                scope=scope,
                source_path=f"evidence_items[{item_index}].sources[{source_index}].source",
            )
            for source_index, source in enumerate(item.sources)
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

    normalized_output = output.strip() if isinstance(output, str) else output
    if isinstance(normalized_output, str) and normalized_output.startswith("{"):
        try:
            decoded_output = json.loads(normalized_output)
        except json.JSONDecodeError:
            decoded_output = None
        if isinstance(decoded_output, Mapping) and "claims" in decoded_output:
            # 新 contract 只解析语义字段；Host compiler 负责 Artifact identity bookkeeping。
            candidate = compile_model_answer_candidate(
                parse_model_answer_candidate(normalized_output),
                has_tool_results=bool(tool_results),
            )
        else:
            # 旧 full Artifact JSON 继续走原 parser，保留历史 artifact/codec 兼容性。
            candidate = parse_answer_output(output)
    else:
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


@dataclass
class _FinalizationRecoveryState:
    """graceful recovery 过程中的 bounded 计数器，不会离开 Evidence 层。"""

    dropped_field_count: int = 0
    dropped_field_paths: list[str] = field(default_factory=list)
    dropped_citation_count: int = 0
    normalization_count: int = 0
    validated_citation_count: int = 0
    degradation_codes: list[str] = field(default_factory=list)
    # 同一 Evidence 的多个坏 source 仍只对应一次被丢弃的 citation，避免诊断重复计数。
    dropped_source_evidence_ids: set[str] = field(default_factory=set, repr=False)

    def drop_field(self, path: str) -> None:
        """记录一个被丢弃的字段；只保存有限路径，完整数量仍单独保留。"""

        self.dropped_field_count += 1
        if len(self.dropped_field_paths) < MAX_FINALIZATION_DIAGNOSTIC_ITEMS and path not in self.dropped_field_paths:
            self.dropped_field_paths.append(path)
        self.add_code("field_dropped")

    def drop_citation(self) -> None:
        """记录一个未能通过当前 run provenance 的 citation。"""

        self.dropped_citation_count += 1
        self.add_code("citation_dropped")

    def drop_citation_for_evidence(self, evidence_id: str) -> None:
        """按 Evidence 去重记录 source 失败，防止 hydrate 与 binding 各算一次。"""

        if evidence_id in self.dropped_source_evidence_ids:
            return
        self.dropped_source_evidence_ids.add(evidence_id)
        self.drop_citation()

    def add_code(self, code: str) -> None:
        """以去重方式保留稳定 degradation code，不保存动态错误正文。"""

        if code not in self.degradation_codes and len(self.degradation_codes) < MAX_FINALIZATION_DIAGNOSTIC_ITEMS:
            self.degradation_codes.append(code)


_FATAL_GRACEFUL_CODES = frozenset(
    {
        "INVALID_PROVENANCE",
        "SCOPE_VIOLATION",
        "MESSAGE_SOURCE_MISMATCH",
        "TRUSTED_METADATA_UNAVAILABLE",
    }
)


def _recovery_text(value: object, path: str, state: _FinalizationRecoveryState) -> str | None:
    """尝试保留一个 bounded 文本字段；非法局部字段不会破坏同一答案。"""

    try:
        return _text(path, value)
    except AnswerContractError:
        state.drop_field(path)
        return None


def _recovery_limitations(
    value: object,
    path: str,
    state: _FinalizationRecoveryState,
) -> tuple[str, ...]:
    """规范化有界 limitations；字符串是唯一允许确定性转成单元素数组的错误形态。"""

    if isinstance(value, str):
        normalized = _recovery_text(value, path, state)
        if normalized is None:
            return ()
        state.normalization_count += 1
        state.add_code("limitations_normalized")
        return (normalized,)
    if not isinstance(value, list):
        state.drop_field(path)
        return ()
    if len(value) > MAX_LIMITATIONS:
        state.drop_field(path)
        return ()
    normalized_limitations: list[str] = []
    for index, item in enumerate(value):
        text = _recovery_text(item, f"{path}[{index}]", state)
        if text is not None:
            normalized_limitations.append(text)
    return tuple(normalized_limitations)


def _recovery_model_sources(
    value: object,
    path: str,
    state: _FinalizationRecoveryState,
) -> tuple[tuple[tuple[str, SourceRelation], ...], bool]:
    """逐条解析 semantic source handle，坏 citation 只影响它自己。"""

    if not isinstance(value, list):
        state.drop_field(path)
        return (), True
    if len(value) > MAX_SOURCES_PER_EVIDENCE:
        state.drop_field(path)
        return (), True
    sources: list[tuple[str, SourceRelation]] = []
    had_invalid_source = False
    for index, raw_source in enumerate(value):
        source_path = f"{path}[{index}]"
        try:
            sources.append(_parse_model_source(raw_source, source_path))
        except AnswerFinalizationError:
            had_invalid_source = True
            state.drop_field(source_path)
    return tuple(sources), had_invalid_source


def _recovery_full_sources(
    value: object,
    path: str,
    state: _FinalizationRecoveryState,
) -> tuple[tuple[EvidenceSource, ...], bool]:
    """解析旧 full Artifact 的 source；模型提供的显示 metadata 仍不会被采用。"""

    if not isinstance(value, list):
        state.drop_field(path)
        return (), True
    if len(value) > MAX_SOURCES_PER_EVIDENCE:
        state.drop_field(path)
        return (), True
    sources: list[EvidenceSource] = []
    had_invalid_source = False
    for index, raw_source in enumerate(value):
        source_path = f"{path}[{index}]"
        if not isinstance(raw_source, Mapping):
            had_invalid_source = True
            state.drop_field(source_path)
            continue
        try:
            relation = raw_source["relation"]
            reference = _parse_source(raw_source["source"], f"{source_path}.source")
            sources.append(EvidenceSource(relation, reference))
        except (KeyError, AnswerFinalizationError, AnswerContractError):
            had_invalid_source = True
            state.drop_field(source_path)
    return tuple(sources), had_invalid_source


def _recovery_sufficiency(
    value: object,
    path: str,
    state: _FinalizationRecoveryState,
) -> EvidenceSufficiency | None:
    """读取 evidence 的有限枚举；不合法时放弃局部 evidence metadata。"""

    if isinstance(value, str) and value in {"sufficient", "partial", "insufficient"}:
        return value  # type: ignore[return-value]
    state.drop_field(path)
    return None


def _recovery_blocks(
    payload: Mapping[str, Any],
    state: _FinalizationRecoveryState,
) -> tuple[AnswerContentBlock, ...]:
    """从 full Artifact payload 保留可读 content block，并丢弃非法局部 block。"""

    raw_blocks: object = payload.get("content_blocks")
    if raw_blocks is None and "answer" in payload:
        raw_blocks = [{"block_id": "answer", "text": payload.get("answer")}]
    if not isinstance(raw_blocks, list):
        state.drop_field("content_blocks")
        raw_answer = _recovery_text(payload.get("answer"), "answer", state)
        return () if raw_answer is None else (AnswerContentBlock("answer", raw_answer),)
    if len(raw_blocks) > MAX_CONTENT_BLOCKS:
        state.drop_field("content_blocks")
        raw_blocks = raw_blocks[:MAX_CONTENT_BLOCKS]
    blocks: list[AnswerContentBlock] = []
    for index, raw_block in enumerate(raw_blocks):
        path = f"content_blocks[{index}]"
        if not isinstance(raw_block, Mapping):
            state.drop_field(path)
            continue
        block_id = _recovery_text(raw_block.get("block_id"), f"{path}.block_id", state)
        text = _recovery_text(raw_block.get("text"), f"{path}.text", state)
        if block_id is None or text is None:
            continue
        try:
            blocks.append(AnswerContentBlock(block_id, text))
        except AnswerContractError:
            state.drop_field(path)
    return tuple(blocks)


def _recovery_candidate_artifact(
    payload: Mapping[str, Any],
    *,
    has_tool_results: bool,
    state: _FinalizationRecoveryState,
) -> tuple[AnswerArtifact, tuple[tuple[str, str], ...]]:
    """从 semantic claims 构建 host-owned identity，返回待 hydrate 的 binding 目标。"""

    raw_claims = payload.get("claims")
    if not isinstance(raw_claims, list):
        state.drop_field("claims")
        fallback = _recovery_text(payload.get("answer"), "answer", state)
        if fallback is None:
            raise _model_error("INVALID_MODEL_CANDIDATE", "model answer contains no readable claim")
        fallback_blocks = (AnswerContentBlock("answer", fallback),)
        limitations = _recovery_limitations(payload.get("limitations", []), "limitations", state)
        return AnswerArtifact(content_blocks=fallback_blocks, limitations=limitations), ()
    if len(raw_claims) > MAX_CONTENT_BLOCKS:
        state.drop_field("claims")
        raw_claims = raw_claims[:MAX_CONTENT_BLOCKS]

    blocks: list[AnswerContentBlock] = []
    evidence: list[EvidenceItem] = []
    binding_targets: list[tuple[str, str]] = []
    answer_limitations = _recovery_limitations(payload.get("limitations", []), "limitations", state)
    for index, raw_claim in enumerate(raw_claims):
        path = f"claims[{index}]"
        if not isinstance(raw_claim, Mapping):
            state.drop_field(path)
            continue
        text = _recovery_text(raw_claim.get("text"), f"{path}.text", state)
        if text is None:
            continue
        block_id = f"claim-{len(blocks) + 1}"
        blocks.append(AnswerContentBlock(block_id, text))
        claim_limitations = _recovery_limitations(
            raw_claim.get("limitations", []),
            f"{path}.limitations",
            state,
        )
        raw_sources = raw_claim.get("sources", [])
        model_sources, had_invalid_sources = _recovery_model_sources(
            raw_sources,
            f"{path}.sources",
            state,
        )
        finding = _recovery_text(raw_claim.get("finding"), f"{path}.finding", state)
        criterion = _recovery_text(raw_claim.get("criterion"), f"{path}.criterion", state)
        sufficiency = _recovery_sufficiency(raw_claim.get("sufficiency"), f"{path}.sufficiency", state)
        if not has_tool_results:
            answer_limitations = tuple((*answer_limitations, *claim_limitations))[:MAX_LIMITATIONS]
            continue
        if finding is None or criterion is None or sufficiency is None:
            if model_sources or had_invalid_sources:
                state.drop_citation()
            continue
        evidence_id = f"e{len(evidence) + 1}"
        evidence.append(
            EvidenceItem(
                evidence_id=evidence_id,
                finding=finding,
                criterion=criterion,
                sufficiency=sufficiency,
                sources=tuple(
                    EvidenceSource(relation, SourceHandleReference(source_id))
                    for source_id, relation in model_sources
                ),
                limitations=claim_limitations,
            )
        )
        if had_invalid_sources:
            state.drop_citation_for_evidence(evidence_id)
        binding_targets.append((block_id, evidence_id))

    if not blocks:
        raise _model_error("INVALID_MODEL_CANDIDATE", "model answer contains no readable claim", "claims")
    return (
        AnswerArtifact(
            content_blocks=tuple(blocks),
            evidence_items=tuple(evidence),
            limitations=answer_limitations,
        ),
        tuple(binding_targets),
    )


def _recovery_full_artifact(
    payload: Mapping[str, Any],
    *,
    has_tool_results: bool,
    state: _FinalizationRecoveryState,
) -> tuple[AnswerArtifact, tuple[tuple[str, str], ...]]:
    """从历史 full Artifact contract 保留可读内容，再独立过滤 binding。"""

    blocks = _recovery_blocks(payload, state)
    if not blocks:
        raise _model_error("INVALID_ANSWER_ARTIFACT", "final answer contains no readable content")
    raw_items = payload.get("evidence_items", [])
    if not isinstance(raw_items, list):
        state.drop_field("evidence_items")
        raw_items = []
    if len(raw_items) > MAX_EVIDENCE_ITEMS:
        state.drop_field("evidence_items")
        raw_items = raw_items[:MAX_EVIDENCE_ITEMS]
    evidence: list[EvidenceItem] = []
    for index, raw_item in enumerate(raw_items):
        path = f"evidence_items[{index}]"
        if not isinstance(raw_item, Mapping):
            state.drop_field(path)
            continue
        evidence_id = _recovery_text(raw_item.get("evidence_id"), f"{path}.evidence_id", state)
        finding = _recovery_text(raw_item.get("finding"), f"{path}.finding", state)
        criterion = _recovery_text(raw_item.get("criterion"), f"{path}.criterion", state)
        sufficiency = _recovery_sufficiency(raw_item.get("sufficiency"), f"{path}.sufficiency", state)
        if evidence_id is None or finding is None or criterion is None or sufficiency is None:
            continue
        sources, had_invalid_sources = _recovery_full_sources(
            raw_item.get("sources", []),
            f"{path}.sources",
            state,
        )
        limitations = _recovery_limitations(raw_item.get("limitations", []), f"{path}.limitations", state)
        try:
            evidence.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    finding=finding,
                    criterion=criterion,
                    sufficiency=sufficiency,
                    sources=sources,
                    limitations=limitations,
                )
            )
            if had_invalid_sources:
                state.drop_citation_for_evidence(evidence_id)
        except AnswerContractError:
            state.drop_field(path)

    raw_bindings = payload.get("citation_bindings", [])
    if not isinstance(raw_bindings, list):
        state.drop_field("citation_bindings")
        raw_bindings = []
    if len(raw_bindings) > MAX_CITATION_BINDINGS:
        state.drop_field("citation_bindings")
        raw_bindings = raw_bindings[:MAX_CITATION_BINDINGS]
    binding_targets: list[tuple[str, str]] = []
    binding_blocks: set[str] = set()
    for index, raw_binding in enumerate(raw_bindings):
        path = f"citation_bindings[{index}]"
        if not isinstance(raw_binding, Mapping):
            state.drop_citation()
            state.drop_field(path)
            continue
        block_id = _recovery_text(raw_binding.get("content_block_id"), f"{path}.content_block_id", state)
        raw_ids = raw_binding.get("evidence_ids")
        if block_id is None or not isinstance(raw_ids, list) or not raw_ids:
            state.drop_citation()
            state.drop_field(path)
            continue
        if block_id in binding_blocks:
            state.drop_citation()
            state.drop_field(path)
            continue
        if len(raw_ids) > MAX_EVIDENCE_ITEMS:
            state.drop_citation()
            state.drop_field(path)
            continue
        for raw_id in raw_ids:
            evidence_id = _recovery_text(raw_id, f"{path}.evidence_ids", state)
            if evidence_id is not None:
                binding_targets.append((block_id, evidence_id))
        binding_blocks.add(block_id)
    limitations = _recovery_limitations(payload.get("limitations", []), "limitations", state)
    return (
        AnswerArtifact(
            content_blocks=blocks,
            evidence_items=tuple(evidence),
            limitations=limitations,
        ),
        tuple(binding_targets),
    )


def _hydrate_recovered_evidence(
    evidence: tuple[EvidenceItem, ...],
    *,
    run_id: str | None,
    tool_results: tuple[ToolResultRecord, ...],
    scope: ExecutionScope,
    accepted_run_ids: tuple[str, ...],
    state: _FinalizationRecoveryState,
) -> tuple[EvidenceItem, ...]:
    """逐 source hydrate；recoverable locator 错误只丢弃当前 citation。"""

    if not tool_results:
        return evidence
    if run_id is None or not run_id:
        raise _model_error("INVALID_PROVENANCE", "current run identity is unavailable")
    records = _record_index(tool_results, run_id, accepted_run_ids)
    finalized_items: list[EvidenceItem] = []
    for item_index, item in enumerate(evidence):
        sources: list[EvidenceSource] = []
        for source_index, source in enumerate(item.sources):
            source_path = f"evidence_items[{item_index}].sources[{source_index}].source"
            try:
                sources.append(
                    _finalize_source(
                        source,
                        run_id=run_id,
                        accepted_run_ids=accepted_run_ids,
                        records=records,
                        scope=scope,
                        source_path=source_path,
                    )
                )
            except AnswerFinalizationError as exc:
                if exc.code in _FATAL_GRACEFUL_CODES:
                    raise
                state.drop_citation_for_evidence(item.evidence_id)
                state.drop_field(source_path)
        state.validated_citation_count += len(sources)
        finalized_items.append(replace(item, sources=tuple(sources)))
    return tuple(finalized_items)


def _recovery_error_result(exc: AnswerFinalizationError) -> FinalizationResult:
    """把 fatal finalization failure 转成稳定的 failed typed result。"""

    diagnostics = FinalizationDiagnostics(
        status="failed",
        user_answer_preserved=False,
        error_code=exc.code,
        error_path=exc.path,
        degradation_codes=("finalization_failed",),
    )
    return FinalizationResult(
        artifact=None,
        diagnostics=diagnostics,
        error=FinalizationErrorInfo(exc.code, exc.message, exc.path),
    )


def finalize_answer_gracefully(
    output: str,
    *,
    run_id: str | None,
    tool_results: tuple[ToolResultRecord, ...],
    scope: ExecutionScope,
    accepted_run_ids: tuple[str, ...] = (),
) -> FinalizationResult:
    """先走 strict finalizer，局部错误才进入有界 deterministic recovery。"""

    try:
        # 正常路径完全复用既有 strict validation，避免 graceful 路径改变合法答案语义。
        artifact = finalize_answer(
            output,
            run_id=run_id,
            tool_results=tool_results,
            scope=scope,
            accepted_run_ids=accepted_run_ids,
        )
    except AnswerFinalizationError as strict_error:
        # trusted provenance/scope/empty answer 不是可恢复的局部 schema 问题。
        if strict_error.code in _FATAL_GRACEFUL_CODES or strict_error.code == "INVALID_FINAL_OUTPUT":
            return _recovery_error_result(strict_error)
        state = _FinalizationRecoveryState()
        state.add_code("strict_validation_failed")
        try:
            normalized_output = output.strip() if isinstance(output, str) else output
            if not isinstance(normalized_output, str) or not normalized_output:
                return _recovery_error_result(strict_error)
            if normalized_output.startswith("{"):
                try:
                    decoded = json.loads(normalized_output)
                except json.JSONDecodeError:
                    # JSON-like malformed payload 没有可靠答案边界，继续显式 failed。
                    return _recovery_error_result(strict_error)
                if not isinstance(decoded, Mapping):
                    return _recovery_error_result(strict_error)
                if "claims" in decoded:
                    recovered, binding_targets = _recovery_candidate_artifact(
                        decoded,
                        has_tool_results=bool(tool_results),
                        state=state,
                    )
                else:
                    recovered, binding_targets = _recovery_full_artifact(
                        decoded,
                        has_tool_results=bool(tool_results),
                        state=state,
                    )
            else:
                if normalized_output.startswith(("[", "```")):
                    return _recovery_error_result(strict_error)
                # 非结构化但可读的正文可以保留；Tool-backed citation 不会被伪造。
                recovered = AnswerArtifact(
                    content_blocks=(AnswerContentBlock("answer", normalized_output),)
                )
                binding_targets = ()
            hydrated = _hydrate_recovered_evidence(
                recovered.evidence_items,
                run_id=run_id,
                tool_results=tool_results,
                scope=scope,
                accepted_run_ids=accepted_run_ids,
                state=state,
            )
            # Tool-backed evidence 没有任何可信 source 时也不能留在 Artifact 中，避免形成无 citation 的伪 evidence。
            usable_evidence = (
                tuple(item for item in hydrated if item.sources)
                if tool_results
                else hydrated
            )
            valid_evidence_ids = {
                item.evidence_id for item in usable_evidence if item.sources
            }
            block_ids = {block.block_id for block in recovered.content_blocks}
            binding_evidence_ids: dict[str, list[str]] = {}
            for block_id, evidence_id in binding_targets:
                if block_id not in block_ids:
                    state.drop_citation()
                    continue
                if evidence_id not in valid_evidence_ids:
                    # source hydrate 已经计过的 Evidence 不再为同一 citation 重复计数。
                    if evidence_id not in state.dropped_source_evidence_ids:
                        state.drop_citation()
                    continue
                targets = binding_evidence_ids.setdefault(block_id, [])
                if evidence_id not in targets:
                    targets.append(evidence_id)
            bindings: list[CitationBinding] = []
            for block_id, evidence_ids in binding_evidence_ids.items():
                try:
                    bindings.append(CitationBinding(block_id, tuple(evidence_ids)))
                except AnswerContractError:
                    state.drop_citation()
            recovered = replace(
                recovered,
                evidence_items=usable_evidence,
                citation_bindings=tuple(bindings),
            )
        except AnswerFinalizationError as recovery_error:
            # recovery 仍遇到可信边界错误时不做第二层吞错，直接返回 fatal。
            return _recovery_error_result(recovery_error)
        except AnswerContractError:
            # 只能是 recovery 自身无法形成 bounded artifact；不给调用方伪造 partial。
            return _recovery_error_result(
                _model_error("INVALID_ANSWER_ARTIFACT", "finalization recovery produced no valid artifact")
            )
        diagnostics = FinalizationDiagnostics(
            status="degraded",
            user_answer_preserved=True,
            error_code=strict_error.code,
            error_path=strict_error.path,
            degradation_codes=tuple(state.degradation_codes),
            dropped_field_count=state.dropped_field_count,
            dropped_field_paths=tuple(state.dropped_field_paths),
            dropped_citation_count=state.dropped_citation_count,
            normalization_count=state.normalization_count,
            validated_citation_count=state.validated_citation_count,
        )
        return FinalizationResult(artifact=recovered, diagnostics=diagnostics)
    else:
        # strict success 只补充计数，不重新解析或重新 hydrate trusted source。
        validated_citations = sum(len(item.sources) for item in artifact.evidence_items)
        diagnostics = FinalizationDiagnostics(
            status="valid",
            user_answer_preserved=True,
            validated_citation_count=validated_citations,
        )
        return FinalizationResult(artifact=artifact, diagnostics=diagnostics)
