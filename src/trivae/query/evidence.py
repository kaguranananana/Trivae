"""Evidence、Citation 与 Answer Finalization 的 Trivae-owned contract。

本模块只保存 bounded 的业务投影，不保存 SDK raw item、SQLite connection 或原始数据库转储。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping, TypeAlias
from urllib.parse import urlsplit

from trivae.capabilities.contracts import ExecutionScope, ToolEnvelope, format_timestamp_utc
from trivae.config.limits import (
    DEFAULT_TOOL_RESULT_TOKEN_BUDGET,
    MAX_MESSAGE_CONTENT_PAGE_CHARS,
    MAX_STRUCTURED_RESULT_ITEMS,
    MAX_TOOL_RESULT_MESSAGE_ITEMS,
)
from trivae.retrieval.context import MessageContextResult
from trivae.retrieval.identity import FindMembersResult
from trivae.retrieval.semantic.contracts import SemanticRetrievalResult
from trivae.retrieval.sql import SchemaResult, SQLQueryResult
from trivae.retrieval.structured import (
    Coverage,
    ForwardProvenance,
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
# message provenance 的 item ceiling 属于 Tool Result record 自身，不绑定任何 retrieval strategy。
MAX_TOOL_RESULT_STRUCTURED_ITEMS = MAX_STRUCTURED_RESULT_ITEMS
MAX_VALUE_NESTING = 6
MAX_SOURCE_URLS = 12
MAX_SOURCE_URL_CHARS = 2_000
MAX_MODEL_MESSAGE_CHARS = 600
# 公共默认值在每个有消息的模型结果中显式声明，避免逐条重复占用证据预算。
MODEL_MESSAGE_DEFAULTS: dict[str, object] = {"message_type": "text", "urls": (), "content_truncated": False}
MODEL_TOKEN_CHAR_RATIO = 3

_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'，。；：！？、（）【】《》“”‘’\u3400-\u4dbf\u4e00-\u9fff]+",
    re.IGNORECASE,
)
_URL_TRAILING_PUNCTUATION = ".,;:!"
_URL_BRACKET_PAIRS = {
    ")": "(",
    "]": "[",
    "}": "{",
}
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


def _normalize_time_range_snapshot(
    name: str,
    value: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """校验 Host 写入的时间事实，并保留可供 renderer/replay 使用的字段。"""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise AnswerContractError(f"{name} must be a mapping or None")
    _check_bounded_value(name, value)
    normalized = dict(value)
    kind = normalized.get("kind")
    if kind not in {"relative", "absolute"}:
        raise AnswerContractError(f"{name}.kind must be relative or absolute")
    for field_name in ("resolved_start_timestamp", "resolved_end_timestamp"):
        if field_name not in normalized:
            raise AnswerContractError(f"{name}.{field_name} is required")

    def optional_timestamp(field_name: str) -> int | None:
        """把 Host 时间边界收窄为可比较的整数类型。"""

        timestamp = normalized[field_name]
        if timestamp is not None and (isinstance(timestamp, bool) or not isinstance(timestamp, int)):
            raise AnswerContractError(f"{name}.{field_name} must be an integer or None")
        return timestamp

    start_timestamp = optional_timestamp("resolved_start_timestamp")
    end_timestamp = optional_timestamp("resolved_end_timestamp")
    if (
        isinstance(start_timestamp, int)
        and not isinstance(start_timestamp, bool)
        and isinstance(end_timestamp, int)
        and not isinstance(end_timestamp, bool)
        and start_timestamp > end_timestamp
    ):
        raise AnswerContractError(f"{name} interval is reversed")
    for field_name in ("anchor_utc", "resolved_start_utc", "resolved_end_utc", "resolved_interval_utc"):
        text = normalized.get(field_name)
        if text is not None and (not isinstance(text, str) or not text.strip()):
            raise AnswerContractError(f"{name}.{field_name} must be non-empty text or None")
    return normalized


def _normalize_retrieval_coverage(
    name: str,
    value: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """校验最终 Artifact 中的 recent coverage，保证 partial 事实可直接回放。"""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise AnswerContractError(f"{name} must be a mapping or None")
    _check_bounded_value(name, value)
    normalized = dict(value)
    status = normalized.get("status")
    if status not in {"complete", "partial"}:
        raise AnswerContractError(f"{name}.status must be complete or partial")
    basis = normalized.get("basis")
    if not isinstance(basis, str) or not basis.strip():
        raise AnswerContractError(f"{name}.basis must be non-empty text")
    if normalized.get("unit") != "message":
        raise AnswerContractError(f"{name}.unit must be message")
    covered_units = normalized.get("covered_units")
    eligible_units = normalized.get("eligible_units")
    retrieved_count = normalized.get("retrieved_count")
    for field_name, field_value in (
        ("covered_units", covered_units),
        ("eligible_units", eligible_units),
        ("retrieved_count", retrieved_count),
    ):
        if isinstance(field_value, bool) or not isinstance(field_value, int):
            raise AnswerContractError(f"{name}.{field_name} must be a non-negative integer")
        if field_value < 0:
            raise AnswerContractError(f"{name}.{field_name} must be a non-negative integer")
    assert isinstance(covered_units, int)
    assert isinstance(eligible_units, int)
    assert isinstance(retrieved_count, int)
    if covered_units > eligible_units:
        raise AnswerContractError(f"{name}.covered_units cannot exceed eligible_units")
    if retrieved_count > covered_units:
        raise AnswerContractError(f"{name}.retrieved_count cannot exceed covered_units")
    has_more = normalized.get("has_more")
    if not isinstance(has_more, bool):
        raise AnswerContractError(f"{name}.has_more must be a boolean")
    if has_more != (status == "partial"):
        raise AnswerContractError(f"{name}.status and has_more disagree")
    if status == "complete" and covered_units != eligible_units:
        raise AnswerContractError(f"{name}.complete coverage must cover all eligible messages")
    return normalized


def _trim_url_candidate(candidate: str) -> str:
    """只裁掉句末标点和不成对的 Markdown 外层括号。"""

    trimmed = candidate
    while trimmed:
        # 先处理明确的句末标点，避免它阻挡后续的括号边界判断。
        punctuation_trimmed = trimmed.rstrip(_URL_TRAILING_PUNCTUATION)
        if punctuation_trimmed != trimmed:
            trimmed = punctuation_trimmed
            continue

        # URL 内部的成对括号属于地址本身，只有多出来的右括号才是 Markdown 外层括号。
        closing = trimmed[-1]
        opening = _URL_BRACKET_PAIRS.get(closing)
        if opening is None or trimmed.count(closing) <= trimmed.count(opening):
            break
        trimmed = trimmed[:-1]
    return trimmed


def _is_valid_http_url(url: str) -> bool:
    """校验 URL 的协议、主机、端口和 percent escape，拒绝模糊候选。"""

    # URL 中的百分号必须后跟两个十六进制字符，避免把坏编码写入 trusted snapshot。
    if re.search(r"%(?![0-9A-Fa-f]{2})", url):
        return False

    try:
        # urlsplit 负责拆分标准 URL 结构，避免手写规则遗漏 netloc 边界。
        parsed = urlsplit(url)
        # hostname 属性会触发 IPv6/非法主机字符校验，port 属性会触发非法端口校验。
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False

    # 只有 HTTP(S) 且同时存在非空 netloc/hostname 的候选才进入来源列表。
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc) and bool(hostname)


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
                # 扫描器只负责找候选，完整边界和合法性在进入 seen 之前统一确认。
                url = _trim_url_candidate(match)
                if (
                    not url
                    or len(url) > MAX_SOURCE_URL_CHARS
                    or url in seen
                    or not _is_valid_http_url(url)
                ):
                    continue
                # 只有已经通过校验的 canonical URL 才占用去重集合和数量上限。
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


def _validate_content_range(offset: int, total_chars: int | None) -> None:
    """字符范围是公开续读契约，拒绝非整数和负位置。"""
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise AnswerContractError("content offset must be a non-negative integer")
    if total_chars is not None and (
        isinstance(total_chars, bool) or not isinstance(total_chars, int) or total_chars < offset
    ):
        raise AnswerContractError("content total chars must be an integer no smaller than offset")


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
    # 合并转发保留 occurrence 位置与原始时间，timestamp_ms 仍是当前群转发时间。
    forward: ForwardProvenance | None = None
    unexpanded_forward_paths: tuple[str, ...] = ()
    # 昵称可重复，内部发送者的导出身份必须随可信快照一起持久化。
    sender_platform_id: str | None = None
    sender_uin: str | None = None
    # 引用卡片仍是短摘录，但必须定位到实际读到的正文段，而不是总回到开头。
    excerpt_offset: int = 0
    content_total_chars: int | None = None

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
        if self.forward is not None and not isinstance(self.forward, ForwardProvenance):
            raise AnswerContractError("forward must be a ForwardProvenance or None")
        if not isinstance(self.unexpanded_forward_paths, tuple) or any(
            not isinstance(path, str) or not path for path in self.unexpanded_forward_paths
        ):
            raise AnswerContractError("unexpanded_forward_paths must contain non-empty paths")
        for name in ("sender_platform_id", "sender_uin"):
            object.__setattr__(self, name, _optional_text(name, getattr(self, name), max_chars=512))
        _validate_content_range(self.excerpt_offset, self.content_total_chars)


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
class RecentRetrievalWindow:
    """Host 派生的一个独立 recent 窗口及其覆盖事实。"""

    resolved_time_range: Mapping[str, object]
    retrieval_coverage: Mapping[str, object] | None

    def __post_init__(self) -> None:
        # 复用既有时间校验，保留每窗原始半开边界而不扩大或拼接窗口。
        time_range = _normalize_time_range_snapshot("window.resolved_time_range", self.resolved_time_range)
        if time_range is None:
            raise AnswerContractError("recent window requires a resolved time range")
        object.__setattr__(self, "resolved_time_range", time_range)
        # 覆盖状态只属于当前窗口，不能把不同窗口的计数相加。
        object.__setattr__(
            self,
            "retrieval_coverage",
            _normalize_retrieval_coverage(
                "window.retrieval_coverage",
                self.retrieval_coverage,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Trace 与持久化共用同一窗口事实投影。"""

        return {
            "resolved_time_range": dict(self.resolved_time_range),
            "retrieval_coverage": None if self.retrieval_coverage is None else dict(self.retrieval_coverage),
        }


