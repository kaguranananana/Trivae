"""语义命中原分享后，明确的远距离回复也应在原上下文容量内送达。"""

from __future__ import annotations

from tests.test_ingestion import make_message, write_export
from tests.test_semantic_retrieval import _DeterministicProvider
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope, GetMessageContextInput, SemanticSearchInput
from trivae.query.evidence import build_tool_result_record, project_tool_result_for_model


def test_semantic_search_recovers_distant_direct_reply_without_changing_hit(tmp_path):
    """真实SQLite/vec0/Capability/投影链路：简短评价没有独立向量，也必须能沿回复边找到。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    base = 1_700_000_000_000
    messages = [make_message("anchor", 0, base, "budget 可视化技术项目 " + "实现说明 " * 30)]
    messages.extend(make_message(f"noise-{i}", i, base + i * 1000, "无关讨论") for i in range(1, 144))
    messages.append(make_message("reply", 144, base + 144_000, "实际用过，效果不错", reply_to="anchor"))
    messages.append(make_message("future", 145, base + 145_000, "范围外回复", reply_to="anchor"))
    write_export(raw, "semantic-reply(100).json", messages,
                 chat_name="语义回复", peer_uid=None, version="5.5.64")
    with create_application(tmp_path / "messages.sqlite3", semantic_provider=_DeterministicProvider()) as application:
        application.import_directory(raw)
        application.rebuild_semantic_index()
        scope = ExecutionScope(allowed_session_ids=("qq:100",), end_timestamp=base + 145_000)
        envelope = application.invoke_tool("semantic_search", SemanticSearchInput(
            query="这种项目实际用起来如何", limit=1, dense_top_k=1, context_before=1, context_after=1,
        ), scope)
        result = envelope.data
        explicit = application.invoke_tool("get_message_context", GetMessageContextInput(
            message_id="qq:100:anchor", context_before=0, context_after=0, include_replies=True,
        ), scope)
        assert "qq:100:reply" in {message.internal_message_id for message in explicit.data.messages}
        identities = {message.internal_message_id for message in result.expanded_messages}
        assert "qq:100:anchor" in identities
        assert "qq:100:reply" in identities, "semantic hit did not recover its distant direct reply"
        assert "qq:100:future" not in identities
        assert "qq:100:reply" not in result.primary_message_ids
        assert len(result.hits) == 1
        assert len(result.expanded_messages) <= 32
        without_context = application.invoke_tool("semantic_search", SemanticSearchInput(
            query="这种项目实际用起来如何", limit=1, dense_top_k=1, context_before=0, context_after=0,
        ), scope).data
        # 只改上下文恢复，ANN命中身份与顺序不变；0/0仍明确不自动扩展回复。
        assert result.hits == without_context.hits
        assert "qq:100:reply" not in {message.internal_message_id for message in without_context.expanded_messages}
        record = build_tool_result_record(run_id="semantic-reply", tool_call_id="run/tool-call/1",
            tool_result_id="result", tool_name="semantic_search", envelope=envelope, scope=scope)
        payload = project_tool_result_for_model(envelope, record)
        visible = {message["source_id"]: message for message in payload["data"]["expanded_messages"]}
        reply = next(message for message in visible.values() if "实际用过" in message["content"])
        assert "budget" in visible[reply["reply_to_source_id"]]["content"]
