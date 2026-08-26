"""M5b Conversation Store、Artifact replay 和 atomic boundary 测试。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.conversation import (
    ConversationMessage,
    SQLiteConversationStore,
    deserialize_answer_artifact,
    serialize_answer_artifact,
)
from trivae.query.contracts import QueryRequest
from trivae.query.evidence import (
    AnswerArtifact,
    AnswerContentBlock,
    CitationBinding,
    EvidenceItem,
    EvidenceSource,
    MessageDisplaySnapshot,
    MessageSource,
    StructuredSource,
    ToolMessageItem,
    ToolResultRecord,
    scope_snapshot,
)
from trivae.query.runtime.contracts import AgentRunRequest, RuntimeResult, RuntimeToolCall
from trivae.retrieval.structured import MessageProjection


def _artifact() -> AnswerArtifact:
    """构造同时包含 MessageSource 和 StructuredSource 的完整 round-trip fixture。"""

    message_source = MessageSource(
        run_id="run-1",
        tool_call_id="run-1/tool-call/1",
        tool_result_id="run-1/tool-result/1",
        result_item_id="message/m1",
        session_id="qq:100",
        internal_message_id="m1",
        snapshot=MessageDisplaySnapshot(
            session_display="Trivae 技术群",
            author_display="Alice",
            timestamp_ms=1_768_435_200_000,
            timezone="UTC",
            excerpt="vector discussion",
            excerpt_truncated=False,
            source_message_id="source-m1",
            urls=("https://github.com/example/vector",),
        ),
    )
    structured_source = StructuredSource(
        run_id="run-1",
        tool_call_id="run-1/tool-call/2",
        tool_result_id="run-1/tool-result/2",
        locator_kind="aggregate",
        locator="total_count",
        value_snapshot=7,
        query_scope_snapshot={"session_ids": ["qq:100"], "limit": 20},
        execution_limitations=("retrieval_truncated",),
        source_id="aggregate:total_count",
    )
    return AnswerArtifact(
        content_blocks=(
            AnswerContentBlock("claim-1", "群里确实讨论过向量检索。"),
            AnswerContentBlock("claim-2", "结构化统计返回了 7 条结果。"),
        ),
        citation_bindings=(
            CitationBinding("claim-1", ("evidence-message",)),
            CitationBinding("claim-2", ("evidence-structured",)),
        ),
        evidence_items=(
            EvidenceItem(
                evidence_id="evidence-message",
                finding="消息中出现了向量检索讨论",
                criterion="消息来源与当前 run 的 Tool Result 一致",
                sufficiency="sufficient",
                sources=(EvidenceSource("supports", message_source),),
                limitations=("仅保存 bounded excerpt",),
            ),
            EvidenceItem(
                evidence_id="evidence-structured",
                finding="结构化查询返回 7 条结果",
                criterion="aggregate locator 与返回值一致",
                sufficiency="partial",
                sources=(EvidenceSource("context", structured_source),),
                limitations=("统计不是语义正确性证明",),
            ),
        ),
        limitations=("当前回答只覆盖授权范围",),
    )


def _tool_record(scope: ExecutionScope, run_id: str, message_id: str) -> ToolResultRecord:
    """构造本轮可被 Finalizer 信任的 message Tool Result projection。"""

    projection = MessageProjection(
        internal_message_id=message_id,
        session_id="qq:100",
        source_message_id=f"source-{message_id}",
        sender_user_id="user:alice",
        sender_platform_id="alice",
        sender_uin="10001",
        sender_name="Alice",
        timestamp=1_768_435_200_000,
        seq=1,
        message_type="text",
        normalized_content="vector discussion",
        reply_to_source_message_id=None,
        recalled=False,
        system=False,
        session_display="Trivae 技术群",
    )
    return ToolResultRecord(
        run_id=run_id,
        tool_call_id=f"{run_id}/tool-call/1",
        tool_result_id=f"{run_id}/tool-result/1",
        tool_name="search_messages",
        status="ok",
        scope_snapshot=scope_snapshot(scope),
        query_scope_snapshot={"session_ids": ["qq:100"], "keyword": "vector"},
        message_items=(ToolMessageItem(f"message/{message_id}", projection),),
    )


def _candidate_json(run_id: str, message_id: str) -> str:
    """生成只包含当前 Tool locator 的模型候选；trusted snapshot 由 Finalizer 补齐。"""

    return json.dumps(
        {
            "content_blocks": [{"block_id": "claim-1", "text": "发现了向量检索讨论。"}],
            "citation_bindings": [{"content_block_id": "claim-1", "evidence_ids": ["e1"]}],
            "evidence_items": [
                {
                    "evidence_id": "e1",
                    "finding": "消息中讨论了向量检索",
                    "criterion": "当前 Tool Result 返回了该消息",
                    "sufficiency": "sufficient",
                    "sources": [
                        {
                            "relation": "supports",
                            "source": {
                                "type": "message",
                                "run_id": run_id,
                                "tool_call_id": f"{run_id}/tool-call/1",
                                "tool_result_id": f"{run_id}/tool-result/1",
                                "result_item_id": f"message/{message_id}",
                                "session_id": "qq:100",
                                "internal_message_id": message_id,
                            },
                        }
                    ],
                    "limitations": [],
                }
            ],
            "limitations": [],
        },
        ensure_ascii=False,
    )


class SQLiteConversationStoreTests(unittest.TestCase):
    """验证真实 SQLite 连接、codec round-trip 和 message 顺序。"""

    def test_answer_artifact_codec_round_trip_preserves_all_replay_fields(self) -> None:
        artifact = _artifact()

        restored = deserialize_answer_artifact(serialize_answer_artifact(artifact))

        self.assertEqual(restored, artifact)
        self.assertEqual(restored.answer_text, artifact.answer_text)
        self.assertEqual(restored.evidence_items[0].sources[0].reference.snapshot, artifact.evidence_items[0].sources[0].reference.snapshot)
        self.assertEqual(
            restored.evidence_items[0].sources[0].reference.snapshot.urls,
            ("https://github.com/example/vector",),
        )
        structured = restored.evidence_items[1].sources[0].reference
        self.assertIsInstance(structured, StructuredSource)
        self.assertEqual(structured.query_scope_snapshot, {"session_ids": ["qq:100"], "limit": 20})
        self.assertEqual(structured.source_id, "aggregate:total_count")

    def test_old_artifact_without_urls_remains_readable(self) -> None:
        """URL 字段是 additive；旧的已提交 Artifact 缺少它时按空列表恢复。"""

        payload = json.loads(serialize_answer_artifact(_artifact()))
        del payload["evidence_items"][0]["sources"][0]["reference"]["snapshot"]["urls"]

        restored = deserialize_answer_artifact(json.dumps(payload, ensure_ascii=False))

        snapshot = restored.evidence_items[0].sources[0].reference.snapshot
        assert snapshot is not None
        self.assertEqual(snapshot.urls, ())

    def test_sqlite_commit_close_reopen_and_ordered_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "conversation.sqlite3"
            store = SQLiteConversationStore(database_path)
            conversation = store.create_conversation()
            committed = store.commit_turn(conversation.conversation_id, "第一轮问题", _artifact())
            store.close()

            reopened = SQLiteConversationStore(database_path)
            restored = reopened.get_conversation(conversation.conversation_id)
            reopened.close()

        self.assertEqual([message.role for message in restored.messages], ["user", "assistant"])
        self.assertEqual([message.ordinal for message in restored.messages], [0, 1])
        self.assertEqual(restored.messages[0].content, "第一轮问题")
        self.assertEqual(restored.messages[1].answer_artifact, _artifact())
        self.assertEqual(committed.messages, restored.messages)

    def test_transaction_failure_rolls_back_user_and_assistant_together(self) -> None:
        class FailingAssistantStore(SQLiteConversationStore):
            """在 assistant insert 边界注入确定性失败，验证生产 transaction 的回滚。"""

            def _insert_message(self, message: ConversationMessage, artifact_json: str | None) -> None:
                if message.role == "assistant":
                    raise RuntimeError("injected assistant insert failure")
                super()._insert_message(message, artifact_json)

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "conversation.sqlite3"
            store = FailingAssistantStore(database_path)
            conversation = store.create_conversation()
            with self.assertRaisesRegex(RuntimeError, "assistant insert failure"):
                store.commit_turn(conversation.conversation_id, "失败问题", _artifact())
            store.close()

            reopened = SQLiteConversationStore(database_path)
            restored = reopened.get_conversation(conversation.conversation_id)
            reopened.close()

        self.assertEqual(restored.messages, ())


class _SequenceRuntime:
    """按顺序返回预先构造的 RuntimeResult，测试 Application boundary 而不调用 provider。"""

    def __init__(self, results: list[RuntimeResult]) -> None:
        self.results = iter(results)
        self.requests: list[AgentRunRequest] = []

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        self.requests.append(request)
        return next(self.results)


def _successful_runtime_result(scope: ExecutionScope, run_id: str, message_id: str) -> RuntimeResult:
    """构造会通过既有 Finalizer 的 completed RuntimeResult。"""

    record = _tool_record(scope, run_id, message_id)
    return RuntimeResult(
        final_answer=_candidate_json(run_id, message_id),
        provider="test",
        model="test-model",
        termination="completed",
        tool_calls=(RuntimeToolCall("search_messages", "ok", tool_call_id=record.tool_call_id),),
        run_id=run_id,
        tool_results=(record,),
    )


class ApplicationConversationBoundaryTests(unittest.TestCase):
    """验证 Application 只提交 validated success，并在 follow-up 建立新 provenance。"""

    def test_application_query_commits_validated_turn_and_replays_history(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=5)
        runtime = _SequenceRuntime(
            [
                _successful_runtime_result(scope, "run-1", "m1"),
                _successful_runtime_result(scope, "run-2", "m2"),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "application.sqlite3"
            application = create_application(database_path, agent_runtime=runtime)
            first = asyncio.run(application.query(QueryRequest("第一轮问题", scope)))
            self.assertTrue(first.is_successful)
            self.assertIsNotNone(first.conversation_id)
            second = asyncio.run(
                application.query(
                    QueryRequest("后来呢？", scope, conversation_id=first.conversation_id)
                )
            )
            self.assertTrue(second.is_successful)
            conversation_id = first.conversation_id
            assert conversation_id is not None
            restored = application.read_conversation(conversation_id)
            application.close()
            # 关闭原 Application 后重新打开 composition root，验证不是内存对象回放。
            reopened_application = create_application(database_path)
            restored_after_restart = reopened_application.read_conversation(conversation_id)
            reopened_application.close()

        self.assertEqual([message.role for message in restored.messages], ["user", "assistant", "user", "assistant"])
        self.assertEqual(restored_after_restart, restored)
        self.assertEqual(restored.messages[1].answer_artifact.evidence_items[0].sources[0].reference.run_id, "run-1")
        self.assertEqual(restored.messages[3].answer_artifact.evidence_items[0].sources[0].reference.run_id, "run-2")
        self.assertEqual(runtime.requests[1].model_context[1].role, "assistant")
        self.assertIn("Historical assistant answer", runtime.requests[1].model_context[1].content)
        self.assertNotIn("run-1/tool-result/1", runtime.requests[1].model_context[1].content)

    def test_degraded_finalization_commits_answer_but_runtime_failure_does_not(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=5)
        finalization_failure = RuntimeResult(
            final_answer="plain text after tool execution",
            provider="test",
            model="test-model",
            termination="completed",
            tool_calls=(),
            run_id="run-invalid",
            tool_results=(_tool_record(scope, "run-invalid", "m-invalid"),),
        )
        runtime_failure = RuntimeResult(
            final_answer=None,
            provider="test",
            model="test-model",
            termination="failed",
            tool_calls=(),
            run_id="run-failed",
        )
        runtime = _SequenceRuntime([finalization_failure, runtime_failure])

        with tempfile.TemporaryDirectory() as directory:
            application = create_application(Path(directory) / "application.sqlite3", agent_runtime=runtime)
            first = asyncio.run(application.query(QueryRequest("finalizer fails", scope)))
            second = asyncio.run(application.query(QueryRequest("runtime fails", scope)))
            first_conversation = application.read_conversation(first.conversation_id or "")
            second_conversation = application.read_conversation(second.conversation_id or "")
            application.close()

        # 可读正文的局部 finalization failure 会保留答案并以 degraded artifact 提交。
        self.assertTrue(first.is_successful)
        self.assertTrue(first.is_degraded)
        self.assertEqual(first.finalization_status, "degraded")
        self.assertIsNone(first.finalization_error)
        self.assertEqual([message.role for message in first_conversation.messages], ["user", "assistant"])
        self.assertEqual(first_conversation.messages[1].content, "plain text after tool execution")
        self.assertFalse(second.is_successful)
        self.assertEqual(second.termination, "failed")
        self.assertEqual(second_conversation.messages, ())

    def test_aborted_and_max_turns_do_not_commit_completed_assistant(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=5)
        runtime = _SequenceRuntime(
            [
                RuntimeResult(
                    final_answer="用户取消前的 partial text",
                    provider="test",
                    model="test-model",
                    termination="aborted",
                    tool_calls=(),
                    run_id="run-aborted",
                ),
                RuntimeResult(
                    final_answer="达到 max turns 的 partial text",
                    provider="test",
                    model="test-model",
                    termination="max_turns_exceeded",
                    tool_calls=(),
                    run_id="run-max-turns",
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as directory:
            application = create_application(Path(directory) / "application.sqlite3", agent_runtime=runtime)
            aborted = asyncio.run(application.query(QueryRequest("取消查询", scope)))
            max_turns = asyncio.run(application.query(QueryRequest("达到轮次上限", scope)))
            aborted_conversation = application.read_conversation(aborted.conversation_id or "")
            max_turns_conversation = application.read_conversation(max_turns.conversation_id or "")
            application.close()

        # Runtime terminal 不是 completed，Application 不应把 partial text 伪装成 Assistant Artifact。
        self.assertEqual(aborted.termination, "aborted")
        self.assertEqual(aborted_conversation.messages, ())
        self.assertEqual(max_turns.termination, "max_turns_exceeded")
        self.assertEqual(max_turns_conversation.messages, ())

    def test_old_evidence_cannot_be_submitted_as_new_run_source(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=5)
        old_result = _successful_runtime_result(scope, "run-old", "old-message")
        old_source_output = _candidate_json("run-old", "old-message")
        new_runtime = RuntimeResult(
            final_answer=old_source_output,
            provider="test",
            model="test-model",
            termination="completed",
            tool_calls=(),
            run_id="run-new",
            tool_results=(),
        )
        self.assertEqual(old_result.tool_results[0].run_id, "run-old")
        self.assertEqual(new_runtime.run_id, "run-new")

        # 这里直接走既有 QueryOrchestrator contract；旧 source 没有新 run 的 Tool Result，必须失败。
        from trivae.query.evidence import AnswerFinalizationError, finalize_answer

        with self.assertRaises(AnswerFinalizationError) as context:
            finalize_answer(
                new_runtime.final_answer or "",
                run_id=new_runtime.run_id,
                tool_results=new_runtime.tool_results,
                scope=scope,
            )
        self.assertEqual(context.exception.code, "INVALID_PROVENANCE")


if __name__ == "__main__":
    unittest.main()