@dataclass(frozen=True)
class AnswerArtifact:
    """最终对外暴露的结构化回答事实载体。"""

    content_blocks: tuple[AnswerContentBlock, ...]
    citation_bindings: tuple[CitationBinding, ...] = ()
    evidence_items: tuple[EvidenceItem, ...] = ()
    limitations: tuple[str, ...] = ()
    # 时间范围由 Host 从当前 Tool Result 派生，模型不能伪造或自行换算。
    resolved_time_range: Mapping[str, object] | None = None
    # retrieval coverage 同样由 Host 派生，避免持久化 Artifact 丢失 partial/complete 事实。
    retrieval_coverage: Mapping[str, object] | None = None
    # 多窗查询逐窗保存事实；原有单值字段仅描述唯一窗口。
    retrieval_windows: tuple[RecentRetrievalWindow, ...] = ()

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
        object.__setattr__(
            self,
            "resolved_time_range",
            _normalize_time_range_snapshot("resolved_time_range", self.resolved_time_range),
        )
        object.__setattr__(
            self,
            "retrieval_coverage",
            _normalize_retrieval_coverage("retrieval_coverage", self.retrieval_coverage),
        )
        if not isinstance(self.retrieval_windows, tuple) or any(
            not isinstance(window, RecentRetrievalWindow) for window in self.retrieval_windows
        ):
            raise AnswerContractError("retrieval_windows must contain RecentRetrievalWindow values")
        if len(self.retrieval_windows) > 1 and (
            self.resolved_time_range is not None or self.retrieval_coverage is not None
        ):
            raise AnswerContractError("multiple retrieval windows cannot have single-window facts")
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


NO_RESULT_KIND = "no_result"


@dataclass(frozen=True)
class ModelAnswerNoResult:
    """zero-result final candidate：成功查询得到空集合时的合法 final 形态。

    只有 Host 能从当前 Tool Result Records 验证“确无可引用数据”时才被接受，
    防止它演变为无 evidence factual claim 的 citation bypass。
    """

    summary: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", _text("no_result summary", self.summary, max_chars=MAX_ANSWER_CHARS))
        object.__setattr__(self, "limitations", _limitations("no_result limitations", self.limitations))


def tool_results_have_result_facts(tool_results: tuple[ToolResultRecord, ...]) -> bool:
    """Host 判定当前 run 是否存在任何可引用的检索事实。

    message items 或非 schema 的 structured row（SQL rows/aggregate buckets/member
    candidates）都算事实；schema inspection tables[] 只是 metadata，不构成事实。
    这是 zero-result 候选的唯一放行依据，模型无法通过参数影响。
    """

    for record in tool_results:
        if record.message_items:
            return True
        if any(
            item.locator_kind == "row" and not item.locator.startswith("tables[")
            for item in record.structured_items
        ):
            return True
    return False


