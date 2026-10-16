"""AnswerArtifact 的显式 JSON codec。

持久化层不使用 pickle 或隐式 dataclass 展开，所有 union/source 字段都在这里
集中编码和解码，避免不同消费者各自解释同一个 JSON payload。
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from trivae.query.evidence import (
    AnswerArtifact,
    AnswerContentBlock,
    CitationBinding,
    EvidenceItem,
    EvidenceSource,
    MessageDisplaySnapshot,
    MessageSource,
    RecentRetrievalWindow,
    SourceReference,
    StructuredSource,
)
from trivae.retrieval.structured import ForwardProvenance

from .contracts import ConversationCodecError


def _mapping(name: str, value: object) -> Mapping[str, object]:
    """只接受 object mapping，拒绝把数组或字符串误当成结构化对象。"""

    if not isinstance(value, Mapping):
        raise ConversationCodecError(f"{name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ConversationCodecError(f"{name} must contain string keys")
    return value


def _sequence(name: str, value: object) -> Sequence[object]:
    """只接受 JSON array 语义，避免字符串被逐字符解析。"""

    if not isinstance(value, list):
        raise ConversationCodecError(f"{name} must be an array")
    return value


def _required(mapping: Mapping[str, object], name: str) -> object:
    """集中处理必需字段，缺字段时保留清晰路径。"""

    if name not in mapping:
        raise ConversationCodecError(f"missing field: {name}")
    return mapping[name]


def _text(name: str, value: object) -> str:
    """codec 层先检查字符串类型，再交给领域对象执行内容约束。"""

    if not isinstance(value, str):
        raise ConversationCodecError(f"{name} must be a string")
    return value


def _json_value(name: str, value: object) -> object:
    """把领域允许的 bounded value 转成标准 JSON 值，不改变其数据层级。"""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConversationCodecError(f"{name} must contain finite numbers")
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(f"{name}.{key}", nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(f"{name}[{index}]", nested) for index, nested in enumerate(value)]
    raise ConversationCodecError(f"{name} contains an unsupported value type")


def _snapshot_to_dict(snapshot: MessageDisplaySnapshot | None) -> dict[str, object] | None:
    """保存 trusted hydration 结果，而不是重新依赖 Canonical Store 回填。"""

    if snapshot is None:
        return None
    payload: dict[str, object] = {
        "session_display": snapshot.session_display,
        "author_display": snapshot.author_display,
        "timestamp_ms": snapshot.timestamp_ms,
        "timezone": snapshot.timezone,
        "excerpt": snapshot.excerpt,
        "excerpt_truncated": snapshot.excerpt_truncated,
        "source_message_id": snapshot.source_message_id,
        "urls": list(snapshot.urls),
    }
    if snapshot.forward is not None:
        # 完整保存回答时的父子定位与双时间，历史回放不依赖索引仍然存在。
        payload["forward"] = snapshot.forward.to_dict()
    if snapshot.sender_platform_id is not None or snapshot.sender_uin is not None:
        payload["sender_platform_id"] = snapshot.sender_platform_id
        payload["sender_uin"] = snapshot.sender_uin
    if snapshot.unexpanded_forward_paths:
        payload["unexpanded_forward_paths"] = list(snapshot.unexpanded_forward_paths)
    return payload


def _reference_to_dict(reference: SourceReference) -> dict[str, object]:
    """用 discriminator 保留 Message/Structured source 的 union 语义。"""

    if isinstance(reference, MessageSource):
        return {
            "type": "message",
            "run_id": reference.run_id,
            "tool_call_id": reference.tool_call_id,
            "tool_result_id": reference.tool_result_id,
            "result_item_id": reference.result_item_id,
            "session_id": reference.session_id,
            "internal_message_id": reference.internal_message_id,
            "snapshot": _snapshot_to_dict(reference.snapshot),
        }
    if isinstance(reference, StructuredSource):
        return {
            "type": "structured",
            "run_id": reference.run_id,
            "tool_call_id": reference.tool_call_id,
            "tool_result_id": reference.tool_result_id,
            "locator_kind": reference.locator_kind,
            "locator": reference.locator,
            "value_snapshot": _json_value("value_snapshot", reference.value_snapshot),
            "query_scope_snapshot": (
                None
                if reference.query_scope_snapshot is None
                else _json_value("query_scope_snapshot", reference.query_scope_snapshot)
            ),
            "execution_limitations": list(reference.execution_limitations),
            "source_id": reference.source_id,
        }
    # transient SourceHandleReference 不能进入持久化边界；只有 validated full source 才可 replay。
    raise ConversationCodecError("source reference must be a validated MessageSource or StructuredSource")


def _artifact_to_dict(artifact: AnswerArtifact) -> dict[str, object]:
    """按领域结构逐层展开 Artifact，确保所有可 replay 字段都有 owner。"""

    return {
        "content_blocks": [
            {"block_id": block.block_id, "text": block.text} for block in artifact.content_blocks
        ],
        "citation_bindings": [
            {
                "content_block_id": binding.content_block_id,
                "evidence_ids": list(binding.evidence_ids),
            }
            for binding in artifact.citation_bindings
        ],
        "evidence_items": [
            {
                "evidence_id": item.evidence_id,
                "finding": item.finding,
                "criterion": item.criterion,
                "sufficiency": item.sufficiency,
                "sources": [
                    {"relation": source.relation, "reference": _reference_to_dict(source.reference)}
                    for source in item.sources
                ],
                "limitations": list(item.limitations),
            }
            for item in artifact.evidence_items
        ],
        "limitations": list(artifact.limitations),
        "resolved_time_range": (
            None
            if artifact.resolved_time_range is None
            else dict(artifact.resolved_time_range)
        ),
        "retrieval_coverage": (
            None
            if artifact.retrieval_coverage is None
            else dict(artifact.retrieval_coverage)
        ),
        # 逐窗编码，历史回放不能重新推导或丢失当时的覆盖状态。
        "retrieval_windows": [window.to_dict() for window in artifact.retrieval_windows],
    }


def serialize_answer_artifact(artifact: AnswerArtifact) -> str:
    """把 validated Artifact 编成稳定 JSON；候选对象不能绕过领域类型检查。"""

    if not isinstance(artifact, AnswerArtifact):
        raise ConversationCodecError("artifact must be an AnswerArtifact")
    try:
        return json.dumps(
            _artifact_to_dict(artifact),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ConversationCodecError("answer artifact cannot be serialized") from exc


def _optional_integer(name: str, value: object) -> int | None:
    """原始时间允许未知；已保存的数值必须保持整数语义。"""

    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ConversationCodecError(f"{name} must be an integer or null")
    return value


def _parse_forward(value: object, path: str) -> ForwardProvenance | None:
    """仅恢复持久化的可信转发位置，旧普通消息没有这个可选字段。"""

    if value is None:
        return None
    raw = _mapping(path, value)
    return ForwardProvenance(
        root_message_id=_text(f"{path}.root_message_id", _required(raw, "root_message_id")),
        parent_message_id=_text(f"{path}.parent_message_id", _required(raw, "parent_message_id")),
        path=_text(f"{path}.path", _required(raw, "path")),
        original_timestamp=_optional_integer(f"{path}.original_timestamp", _required(raw, "original_timestamp")),
        root_source_message_id=(
            None
            if raw.get("root_source_message_id") is None
            else _text(f"{path}.root_source_message_id", raw["root_source_message_id"])
        ),
        source_file=None if raw.get("source_file") is None else _text(f"{path}.source_file", raw["source_file"]),
        source_record_index=_optional_integer(f"{path}.source_record_index", raw.get("source_record_index")),
    )


def _parse_snapshot(value: object, path: str) -> MessageDisplaySnapshot | None:
    """恢复可信展示 snapshot；历史回放不重新查询 canonical source。"""

    if value is None:
        return None
    raw = _mapping(path, value)
    timestamp_ms = _required(raw, "timestamp_ms")
    excerpt_truncated = _required(raw, "excerpt_truncated")
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
        raise ConversationCodecError(f"{path}.timestamp_ms must be an integer")
    if not isinstance(excerpt_truncated, bool):
        raise ConversationCodecError(f"{path}.excerpt_truncated must be a boolean")
    raw_urls = raw.get("urls", [])
    if not isinstance(raw_urls, list):
        raise ConversationCodecError(f"{path}.urls must be an array")
    return MessageDisplaySnapshot(
        session_display=_text(f"{path}.session_display", _required(raw, "session_display")),
        author_display=(
            None
            if raw.get("author_display") is None
            else _text(f"{path}.author_display", raw["author_display"])
        ),
        timestamp_ms=timestamp_ms,
        timezone=_text(f"{path}.timezone", _required(raw, "timezone")),
        excerpt=_text(f"{path}.excerpt", _required(raw, "excerpt")),
        excerpt_truncated=excerpt_truncated,
        source_message_id=(
            None
            if raw.get("source_message_id") is None
            else _text(f"{path}.source_message_id", raw["source_message_id"])
        ),
        urls=tuple(_text(f"{path}.urls[{index}]", url) for index, url in enumerate(raw_urls)),
        forward=_parse_forward(raw.get("forward"), f"{path}.forward"),
        unexpanded_forward_paths=tuple(
            _text(f"{path}.unexpanded_forward_paths[{index}]", nested_path)
            for index, nested_path in enumerate(
                _sequence(f"{path}.unexpanded_forward_paths", raw.get("unexpanded_forward_paths", []))
            )
        ),
        sender_platform_id=(
            None
            if raw.get("sender_platform_id") is None
            else _text(f"{path}.sender_platform_id", raw["sender_platform_id"])
        ),
        sender_uin=None if raw.get("sender_uin") is None else _text(f"{path}.sender_uin", raw["sender_uin"]),
    )


def _parse_reference(value: object, path: str) -> MessageSource | StructuredSource:
    """按 source discriminator 恢复 union，未知类型显式失败。"""

    raw = _mapping(path, value)
    source_type = _text(f"{path}.type", _required(raw, "type"))
    if source_type == "message":
        return MessageSource(
            run_id=_text(f"{path}.run_id", _required(raw, "run_id")),
            tool_call_id=_text(f"{path}.tool_call_id", _required(raw, "tool_call_id")),
            tool_result_id=_text(f"{path}.tool_result_id", _required(raw, "tool_result_id")),
            result_item_id=_text(f"{path}.result_item_id", _required(raw, "result_item_id")),
            session_id=_text(f"{path}.session_id", _required(raw, "session_id")),
            internal_message_id=_text(f"{path}.internal_message_id", _required(raw, "internal_message_id")),
            snapshot=_parse_snapshot(raw.get("snapshot"), f"{path}.snapshot"),
        )
    if source_type == "structured":
        query_scope = raw.get("query_scope_snapshot")
        if query_scope is not None and not isinstance(query_scope, Mapping):
            raise ConversationCodecError(f"{path}.query_scope_snapshot must be an object or null")
        return StructuredSource(
            run_id=_text(f"{path}.run_id", _required(raw, "run_id")),
            tool_call_id=_text(f"{path}.tool_call_id", _required(raw, "tool_call_id")),
            tool_result_id=_text(f"{path}.tool_result_id", _required(raw, "tool_result_id")),
            locator_kind=_text(f"{path}.locator_kind", _required(raw, "locator_kind")),  # type: ignore[arg-type]
            locator=_text(f"{path}.locator", _required(raw, "locator")),
            value_snapshot=_required(raw, "value_snapshot"),
            query_scope_snapshot=query_scope,
            execution_limitations=tuple(
                _text(f"{path}.execution_limitations[{index}]", item)
                for index, item in enumerate(_sequence(f"{path}.execution_limitations", _required(raw, "execution_limitations")))
            ),
            source_id=(
                None
                if raw.get("source_id") is None
                else _text(f"{path}.source_id", raw["source_id"])
            ),
        )
    raise ConversationCodecError(f"{path}.type must be message or structured")


def _parse_evidence_source(value: object, path: str) -> EvidenceSource:
    """恢复 source relation，并把 relation 与 reference 保持在同一 EvidenceSource 内。"""

    raw = _mapping(path, value)
    relation = _text(f"{path}.relation", _required(raw, "relation"))
    return EvidenceSource(
        relation=relation,  # type: ignore[arg-type]
        reference=_parse_reference(_required(raw, "reference"), f"{path}.reference"),
    )


def _parse_artifact(value: object) -> AnswerArtifact:
    """按 content → binding → evidence 顺序恢复，最终由 AnswerArtifact 做交叉引用校验。"""

    raw = _mapping("artifact", value)
    content_blocks = tuple(
        AnswerContentBlock(
            block_id=_text(f"content_blocks[{index}].block_id", _required(_mapping("content block", item), "block_id")),
            text=_text(f"content_blocks[{index}].text", _required(_mapping("content block", item), "text")),
        )
        for index, item in enumerate(_sequence("content_blocks", _required(raw, "content_blocks")))
    )
    bindings = tuple(
        CitationBinding(
            content_block_id=_text(
                f"citation_bindings[{index}].content_block_id",
                _required(_mapping("citation binding", item), "content_block_id"),
            ),
            evidence_ids=tuple(
                _text(f"citation_bindings[{index}].evidence_ids[{evidence_index}]", evidence_id)
                for evidence_index, evidence_id in enumerate(
                    _sequence(
                        f"citation_bindings[{index}].evidence_ids",
                        _required(_mapping("citation binding", item), "evidence_ids"),
                    )
                )
            ),
        )
        for index, item in enumerate(_sequence("citation_bindings", _required(raw, "citation_bindings")))
    )
    evidence_items = tuple(
        EvidenceItem(
            evidence_id=_text(f"evidence_items[{index}].evidence_id", _required(item_mapping, "evidence_id")),
            finding=_text(f"evidence_items[{index}].finding", _required(item_mapping, "finding")),
            criterion=_text(f"evidence_items[{index}].criterion", _required(item_mapping, "criterion")),
            sufficiency=_text(f"evidence_items[{index}].sufficiency", _required(item_mapping, "sufficiency")),  # type: ignore[arg-type]
            sources=tuple(
                _parse_evidence_source(source, f"evidence_items[{index}].sources[{source_index}]")
                for source_index, source in enumerate(
                    _sequence(f"evidence_items[{index}].sources", _required(item_mapping, "sources"))
                )
            ),
            limitations=tuple(
                _text(f"evidence_items[{index}].limitations[{limit_index}]", limitation)
                for limit_index, limitation in enumerate(
                    _sequence(f"evidence_items[{index}].limitations", _required(item_mapping, "limitations"))
                )
            ),
        )
        for index, item in enumerate(_sequence("evidence_items", _required(raw, "evidence_items")))
        for item_mapping in (_mapping(f"evidence_items[{index}]", item),)
    )
    limitations = tuple(
        _text(f"limitations[{index}]", limitation)
        for index, limitation in enumerate(_sequence("limitations", _required(raw, "limitations")))
    )
    raw_time_range = raw.get("resolved_time_range")
    if raw_time_range is not None and not isinstance(raw_time_range, Mapping):
        raise ConversationCodecError("resolved_time_range must be an object or null")
    raw_retrieval_coverage = raw.get("retrieval_coverage")
    if raw_retrieval_coverage is not None and not isinstance(raw_retrieval_coverage, Mapping):
        raise ConversationCodecError("retrieval_coverage must be an object or null")
    try:
        # 旧持久化记录没有此字段；缺省为空表示沿用其原有单窗事实。
        windows = tuple(
            RecentRetrievalWindow(
                resolved_time_range=_mapping("window.resolved_time_range", _required(window, "resolved_time_range")),
                retrieval_coverage=(
                    None
                    if window.get("retrieval_coverage") is None
                    else _mapping("window.retrieval_coverage", window["retrieval_coverage"])
                ),
            )
            for value in _sequence("retrieval_windows", raw.get("retrieval_windows", []))
            for window in (_mapping("retrieval_windows item", value),)
        )
        return AnswerArtifact(
            content_blocks=content_blocks,
            citation_bindings=bindings,
            evidence_items=evidence_items,
            limitations=limitations,
            resolved_time_range=raw_time_range,
            retrieval_coverage=raw_retrieval_coverage,
            retrieval_windows=windows,
        )
    except (TypeError, ValueError) as exc:
        raise ConversationCodecError("decoded answer artifact violates its domain contract") from exc


def deserialize_answer_artifact(payload: str) -> AnswerArtifact:
    """从 SQLite 文本恢复 Artifact；JSON 或领域错误均显式向 Application 暴露。"""

    if not isinstance(payload, str) or not payload.strip():
        raise ConversationCodecError("answer artifact JSON must be non-empty text")
    try:
        decoded: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ConversationCodecError("answer artifact JSON is invalid") from exc
    try:
        return _parse_artifact(decoded)
    except ConversationCodecError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ConversationCodecError("answer artifact JSON has invalid fields") from exc
