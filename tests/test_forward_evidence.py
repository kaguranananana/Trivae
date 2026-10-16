"""合并转发的模型可见事实、可信 Citation、历史回放和来源复核回归。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_evidence import _message
from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope, GetMessageContextInput
from trivae.capabilities.contracts import ToolEnvelope, format_timestamp_utc
from trivae.conversation import (
    SQLiteConversationStore,
    deserialize_answer_artifact,
    serialize_answer_artifact,
)
from trivae.interfaces.cli import _print_source_block, _print_source_detail
from trivae.interfaces.web.projection import project_context_messages, project_source_snapshot
from trivae.query.contracts import QueryRequest
from trivae.query.evidence import (
    AnswerFinalizationError,
    MessageSource,
    SourceInspectionError,
    answer_source_summaries,
    build_tool_result_record,
    finalize_answer,
    project_tool_result_for_model,
    validate_answer_artifact,
)
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.retrieval.semantic.contracts import SemanticQuery, SemanticRetrievalResult
from trivae.retrieval.structured import (
    Coverage,
    ForwardProvenance,
    LexicalQuery,
    MessageHit,
    MessageQuery,
    RetrievalMetadata,
    RetrievalResult,
)


def _child(*, root_id: str = "qq:100:outer", missing: bool = False):
    """原始时间在 scope 外，转发时间在 scope 内，固定两种时间不可混用。"""

    path = "content.elements[0].data.messages[1].content.elements[0].data.messages[2]"
    return replace(
        _message(internal_message_id=f"{root_id}#forward:0.1.0.2", timestamp=10_000, content="远程连接"),
        source_message_id="original-child",
        sender_name="内部作者",
        sender_platform_id="u-original",
        sender_uin="12345",
        forward=ForwardProvenance(
            root_message_id=root_id,
            parent_message_id=f"{root_id}#forward:0.1",
            path=path,
            original_timestamp=1_000,
            root_source_message_id="outer",
            source_file="raw/group(100).json",
            source_record_index=6235,
        ),
        unexpanded_forward_paths=(f"{path}.content.elements[0]",) if missing else (),
    )


def _envelope(messages, *, semantic=False):
    """两条已有检索路径使用同一种 canonical 子消息 projection。"""

    metadata = RetrievalMetadata(filters={}, ordering="test", latency_ms=0.0)
    if semantic:
        result = SemanticRetrievalResult(
            query=SemanticQuery(query="连接远程机器", limit=5),
            filters={},
            strategy="semantic",
            hits=(),
            expanded_messages=messages,
            primary_message_ids=tuple(message.internal_message_id for message in messages),
            total_hits=1,
            returned_messages=len(messages),
            coverage=Coverage("complete", "canonical_semantic_range"),
            partial=False,
            truncated=False,
            metadata=metadata,
        )
    else:
        result = RetrievalResult(
            query=LexicalQuery(keyword="远程连接", limit=5, context_before=0, context_after=0),
            filters={},
            strategy="lexical",
            hits=tuple(MessageHit(message, ("远程连接",), 1.0, "test") for message in messages),
            expanded_messages=messages,
            total_hits=len(messages),
            returned_messages=len(messages),
            coverage=Coverage("complete", "canonical_lexical"),
            partial=False,
            truncated=False,
            metadata=metadata,
        )
    return ToolEnvelope("ok", result, {}, None)


def _record(envelope, scope):
    """通过生产 builder 创建当前 run record，不能手工省掉 provenance 校验。"""

    return build_tool_result_record(
        run_id="forward-run",
        tool_call_id="forward-run/tool-call/1",
        tool_result_id="forward-run/tool-call/1/result",
        tool_name="semantic_search" if envelope.data.strategy == "semantic" else "lexical_search",
        envelope=envelope,
        scope=scope,
    )


def _answer(*sources):
    """模型只提交当前 Tool Result 的短 handle，不构造父子来源。"""

    return json.dumps({
        "claims": [{
            "text": "内部作者讨论了远程连接。",
            "finding": "子消息出现远程连接",
            "criterion": "当前工具返回该子消息",
            "sufficiency": "partial",
            "sources": list(sources),
            "limitations": [],
        }],
        "limitations": [],
    }, ensure_ascii=False)


@pytest.mark.parametrize("semantic", [False, True])
def test_model_projection_and_finalization_preserve_forward_provenance(semantic):
    """lexical/semantic 都让模型看见内部作者、双时间和精确父子链。"""

    message = _child()
    scope = ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=9_000, end_timestamp=11_000)
    envelope = _envelope((message,), semantic=semantic)
    record = _record(envelope, scope)
    projection = project_tool_result_for_model(envelope, record)
    entry = (
        projection["data"]["expanded_messages"][0]
        if semantic else projection["data"]["hits"][0]["message"]
    )

    assert entry["source_id"] == "m1-1"
    assert entry["author"] == "内部作者"
    assert entry["sender_platform_id"] == "u-original"
    assert entry["source_message_id"] == "original-child"
    assert entry["timestamp"] == 10_000
    assert entry["timestamp_utc"] == format_timestamp_utc(10_000)
    assert entry["timestamp_semantics"] == "forwarded_at"
    assert entry["original_timestamp_utc"] == format_timestamp_utc(1_000)
    assert entry["forward"] == message.forward.to_dict()
    artifact = finalize_answer(_answer("m1-1"), run_id=record.run_id, tool_results=(record,), scope=scope)
    reference = artifact.evidence_items[0].sources[0].reference
    assert isinstance(reference, MessageSource)
    assert reference.internal_message_id == message.internal_message_id
    assert reference.snapshot.forward == message.forward
    assert reference.snapshot.sender_platform_id == "u-original"
    assert reference.snapshot.sender_uin == "12345"
    assert reference.snapshot.timestamp_ms == 10_000
    # 提交者伪造 snapshot 时，Finalizer 仍从当前 Tool Result 覆盖全部转发来源。
    fake_snapshot = replace(reference.snapshot, forward=replace(message.forward, root_message_id="qq:200:forged"))
    evidence = artifact.evidence_items[0]
    fake_artifact = replace(artifact, evidence_items=(replace(evidence, sources=(
        replace(evidence.sources[0], reference=replace(reference, snapshot=fake_snapshot)),
    )),))
    validated = validate_answer_artifact(fake_artifact, run_id=record.run_id, tool_results=(record,), scope=scope)
    assert validated.evidence_items[0].sources[0].reference.snapshot.forward == message.forward


def test_missing_nodes_survive_model_snapshot_and_history(tmp_path):
    """空节点的限制不依赖模型自觉填写，可信快照和重启回放均保留缺失位置。"""

    message = _child(missing=True)
    scope = ExecutionScope(allowed_session_ids=("qq:100",))
    envelope = _envelope((message,))
    record = _record(envelope, scope)
    entry = project_tool_result_for_model(envelope, record)["data"]["hits"][0]["message"]
    assert entry["unexpanded_forward_paths"] == list(message.unexpanded_forward_paths)
    assert "not full message content" in entry["forward_content_limitation"]

    artifact = finalize_answer(_answer("m1-1"), run_id=record.run_id, tool_results=(record,), scope=scope)
    assert "unexpanded_forward_content" in artifact.limitations
    database_path = tmp_path / "history.sqlite3"
    store = SQLiteConversationStore(database_path)
    conversation = store.create_conversation(scope)
    store.commit_turn(conversation.conversation_id, "转发里说了什么", artifact)
    store.close()
    reopened = SQLiteConversationStore(database_path)
    try:
        restored = reopened.get_conversation(conversation.conversation_id).messages[-1].answer_artifact
    finally:
        reopened.close()
    assert restored == artifact
    snapshot = restored.evidence_items[0].sources[0].reference.snapshot
    assert snapshot.unexpanded_forward_paths == message.unexpanded_forward_paths
    assert snapshot.forward.source_record_index == 6235
    assert project_source_snapshot(snapshot)["forward"]["root_message_id"] == "qq:100:outer"
    # 已保存来源只能回放；新的 run 必须重新取得 Tool Result 才能使用该子消息引用。
    with pytest.raises(AnswerFinalizationError) as error:
        validate_answer_artifact(restored, run_id="new-run", tool_results=(), scope=scope)
    assert error.value.code == "INVALID_PROVENANCE"


@pytest.mark.parametrize("semantic", [False, True])
def test_scope_missing_content_is_retained_even_when_the_hit_has_no_missing_descendants(semantic):
    """命中叶子与缺失节点是兄弟分支时，scope coverage 仍明确限制最终回答。"""

    scope = ExecutionScope(allowed_session_ids=("qq:100",))
    envelope = _envelope((_child(),), semantic=semantic)
    result = replace(envelope.data, coverage=Coverage(
        "partial", "canonical_index", known_gaps=("unexpanded_forward_content",),
    ))
    envelope = replace(envelope, data=result)
    record = _record(envelope, scope)
    assert "unexpanded_forward_content" in record.limitations
    assert not record.message_items[0].message.unexpanded_forward_paths
    projected = project_tool_result_for_model(envelope, record)
    assert "unexpanded_forward_content" in projected["data"]["coverage"]["known_gaps"]
    artifact = finalize_answer(_answer("m1-1"), run_id=record.run_id, tool_results=(record,), scope=scope)
    assert "unexpanded_forward_content" in artifact.limitations


def test_dedup_keeps_repeated_and_cross_session_forward_occurrences():
    """同一原始子消息跨父消息或群聊出现时，各 occurrence 都是独立可引用来源。"""

    first = _child()
    repeated = _child(root_id="qq:100:outer-again")
    cross_session = replace(_child(root_id="qq:200:outer"), session_id="qq:200")
    scope = ExecutionScope(allowed_session_ids=("qq:100", "qq:200"))
    envelope = _envelope((first, repeated, cross_session, first))
    record = _record(envelope, scope)
    assert len(record.message_items) == 3
    artifact = finalize_answer(_answer("m1-1", "m1-2", "m1-3"),
        run_id=record.run_id, tool_results=(record,), scope=scope)
    summaries = answer_source_summaries(artifact)
    assert len(summaries) == 3
    assert {summary.reference.internal_message_id for summary in summaries} == {
        first.internal_message_id, repeated.internal_message_id, cross_session.internal_message_id,
    }


@pytest.mark.parametrize("changes", [{"session_id": "qq:200"}, {"timestamp": 12_000}])
def test_forward_citation_cannot_bypass_current_group_or_forwarded_time(changes):
    """原始时间或父子定位都不能让当前群/转发时间范围之外的证据获得引用。"""

    scope = ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=9_000, end_timestamp=11_000)
    message = replace(_child(), **changes)
    record = _record(_envelope((message,)), scope)
    with pytest.raises(AnswerFinalizationError) as error:
        finalize_answer(_answer("m1-1"), run_id=record.run_id, tool_results=(record,), scope=scope)
    assert error.value.code == "SCOPE_VIOLATION"


def test_long_json_position_does_not_expand_source_identity_and_plain_messages_stay_plain():
    """完整 JSON 路径可以长于 locator bound，短数字链仍保留精确 provenance。"""

    message = _child()
    forward = replace(message.forward, path="content.elements[0].data.messages[1]." * 20)
    message = replace(message, forward=forward)
    scope = ExecutionScope()
    record = _record(_envelope((message,)), scope)
    artifact = finalize_answer(_answer("m1-1"), run_id=record.run_id, tool_results=(record,), scope=scope)
    assert deserialize_answer_artifact(serialize_answer_artifact(artifact)) == artifact
    assert len(artifact.evidence_items[0].sources[0].reference.snapshot.forward.path) > 512

    ordinary = _message()
    envelope = _envelope((ordinary,))
    record = _record(envelope, scope)
    entry = project_tool_result_for_model(envelope, record)["data"]["hits"][0]["message"]
    assert "forward" not in entry
    assert "timestamp_semantics" not in entry
    ordinary_artifact = finalize_answer(_answer("m1-1"), run_id=record.run_id, tool_results=(record,), scope=scope)
    assert ordinary_artifact.evidence_items[0].sources[0].reference.snapshot.forward is None
    assert "forward" not in json.loads(serialize_answer_artifact(ordinary_artifact))["evidence_items"][0]["sources"][0]["reference"]["snapshot"]


def _write_forward_fixture(directory: Path):
    """只创建 temporary QCE 输入；内部作者不作为当前群 Membership 写入。"""

    child = make_message("inside", 1, 1_000, "远程连接", sender_uid="u-original")
    child["sender"]["name"] = "内部作者"
    missing = {"type": "forward", "data": {"messages": [], "preview": ["不能推断的预览"]}}
    nested = make_message("nested", 2, 2_000, "[合并转发]")
    nested["content"]["elements"] = [missing]
    root = make_message("outer", 1, 10_000, "[合并转发]")
    root["content"]["elements"] = [{"type": "forward", "data": {"messages": [child, nested]}}]
    write_export(directory, "forward(100).json", [root, make_message("plain", 2, 11_000, "普通消息")],
        chat_name="当前群", peer_uid=None, version="5.5.64")


def test_production_agent_child_handle_context_citation_inspection_and_replay(tmp_path):
    """真实 SDK tool loop 贯通 FTS→source handle→context→Citation→来源复核→历史。"""

    raw = tmp_path / "raw"
    raw.mkdir()
    _write_forward_fixture(raw)
    application = create_application(tmp_path / "canonical.sqlite3")
    scope = ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=9_000, end_timestamp=12_000)
    try:
        application.import_directory(raw)
        application.rebuild_lexical_index()
        model = ScriptedModel([
            ModelStep(output=[function_call("lexical_search", {"keyword": "远程连接", "limit": 5,
                "context_before": 0, "context_after": 0}, call_id="search")]),
            ModelStep(output=[function_call("get_message_context", {"source_id": "m1-1",
                "context_before": 0, "context_after": 3}, call_id="context")]),
            ModelStep(output=[assistant_message(_answer("m1-1"))]),
        ])
        application._agent_runtime = OpenAIAgentsRuntimeAdapter(application.capability_registry, model=model, max_turns=4)
        result = asyncio.run(application.query(QueryRequest("转发中谁说了远程连接？", scope,
            available_capabilities=("lexical_search", "get_message_context"))))
        assert result.is_successful, result.finalization_error
        artifact = result.answer_artifact
        reference = artifact.evidence_items[0].sources[0].reference
        assert isinstance(reference, MessageSource)
        assert reference.internal_message_id == "qq:100:outer#forward:0.0"
        assert reference.snapshot.author_display == "内部作者"
        assert reference.snapshot.forward.root_message_id == "qq:100:outer"
        assert reference.snapshot.forward.source_record_index == 0
        assert reference.snapshot.forward.source_file.endswith("forward(100).json")
        # 当前 run 的短 handle 正常解析到 canonical child，context 不混入外层普通群消息。
        context_messages = result.runtime_result.tool_results[1].message_items
        assert context_messages[0].message.internal_message_id == reference.internal_message_id
        assert all(item.message.forward is not None for item in context_messages)
        assert "unexpanded_forward_content" in artifact.limitations
        restored = application.read_conversation(result.conversation_id).messages[-1].answer_artifact
        assert restored == artifact

        inspected = application.inspect_message_source(reference, scope)
        target = next(message for message in inspected if message.internal_message_id == reference.internal_message_id)
        assert target.normalized_content == "远程连接"
        assert target.timestamp == 10_000
        assert target.forward.original_timestamp == 1_000
        context = project_context_messages(inspected, target_internal_message_id=reference.internal_message_id)
        projected_target = next(message for message in context["messages"] if message["is_target"])
        assert projected_target["forward"] == target.forward.to_dict()
        assert projected_target["timestamp_semantics"] == "forwarded_at"

        with pytest.raises(SourceInspectionError):
            application.inspect_message_source(reference, ExecutionScope(allowed_session_ids=("qq:200",)))
        with pytest.raises(SourceInspectionError):
            application.inspect_message_source(reference, ExecutionScope(allowed_session_ids=("qq:100",), end_timestamp=9_000))

        lines = []
        summary = answer_source_summaries(artifact)[0]
        _print_source_block((summary,), output_fn=lines.append, verbose=False)
        _print_source_detail(summary, application=application, scope=scope, output_fn=lines.append, verbose=False)
        rendered = "\n".join(lines)
        assert "forwarded at" in rendered and "Original sent at" in rendered
        assert target.forward.path in rendered and "forward(100).json" in rendered
        assert "qq:100:outer" in rendered and "inside" in rendered
        # 普通上下文行为与 Canonical 数量不受子消息投影影响。
        assert application.read_repository.count_messages(MessageQuery()) == 2
        ordinary = application.invoke_tool("get_message_context", GetMessageContextInput("qq:100:plain"), scope)
        assert ordinary.status == "ok"
        assert all(message.forward is None for message in ordinary.data.messages)
    finally:
        application.close()