# 只有这些 Agent-facing retrieval 工具的成功空结果才能为 kind=no_result 提供
# positive proof；get_schema/find_members 等不产生候选集合完整性的证据。
_RETRIEVAL_TOOL_NAMES = frozenset(
    {
        "lexical_search",
        "semantic_search",
        "search_messages",
        "get_recent_messages",
        "get_message_context",
    }
)

# 这些 limitation 信号表示该次 retrieval 未能"完整确定地返回空集合"：
# 执行失败、部分覆盖、未知 coverage、被截断的结果集都不能支持"范围内没有数据"。
_INCOMPLETE_ZERO_SIGNALS = frozenset(
    {
        "tool_result_partial",
        "retrieval_partial",
        "retrieval_truncated",
        "unexpanded_forward_content",
    }
)


def _is_complete_empty_retrieval_record(record: ToolResultRecord) -> bool:
    """单个 retrieval record 是否构成“明确成功且完整确定为空”的证据。"""

    if record.tool_name not in _RETRIEVAL_TOOL_NAMES:
        return False
    # error/partial envelope 一律不构成 proof；error_code 同时记录在 limitations。
    if record.status != "ok":
        return False
    for limitation in record.limitations:
        if limitation in _INCOMPLETE_ZERO_SIGNALS or limitation.startswith("tool_error:"):
            return False
        if limitation.startswith("coverage:") and limitation != "coverage:complete":
            return False
    return True


def _is_auxiliary_sql_aggregate(
    record: ToolResultRecord,
    *,
    start_timestamp: int,
    end_timestamp: int,
) -> bool:
    """区分 SQL 统计行和实际候选消息；零结果仍由完整时间窗检索证明。"""

    if record.tool_name != "execute_sql" or record.status != "ok" or record.limitations:
        return False
    query = record.query_scope_snapshot.get("query")
    sql = query.get("sql") if isinstance(query, Mapping) else None
    # SQL row 本身仍是可引用事实；这里只允许以聚合函数开头的数值统计作为辅助诊断。
    if not isinstance(sql, str) or re.match(r"^\s*SELECT\s+(COUNT|MIN|MAX)\s*\(", sql, re.I) is None:
        return False
    for item in record.structured_items:
        if item.locator_kind != "row" or not isinstance(item.value_snapshot, Mapping):
            return False
        values = tuple(item.value_snapshot.values())
        # 文本/消息列不是纯统计，不能绕过 no_result 的候选事实拒绝规则。
        if any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))) for value in values):
            return False
        # 同一时间窗的正计数与零条检索相冲突，必须显式拒绝而非猜测哪边正确。
        if str(start_timestamp) in sql and str(end_timestamp) in sql:
            if any(isinstance(value, (int, float)) and value > 0 for value in values):
                return False
    return True


def has_verified_zero_result_evidence(tool_results: tuple[ToolResultRecord, ...]) -> bool:
    """kind=no_result 的 positive-proof 判定。

    必须同时满足：
    1. 至少一次相关 retrieval 调用存在记录；
    2. 所有相关 retrieval 调用都 status=ok 且无 partial/error/incomplete coverage/
       truncation 信号（任何一条失败路径都会让"没有数据"结论不完备）；
    3. 当前 run 无候选消息或普通结构化数据行；明确时间窗的完整零条证明可与
       数值型 SQL 聚合统计并存，统计行本身仍是可引用事实。
    """

    retrieval_records = [
        record for record in tool_results if record.tool_name in _RETRIEVAL_TOOL_NAMES
    ]
    if not retrieval_records:
        return False
    if any(
        not _is_complete_empty_retrieval_record(record)
        for record in retrieval_records
    ):
        return False
    if not tool_results_have_result_facts(tool_results):
        return True
    # get_recent_messages 对明确时间窗返回 complete/0 时，SQL 的聚合统计行不表示
    # 该时间窗存在消息。其他检索和任意消息/非聚合行仍按原契约拒绝 no_result。
    recent = next(
        (
            record for record in retrieval_records
            if record.tool_name == "get_recent_messages"
            and record.query_scope_snapshot.get("total_hits") == 0
            and isinstance(record.query_scope_snapshot.get("resolved_time_range"), Mapping)
        ),
        None,
    )
    if recent is None or any(record.message_items for record in tool_results):
        return False
    start = recent.query_scope_snapshot.get("start_timestamp")
    end = recent.query_scope_snapshot.get("end_timestamp")
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    return all(
        record.tool_name == "get_schema"
        or not record.structured_items
        or _is_auxiliary_sql_aggregate(record, start_timestamp=start, end_timestamp=end)
        for record in tool_results
    )


def parse_model_no_result_candidate(output: str) -> ModelAnswerNoResult:
    """解析 kind=no_result 的显式 zero-result final contract。"""

    if not isinstance(output, str) or not output.strip():
        raise _model_error("INVALID_FINAL_OUTPUT", "final answer must be non-empty text")
    try:
        decoded = json.loads(output.strip())
    except json.JSONDecodeError as exc:
        raise _model_error("INVALID_MODEL_CANDIDATE", "no-result answer is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise _model_error("INVALID_MODEL_CANDIDATE", "no-result answer must be an object")
    if decoded.get("kind") != NO_RESULT_KIND:
        raise _model_error("INVALID_MODEL_CANDIDATE", f"answer kind must be {NO_RESULT_KIND}", "kind")
    if "claims" in decoded:
        # 不允许 no-result 与 claims 形态混合（即使空数组）：有数据时必须走正常 citation contract。
        raise _model_error(
            "INVALID_MODEL_CANDIDATE",
            f"{NO_RESULT_KIND} answer must not carry a claims field",
            "claims",
        )
    summary_value = decoded.get("summary")
    if not isinstance(summary_value, str):
        raise _model_error("INVALID_MODEL_CANDIDATE", "no-result answer requires a summary", "summary")
    try:
        return ModelAnswerNoResult(
            summary=summary_value,
            limitations=tuple(decoded.get("limitations") or ()),
        )
    except (AnswerContractError, TypeError) as exc:
        raise _model_error("INVALID_MODEL_CANDIDATE", str(exc)) from exc


def compile_model_no_result_answer(candidate: ModelAnswerNoResult) -> AnswerArtifact:
    """把 zero-result candidate 编译为单一可读 block；无 evidence/citation 是契约语义。"""

    return AnswerArtifact(
        content_blocks=(AnswerContentBlock("answer", candidate.summary),),
        limitations=candidate.limitations,
    )


@dataclass(frozen=True)
class ToolMessageItem:
    """Tool Result 中一个可引用的 bounded canonical message projection。"""

    result_item_id: str
    message: MessageProjection
    content_truncated: bool = False
    urls: tuple[str, ...] = ()
    is_hit: bool = True
    content_offset: int = 0
    content_total_chars: int | None = None

    def __post_init__(self) -> None:
        # 读取页与引用摘录分离；record允许有界正文页，搜索仍由builder保留短预览。
        object.__setattr__(self, "result_item_id", _text("result_item_id", self.result_item_id, max_chars=512))
        if not isinstance(self.message, MessageProjection):
            raise AnswerContractError("message must be a MessageProjection")
        if not isinstance(self.message.normalized_content, str):
            raise AnswerContractError("message normalized_content must be text")
        if len(self.message.normalized_content) > MAX_MESSAGE_CONTENT_PAGE_CHARS:
            raise AnswerContractError("tool message content must be bounded")
        _validate_content_range(self.content_offset, self.content_total_chars)
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
    content_page: Mapping[str, Any] | None = None,
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
        # 显式锚点的页边界由Capability从原文计算；其他消息保持搜索record的1000字边界。
        maximum, offset, total_chars = MAX_SAFE_EXCERPT_CHARS, 0, len(content)
        if content_page is not None and message.internal_message_id == content_page["message_id"]:
            maximum = MAX_MESSAGE_CONTENT_PAGE_CHARS
            offset, total_chars = content_page["offset"], content_page["total_chars"]
        # record只保存原文字符，省略号只在展示层生成，保证下一页偏移不会跨过一个未读字符。
        bounded_message = replace(message, normalized_content=content[:maximum])
        items.append(ToolMessageItem(
            f"message/{message.internal_message_id}", bounded_message,
            offset + len(bounded_message.normalized_content) < total_chars,
            urls, hit_ids is None or message.internal_message_id in hit_ids,
            content_offset=offset, content_total_chars=total_chars,
        ))
    return tuple(items)


def _semantic_literal_ids(data: SemanticRetrievalResult) -> set[str]:
    """只使用 Retrieval 已核验且实际返回的字面命中，统一来源与正文的保留优先级。"""

    literal_ids = data.metadata.details.get("literal_message_ids", ())
    if not isinstance(literal_ids, (tuple, list)):
        raise ToolResultProjectionError("semantic literal message identities must be a sequence")
    return set(literal_ids) & set(data.primary_message_ids)


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
        if isinstance(coverage, Coverage) and "unexpanded_forward_content" in coverage.known_gaps:
            # 即使命中本身完整，scope 内的其他空转发节点仍是回答完整性的真实限制。
            limitations.append("unexpanded_forward_content")
    return tuple(limitations)


def _record_time_range(record: ToolResultRecord) -> dict[str, object] | None:
    """读取 recent record 的 Host 时间事实，拒绝未经校验的任意映射。"""

    if record.tool_name != "get_recent_messages":
        return None
    raw_range = record.query_scope_snapshot.get("resolved_time_range")
    if raw_range is None:
        return None
    if not isinstance(raw_range, Mapping):
        raise _model_error("TIME_RANGE_MISMATCH", "recent tool result has an invalid resolved time range")
    time_range = _normalize_time_range_snapshot("tool result resolved_time_range", raw_range)
    assert time_range is not None
    # 独立窗口可以不同，但单条记录的解析边界必须与其实际查询边界一致。
    for boundary in ("start_timestamp", "end_timestamp"):
        if boundary in record.query_scope_snapshot and (
            record.query_scope_snapshot[boundary] != time_range[f"resolved_{boundary}"]
        ):
            raise _model_error("TIME_RANGE_MISMATCH", "recent resolved window disagrees with its query boundary")
    return time_range


def _recent_time_range_key(time_range: Mapping[str, object]) -> tuple[object, object]:
    """只按实际半开边界比较窗口，避免 relative/absolute 表示差异造成假冲突。"""

    return (
        time_range.get("resolved_start_timestamp"),
        time_range.get("resolved_end_timestamp"),
    )


def _group_recent_records(
    tool_results: tuple[ToolResultRecord, ...],
) -> tuple[tuple[dict[str, object], tuple[ToolResultRecord, ...]], ...]:
    """按真实半开边界分组，区分同窗分页与独立时间窗口。"""

    observed: dict[tuple[object, object], tuple[dict[str, object], list[ToolResultRecord]]] = {}
    unknown_with_facts = False
    for record in tool_results:
        if record.tool_name != "get_recent_messages":
            continue
        time_range = _record_time_range(record)
        if time_range is None:
            if record.message_items:
                unknown_with_facts = True
            continue
        # 同窗的相对/绝对表示可以不同，只按实际边界决定是否属于同一组。
        key = _recent_time_range_key(time_range)
        if key not in observed:
            observed[key] = (time_range, [])
        # 保留全部页和独立 root，交给已有覆盖汇总逻辑校验。
        observed[key][1].append(record)
    if observed and unknown_with_facts:
        raise _model_error(
            "TIME_RANGE_MISMATCH",
            "recent results mix a resolved window with an unresolved message window",
        )
    return tuple((time_range, tuple(records)) for time_range, records in observed.values())


def _recent_record_coverage(record: ToolResultRecord) -> dict[str, object] | None:
    """把一个 recent record 的页级 coverage 补成最终 Artifact 所需的完整快照。"""

    if record.tool_name != "get_recent_messages":
        return None
    raw_coverage = record.query_scope_snapshot.get("coverage")
    if raw_coverage is None:
        if record.message_items:
            raise _model_error(
                "COVERAGE_MISMATCH",
                "recent message result has messages but no coverage snapshot",
            )
        return None
    if not isinstance(raw_coverage, Mapping):
        raise _model_error("COVERAGE_MISMATCH", "recent message coverage snapshot is invalid")
    snapshot = record.query_scope_snapshot
    required_fields = ("total_hits", "retrieved_count", "has_more")
    if any(field_name not in snapshot for field_name in required_fields):
        raise _model_error(
            "COVERAGE_MISMATCH",
            "recent message result is missing page coverage facts",
        )
    retrieved_count = snapshot["retrieved_count"]
    total_hits = snapshot["total_hits"]
    has_more = snapshot["has_more"]
    if (
        isinstance(retrieved_count, bool)
        or not isinstance(retrieved_count, int)
        or retrieved_count != len(record.message_items)
    ):
        raise _model_error("COVERAGE_MISMATCH", "recent retrieved_count does not match message items")
    if isinstance(total_hits, bool) or not isinstance(total_hits, int) or total_hits < 0:
        raise _model_error("COVERAGE_MISMATCH", "recent total_hits is invalid")
    if not isinstance(has_more, bool):
        raise _model_error("COVERAGE_MISMATCH", "recent has_more is invalid")
    normalized = dict(raw_coverage)
    normalized["retrieved_count"] = retrieved_count
    normalized["has_more"] = has_more
    eligible_units = normalized.get("eligible_units")
    if eligible_units != total_hits:
        raise _model_error("COVERAGE_MISMATCH", "recent coverage eligible_units disagrees with total_hits")
    try:
        return _normalize_retrieval_coverage("recent retrieval coverage", normalized)
    except AnswerContractError as exc:
        raise _model_error("COVERAGE_MISMATCH", str(exc)) from exc


def _recent_window_coverage(
    tool_results: tuple[ToolResultRecord, ...],
) -> dict[str, object] | None:
    """仅在同一时间窗内汇总唯一消息数与最强 coverage 事实。"""

    observed: list[dict[str, object]] = []
    message_ids: set[str] = set()
    for record in tool_results:
        coverage = _recent_record_coverage(record)
        if coverage is None:
            continue
        observed.append(coverage)
        message_ids.update(item.message.internal_message_id for item in record.message_items)
    if not observed:
        return None

    first = observed[0]
    invariant_fields = ("basis", "unit", "eligible_units")
    for item in observed[1:]:
        if any(item[field_name] != first[field_name] for field_name in invariant_fields):
            raise _model_error("COVERAGE_MISMATCH", "recent pages disagree on coverage scope")

    # 同一时间窗允许多条独立 root 查询；后来的小样本不能覆盖此前已证明的完整 coverage。
    strongest_observation = observed[0]
    strongest_covered_units = strongest_observation["covered_units"]
    assert isinstance(strongest_covered_units, int)
    for item in observed[1:]:
        covered_units = item["covered_units"]
        assert isinstance(covered_units, int)
        # 相同 coverage 选择后出现的记录，让合法 continuation 末页仍提供最终状态。
        if covered_units >= strongest_covered_units:
            strongest_observation = item
            strongest_covered_units = covered_units

    strongest = dict(strongest_observation)
    strongest["retrieved_count"] = len(message_ids)
    try:
        return _normalize_retrieval_coverage("retrieval_coverage", strongest)
    except AnswerContractError as exc:
        raise _model_error("COVERAGE_MISMATCH", str(exc)) from exc


def _attach_execution_facts(
    artifact: AnswerArtifact,
    tool_results: tuple[ToolResultRecord, ...],
) -> AnswerArtifact:
    """把当前 Run 的窗口与 retrieval limitation 编译进最终 Artifact。"""

    # 每组独立校验 coverage；多窗不再错误套用同窗 eligible_units 不变式。
    windows = tuple(
        RecentRetrievalWindow(time_range, _recent_window_coverage(records))
        for time_range, records in _group_recent_records(tool_results)
    )
    # 唯一窗口继续使用原单值字段，多窗口通过独立事实列表表达。
    resolved_time_range = windows[0].resolved_time_range if len(windows) == 1 else None
    retrieval_coverage = windows[0].retrieval_coverage if len(windows) == 1 else None
    if artifact.retrieval_windows and artifact.retrieval_windows != windows:
        raise _model_error("TIME_RANGE_MISMATCH", "answer retrieval windows do not match Host tool windows")
    if len(windows) > 1 and artifact.resolved_time_range is not None:
        raise _model_error("TIME_RANGE_MISMATCH", "multi-window answer cannot claim a single resolved window")
    if len(windows) > 1 and artifact.retrieval_coverage is not None:
        raise _model_error("COVERAGE_MISMATCH", "multi-window answer cannot claim aggregate coverage")
    if (
        artifact.resolved_time_range is not None
        and resolved_time_range is not None
        and _recent_time_range_key(artifact.resolved_time_range) != _recent_time_range_key(resolved_time_range)
    ):
        raise _model_error(
            "TIME_RANGE_MISMATCH",
            "answer time range does not match the Host-resolved tool window",
            "resolved_time_range",
        )
    if (
        artifact.retrieval_coverage is not None
        and retrieval_coverage is not None
        and dict(artifact.retrieval_coverage) != retrieval_coverage
    ):
        raise _model_error(
            "COVERAGE_MISMATCH",
            "answer retrieval coverage does not match Host retrieval facts",
            "retrieval_coverage",
        )
    merged_limitations = list(artifact.limitations)
    for record in tool_results:
        for limitation in record.limitations:
            if limitation not in merged_limitations:
                merged_limitations.append(limitation)
    try:
        return replace(
            artifact,
            limitations=tuple(merged_limitations),
            resolved_time_range=resolved_time_range
            if resolved_time_range is not None
            else artifact.resolved_time_range,
            retrieval_coverage=retrieval_coverage if retrieval_coverage is not None else artifact.retrieval_coverage,
            retrieval_windows=windows,
        )
    except AnswerContractError as exc:
        raise _model_error("INVALID_ANSWER_ARTIFACT", str(exc)) from exc


def _assert_message_matches_recent_window(
    record: ToolResultRecord,
    message: MessageProjection,
    source_path: str,
) -> None:
    """确认 recent citation 的 canonical timestamp 落在同一 Host 半开窗口内。"""

    time_range = _record_time_range(record)
    if time_range is None:
        return
    start_timestamp = time_range["resolved_start_timestamp"]
    end_timestamp = time_range["resolved_end_timestamp"]
    if isinstance(start_timestamp, int) and not isinstance(start_timestamp, bool) and message.timestamp < start_timestamp:
        raise _model_error("TIME_RANGE_MISMATCH", "message citation is before the resolved recent window", source_path)
    if isinstance(end_timestamp, int) and not isinstance(end_timestamp, bool) and message.timestamp >= end_timestamp:
        raise _model_error("TIME_RANGE_MISMATCH", "message citation is after the resolved recent window", source_path)


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
        # 只前置已被 Retrieval 确认的实际命中，其他正文保持原有时间顺序。
        preferred_ids = _semantic_literal_ids(data)
        messages_by_id = {message.internal_message_id: message for message in data.expanded_messages}
        preferred_messages = tuple(
            messages_by_id[message_id]
            for message_id in data.primary_message_ids
            if message_id in preferred_ids
        )
        # 短 source handle 的优先序随真实命中传递，后续预算不能重新按时间挤掉它。
        message_items = _message_items(
            preferred_messages + data.expanded_messages,
            hit_ids=set(data.primary_message_ids),
        )
        query_snapshot = data.query.to_dict()
    elif isinstance(data, StructuredMessageResult):
        message_items = _message_items(data.messages)
        # recent query 的 resolved range 在 metadata 中，由 Capability 注入后与 continuation 一起保留。
        query_snapshot = {
            **data.query.to_dict(),
            "resolved_time_range": data.metadata.details.get("resolved_time_range"),
            "retrieved_count": data.metadata.details.get("retrieved_count", data.returned_count),
            "total_hits": data.total_hits,
            "returned_count": data.returned_count,
            "coverage": data.coverage.to_dict(),
            "partial": data.partial,
            "truncated": data.truncated,
            "has_more": data.metadata.details.get("has_more", data.partial),
            "next_cursor": data.metadata.details.get("next_cursor"),
        }
    elif isinstance(data, MessageContextResult):
        # Explicit context 的所有消息都属于当前 Tool Result，可继续使用 MessageSource citation。
        content_page = data.metadata.details.get("content_page")
        message_items = _message_items(data.messages, content_page=content_page if isinstance(content_page, Mapping) else None)
        raw_scope = data.metadata.filters.get("scope", {})
        query_snapshot = {
            "message_id": data.message_id,
            "session_id": data.session_id,
            "requested_before": data.requested_before,
            "requested_after": data.requested_after,
            "include_replies": data.metadata.details.get("include_replies", False),
            "content_page": content_page,
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
    limitations = _retrieval_limitations(envelope.status, data, error_code)
    if "unexpanded_forward_content" not in limitations and any(
        item.message.unexpanded_forward_paths for item in message_items
    ):
        # 缺失正文是来源事实；即使模型漏写限制，也要随当前 Tool Result 进入最终 Artifact。
        limitations = (*limitations, "unexpanded_forward_content")
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
        limitations=limitations,
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


def _set_model_message_content(
    entry: dict[str, object], full_content: str, maximum: int, canonical_truncated: bool,
) -> None:
    """按实际送达字符更新续读位置；预算进一步压缩正文时也不能跳过未读内容。"""
    content, shortened = _model_content(full_content, maximum)
    entry["content"] = content
    if shortened and "content_total_chars" not in entry:
        # 原本短消息也可能因本次预算被缩短，此时同样公开续读位置。
        entry["content_offset"] = 0
        entry["content_total_chars"] = len(full_content)
    offset = entry.get("content_offset", 0)
    entry["content_truncated"] = canonical_truncated or shortened or offset != 0
    if "content_total_chars" in entry:
        assert isinstance(offset, int)
        total_chars = entry["content_total_chars"]
        assert isinstance(total_chars, int)
        # 模型预览末尾的省略号不是原文字符，不计入下一页偏移。
        end = offset + len(content) - int(shortened)
        entry["content_end"] = end
        entry["next_content_offset"] = end if end < total_chars else None


def _reply_identity(message: MessageProjection, source_message_id: str) -> tuple[str, str | None, str | None, str]:
    """平台回复 ID 只能在同会话、同一个直接转发容器内关联。"""

    forward = message.forward
    return (
        message.session_id,
        None if forward is None else forward.parent_message_id,
        None if forward is None else forward.container_path,
        source_message_id,
    )


def _model_message_projection(
    record: ToolResultRecord,
    item: ToolMessageItem,
    source_id: str,
    reply_handles: Mapping[tuple[str, str | None, str | None, str], str | None],
    *,
    maximum_chars: int = MAX_MODEL_MESSAGE_CHARS,
    include_content_range: bool = False,
) -> tuple[dict[str, object], tuple[dict[str, object], bool, str, bool]]:
    """生成正文与必要转发来源 projection，并返回 budget trimming slot。"""

    message = item.message
    entry: dict[str, object] = {
        "source_id": source_id,
        "timestamp": message.timestamp,
        # 模型可直接读取 Host 派生的 UTC 日期；canonical 毫秒时间仍保留供契约校验。
        "timestamp_utc": format_timestamp_utc(message.timestamp),
        "author": message.sender_name or message.sender_user_id,
        "session": message.session_display or message.session_id,
        "message_type": message.message_type,
        "urls": item.urls,
        "hit": item.is_hit,
    }
    # 短普通消息不搬运额外元数据；长消息预览和显式正文页公开准确长度及续读位置。
    if include_content_range or item.content_truncated or len(message.normalized_content) > maximum_chars:
        entry["content_offset"] = item.content_offset
        entry["content_total_chars"] = (
            item.content_total_chars if item.content_total_chars is not None else len(message.normalized_content)
        )
    _set_model_message_content(entry, message.normalized_content, maximum_chars, item.content_truncated)
    # 只给真实回复增加关系字段，避免给所有普通命中重复搬运平台 ID、挤占调查预算。
    if message.reply_to_source_message_id is not None:
        entry["reply_to_source_message_id"] = message.reply_to_source_message_id
        target_handle = reply_handles.get(_reply_identity(message, message.reply_to_source_message_id))
        if target_handle is not None:
            # 目标在本结果内且能唯一定位时，直接关联模型已经认识的 source handle。
            entry["reply_to_source_id"] = target_handle
    if message.forward is not None:
        # 使用同一个 canonical provenance，模型无需从预览或相邻消息猜测父消息与作者。
        entry["forward"] = message.forward.to_dict()
        # 时间范围按当前群转发时间过滤，原始发送时间单独给出可直接引用的 UTC 文本。
        entry["timestamp_semantics"] = "forwarded_at"
        entry["original_timestamp_utc"] = (
            None
            if message.forward.original_timestamp is None
            else format_timestamp_utc(message.forward.original_timestamp)
        )
        entry["source_message_id"] = message.source_message_id
        entry["sender_platform_id"] = message.sender_platform_id
        entry["sender_uin"] = message.sender_uin
    if message.unexpanded_forward_paths:
        # 只说明该位置没有导出正文；预览不能证明缺失子消息的具体内容。
        entry["unexpanded_forward_paths"] = list(message.unexpanded_forward_paths)
        entry["forward_content_limitation"] = "Exported forward messages are empty; previews are not full message content."
    # slot 只存在 Host 内存中，full_content 不会随 model payload 返回。
    return entry, (entry, item.is_hit, message.normalized_content, item.content_truncated)


def _compact_model_message_fields(projected: dict[str, Any], entries: list[dict[str, object]]) -> None:
    """无损编码消息默认字段，排序实现细节继续由Host保留。"""
    if entries:
        # 声明省略字段的唯一含义；非默认值（链接、非文本、已截断）仍逐条保留。
        projected["message_defaults"] = dict(MODEL_MESSAGE_DEFAULTS)
        for entry in entries:
            for key, default in MODEL_MESSAGE_DEFAULTS.items():
                if entry.get(key) == default:
                    entry.pop(key)
    if projected.get("strategy") == "lexical":
        # 检索顺序和每条命中身份不变；模型不用根据BM25分数推断事实或质量。
        for hit in projected.get("hits", []):
            for key in ("matched_terms", "score", "score_type"):
                hit.pop(key)
    if projected.get("strategy") == "context":
        metadata = projected.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("details"), dict):
            # Canonical抓取页与模型实际投影可能因预算不同；只让逐消息范围指导模型续读。
            metadata["details"].pop("content_page", None)


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
    reply_handles: dict[tuple[str, str | None, str | None, str], str | None] = {}
    for index, item in enumerate(record.message_items):
        if item.message.source_message_id is not None:
            key = _reply_identity(item.message, item.message.source_message_id)
            # 转发导出允许重复平台 ID；有歧义时只保留原始关系，不指认任意一个 occurrence。
            reply_handles[key] = None if key in reply_handles else f"m{record.model_scope_id}-{index + 1}"
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
                    "ranking_strategy",
                    "literal_candidate_count",
                    "candidate_scores",
                    "score_type",
                    "context_before",
                    "context_after",
                    "expanded_candidate_messages",
                    "reply_source_hits",
                    "expanded_reply_messages",
                    "known_gaps",
                    "unexpanded_forward_node_count",
                    "unexpanded_forward_nodes",
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
                    reply_handles,
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
        indexed_messages: list[tuple[int, ToolMessageItem]] = []
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
            indexed_messages.append(indexed_item)
        if name == "expanded_messages" and projected.get("strategy") == "semantic":
            # Host record 已保留真实命中优先序；模型正文与 trimming slots 必须使用同一顺序。
            indexed_messages.sort(key=lambda indexed: indexed[0])
        for message_index, item in indexed_messages:
            # 显式读取的锚点按正文页送达；引用卡片的1000字边界不再截断阅读内容。
            is_context_anchor = projected.get("strategy") == "context" and (
                item.message.internal_message_id == projected.get("message_id")
            )
            entry, slot = _model_message_projection(
                record,
                item,
                f"m{record.model_scope_id}-{message_index + 1}",
                reply_handles,
                # 普通邻居沿用600字；点名原文按单页边界读取，继续受本轮Token预算控制。
                maximum_chars=MAX_MESSAGE_CONTENT_PAGE_CHARS if is_context_anchor else MAX_MODEL_MESSAGE_CHARS,
                include_content_range=is_context_anchor,
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

    # 预算裁剪之前先去掉可还原的重复字段，不以删正文或观点来为后续调查腾空间。
    _compact_model_message_fields(projected, [slot[1] for slot in slots])
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
    record: ToolResultRecord,
    *,
    token_budget: int,
    truncated: bool,
    omitted_context_messages: int,
    omitted_hit_messages: int,
) -> None:
    """写入公开 projection 预算事实，避免 Host 侧 trim 变成 hidden truncation。"""

    visible_source_ids = _projected_source_ids(payload.get("data"))
    projected_messages = sum(
        1 for source_id in visible_source_ids if source_id.startswith("m")
    )
    omitted_messages = max(0, len(record.message_items) - projected_messages)
    payload["model_projection"] = {
        "token_budget": token_budget,
        "estimated_tokens": (_projection_size(payload) + MODEL_TOKEN_CHAR_RATIO - 1) // MODEL_TOKEN_CHAR_RATIO,
        "truncated": truncated,
        "omitted_context_messages": omitted_context_messages,
        "omitted_hit_messages": omitted_hit_messages,
        "projected_messages": projected_messages,
        "projected_count": projected_messages,
        "omitted_messages": omitted_messages,
    }
    # meta 属于当前 projection 的公开摘要；canonical ToolEnvelope 本身仍保留 retrieved/total。
    meta = payload.get("meta")
    if isinstance(meta, dict):
        meta["projected_messages"] = projected_messages
        meta["projected_count"] = projected_messages
        meta["omitted_messages"] = omitted_messages
    # 估算必须包含 metrics 和新增 meta 自身，旧实现遗漏了这部分 transport 开销。
    metrics = payload["model_projection"]
    assert isinstance(metrics, dict)
    while True:
        # 数字位数可能使序列化长度变化，收敛到完整 payload 的精确 byte/ratio 估算。
        estimated = (_projection_size(payload) + MODEL_TOKEN_CHAR_RATIO - 1) // MODEL_TOKEN_CHAR_RATIO
        if metrics["estimated_tokens"] == estimated:
            break
        metrics["estimated_tokens"] = estimated


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
    # 预算二分会反复删减或恢复消息；独立保存原始关联，避免产生指向已省略来源的 handle。
    reply_target_entries = tuple(
        (slot[1], slot[1]["reply_to_source_id"])
        for slot in slots if "reply_to_source_id" in slot[1]
    )
    if isinstance(envelope.data, MessageContextResult) and envelope.data.metadata.details.get("include_replies"):
        # 只改变预算省略优先级：先保留 anchor 和显式请求的回复，再保留普通邻居。
        # canonical 返回顺序、来源 handle 与 hit/context 语义均保持原值。
        anchor_id = envelope.data.message_id
        anchor = next(item.message for item in record.message_items if item.message.internal_message_id == anchor_id)
        reply_handles = {
            f"m{record.model_scope_id}-{index + 1}"
            for index, item in enumerate(record.message_items)
            if item.message.internal_message_id == anchor_id
            or item.message.reply_to_source_message_id == anchor.source_message_id
        }
        slots.sort(key=lambda slot: slot[1]["source_id"] not in reply_handles)
    literal_ids = _semantic_literal_ids(envelope.data) if isinstance(envelope.data, SemanticRetrievalResult) else set()
    # 已核验命中保留最初的有界原文；否则先缩到 32 字再省略其他来源会丢掉正文中段的查询词。
    protected_source_ids = {
        f"m{record.model_scope_id}-{index + 1}"
        for index, item in enumerate(record.message_items)
        if item.message.internal_message_id in literal_ids
    }
    # 搜索命中的原消息与其明确直接回复共同构成证据；回复仍保留非 hit 身份。
    hit_handles = {slot[1]["source_id"] for slot in slots if slot[3]}
    context_reply_targets = {
        id(slot[2]): slot[1]["reply_to_source_id"] for slot in slots
        if not slot[3] and slot[1].get("reply_to_source_id") in hit_handles
    }
    raw_meta = canonical_payload.get("meta")
    projected_meta = dict(raw_meta) if isinstance(raw_meta, Mapping) else raw_meta
    payload: dict[str, object] = {
        "status": canonical_payload["status"],
        "data": projected_data,
        "meta": projected_meta,
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
        visible_source_ids = _projected_source_ids(payload["data"])
        for entry, target_handle in reply_target_entries:
            if target_handle in visible_source_ids:
                entry["reply_to_source_id"] = target_handle
            else:
                # 原始平台回复 ID 仍保留，但不再暗示被裁掉的目标正文已经对模型可见。
                entry.pop("reply_to_source_id", None)
        payload["provenance"] = record.to_model_provenance(source_ids=visible_source_ids)
        payload.pop("model_projection", None)
        _set_projection_metrics(
            payload,
            record,
            token_budget=token_budget,
            truncated=truncated,
            omitted_context_messages=omitted_context_messages,
            omitted_hit_messages=omitted_hit_messages,
        )
        return _projection_size(payload) <= max_bytes

    if not fits():
        # 只从普通邻居尾部省略刚好需要的数量，已关联到命中的回复暂不删除。
        ordinary_context = tuple(slot for slot in slots if not slot[3] and id(slot[2]) not in context_reply_targets)
        context_base = {id(slot[0]): (slot[0], list(slot[0])) for slot in slots}

        def apply_context_omission(count: int) -> set[int]:
            """每次从同一基线重建，二分裁剪不会反复丢失候选。"""
            removed = {id(slot[2]) for slot in ordinary_context[len(ordinary_context) - count:]}
            for container, original in context_base.values():
                container[:] = [entry for entry in original if id(entry) not in removed]
            return removed

        low, high = 0, len(ordinary_context)
        while low < high:
            candidate = (low + high) // 2
            apply_context_omission(candidate)
            omitted_context_messages = candidate
            truncated = candidate > 0
            if fits():
                high = candidate
            else:
                low = candidate + 1
        removed = apply_context_omission(low)
        omitted_context_messages = low
        truncated = low > 0
        slots = [slot for slot in slots if id(slot[2]) not in removed]

    if not fits():
        # 第二阶段只缩短正文；source、canonical/UTC timestamp、author、URL 和 hit identity 不被删除。
        for maximum in (512, 384, 256, 192, 128, 96, 64, 32):
            for _container, entry, _remove_entry, _is_hit, full_content, canonical_truncated in slots:
                # 优先来源已受既有 excerpt 上限约束；预算不足时继续省略后面的其他 hit。
                if entry["source_id"] in protected_source_ids:
                    continue
                _set_model_message_content(entry, full_content, maximum, canonical_truncated)
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
            context_omitted_before_hits = omitted_context_messages

            def apply_hit_omission(count: int) -> int:
                """从当前 context-trim 基线重建列表，只移除稳定顺序尾部 hit。"""

                omitted_entries = {
                    id(slot[2])
                    for slot in hit_slots[len(hit_slots) - count :]
                }
                # 原消息被省略时，它的附属回复也不再占用可见预算，避免孤立回复挤掉其他命中。
                retained_hits = {slot[1]["source_id"] for slot in hit_slots[:len(hit_slots) - count]}
                removed_replies = {entry_id for entry_id, target in context_reply_targets.items()
                    if target not in retained_hits}
                omitted_entries.update(removed_replies)
                for container, original in base_contents.values():
                    # 通过 identity 过滤可避免 list.remove 对每个尾部 hit 重复扫描前缀。
                    container[:] = [entry for entry in original if id(entry) not in omitted_entries]
                return len(removed_replies)

            low = 0
            high = len(hit_slots)
            while low < high:
                candidate = (low + high) // 2
                omitted_context_messages = context_omitted_before_hits + apply_hit_omission(candidate)
                omitted_hit_messages = candidate
                truncated = True
                if fits():
                    high = candidate
                else:
                    low = candidate + 1

            omitted_context_messages = context_omitted_before_hits + apply_hit_omission(low)
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
    content_offset: int = 0,
    content_total_chars: int | None = None,
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
        excerpt_truncated=truncated or content_offset > 0,
        excerpt_offset=content_offset,
        content_total_chars=content_total_chars,
        source_message_id=message.source_message_id,
        urls=source_urls or extract_urls(content),
        forward=message.forward,
        unexpanded_forward_paths=message.unexpanded_forward_paths,
        sender_platform_id=message.sender_platform_id if message.forward is not None else None,
        sender_uin=message.sender_uin if message.forward is not None else None,
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
        _assert_message_matches_recent_window(matched_record, message, source_path)
        return EvidenceSource(
            source.relation,
            replace(
                reference,
                snapshot=_hydrate_snapshot(
                    message,
                    content_truncated=matched_message_item.content_truncated,
                    source_urls=matched_message_item.urls,
                    content_offset=matched_message_item.content_offset,
                    content_total_chars=matched_message_item.content_total_chars,
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
        return _attach_execution_facts(artifact, tool_results)
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
        hydrated = replace(artifact, evidence_items=tuple(finalized_items))
        return _attach_execution_facts(hydrated, tool_results)
    except AnswerFinalizationError:
        # trusted time/provenance 边界错误必须保留稳定错误码，不能被普通 schema 包装覆盖。
        raise
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
        if isinstance(decoded_output, Mapping) and decoded_output.get("kind") == NO_RESULT_KIND:
            # 显式 zero-result 契约：positive proof——必须存在成功且完整确定为空的
            # retrieval 记录，且全程无可引用数据；error/partial/incomplete 走原 failure。
            no_result = parse_model_no_result_candidate(normalized_output)
            if not has_verified_zero_result_evidence(tool_results):
                raise _model_error(
                    "INVALID_FINAL_OUTPUT",
                    "zero-result final answer lacks verified complete-and-empty retrieval evidence",
                )
            return _attach_execution_facts(
                compile_model_no_result_answer(no_result),
                tool_results,
            )
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
        # recent citation 越过 Host 时间窗属于可信边界冲突，不能被 recovery 降级为无 citation 答案。
        "TIME_RANGE_MISMATCH",
        # recent 页的 coverage 冲突说明执行事实不可信，不能被 recovery 隐去。
        "COVERAGE_MISMATCH",
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
                if decoded.get("kind") == NO_RESULT_KIND:
                    # no-result recovery 与 strict 共用 positive-proof guard；不满足走 fatal。
                    no_result = parse_model_no_result_candidate(normalized_output)
                    if not has_verified_zero_result_evidence(tool_results):
                        return _recovery_error_result(
                            _model_error(
                                "INVALID_FINAL_OUTPUT",
                                "zero-result final answer lacks verified complete-and-empty retrieval evidence",
                            )
                        )
                    recovered = compile_model_no_result_answer(no_result)
                    binding_targets: tuple[tuple[str, str], ...] = ()
                elif "claims" in decoded:
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
            recovered = _attach_execution_facts(recovered, tool_results)
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
