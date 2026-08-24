from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.conversation import SQLiteConversationStore
from trivae.feedback.contracts import FeedbackRecord
from trivae.feedback.sqlite import SQLiteFeedbackStore
from trivae.query.evidence import (
    AnswerArtifact,
    AnswerContentBlock,
    AnswerSourceSummary,
    CitationBinding,
    EvidenceItem,
    EvidenceSource,
    MessageDisplaySnapshot,
    MessageSource,
    answer_source_summaries,
)


def _artifact(source: MessageSource) -> AnswerArtifact:
    """构造两个 Evidence 共享一条来源的 finalized 形状。"""

    return AnswerArtifact(
        content_blocks=(AnswerContentBlock("answer", "bounded answer"),),
        citation_bindings=(CitationBinding("answer", ("e1",)),),
        evidence_items=(
            EvidenceItem(
                evidence_id="e1",
                finding="first finding",
                criterion="first criterion",
                sufficiency="sufficient",
                sources=(EvidenceSource("supports", source),),
            ),
            EvidenceItem(
                evidence_id="e2",
                finding="second finding",
                criterion="second criterion",
                sufficiency="partial",
                sources=(EvidenceSource("context", source),),
            ),
        ),
    )


class ProductExperienceHardeningTests(unittest.TestCase):
    """覆盖来源、scope/readiness、反馈和 history 的产品契约。"""

    def test_source_summaries_are_deterministic_and_deduplicated(self) -> None:
        """同一 canonical message 即使来自不同 tool provenance 也只显示一次。"""

        source = MessageSource(
            run_id="run-1",
            tool_call_id="run-1/tool-call/1",
            tool_result_id="run-1/tool-call/1/result",
            result_item_id="message/qq:1:m1",
            session_id="qq:1",
            internal_message_id="qq:1:m1",
            snapshot=MessageDisplaySnapshot(
                session_display="Test chat",
                author_display="Author",
                timestamp_ms=1_700_000_000_000,
                timezone="UTC",
                excerpt="source excerpt",
                excerpt_truncated=False,
                source_message_id="m1",
            ),
        )

        duplicate_source = replace(
            source,
            run_id="run-2",
            tool_call_id="run-2/tool-call/1",
            tool_result_id="run-2/tool-call/1/result",
            result_item_id="message/qq:1:m1-copy",
        )
        artifact = _artifact(source)
        artifact = replace(
            artifact,
            evidence_items=artifact.evidence_items
            + (EvidenceItem(
                evidence_id="e3",
                finding="same canonical message",
                criterion="deduplication",
                sufficiency="sufficient",
                sources=(EvidenceSource("context", duplicate_source),),
            ),),
        )

        summaries = answer_source_summaries(artifact)

        self.assertEqual(len(summaries), 1)
        self.assertIsInstance(summaries[0], AnswerSourceSummary)
        self.assertEqual(summaries[0].index, 1)
        self.assertEqual(summaries[0].evidence_ids, ("e1", "e2", "e3"))
        self.assertEqual(summaries[0].relations, ("supports", "context"))

    def test_conversation_scope_round_trips_and_legacy_scope_is_null(self) -> None:
        """新记录保存 scope，旧式空记录保持不可猜测的 NULL。"""

        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteConversationStore(Path(temporary) / "conversation.sqlite3")
            scoped = ExecutionScope(
                allowed_session_ids=("qq:1",),
                start_timestamp=100,
                end_timestamp=200,
                max_results=7,
            )
            scoped_conversation = store.create_conversation(scoped)
            legacy_conversation = store.create_conversation()

            restored = store.get_conversation(scoped_conversation.conversation_id)
            legacy = store.get_conversation(legacy_conversation.conversation_id)

            self.assertEqual(restored.scope, scoped)
            self.assertIsNone(legacy.scope)
            store.close()

    def test_history_title_is_first_user_query_and_order_is_deterministic(self) -> None:
        """history 只读取 bounded 首问标题，更新顺序相同时按 id 稳定排序。"""

        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteConversationStore(Path(temporary) / "conversation.sqlite3")
            conversation = store.create_conversation(ExecutionScope(allowed_session_ids=("qq:1",)))
            store.commit_turn(
                conversation.conversation_id,
                "Why did the import fail?",
                AnswerArtifact(content_blocks=(AnswerContentBlock("answer", "It failed."),)),
            )

            summaries = store.list_summaries()

            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].title, "Why did the import fail?")
            self.assertEqual(summaries[0].message_count, 2)
            self.assertEqual(summaries[0].scope, conversation.scope)
            store.close()

    def test_feedback_is_separate_and_upserts_one_query(self) -> None:
        """反馈更新 rating/note，但保留同一条 feedback identity。"""

        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteFeedbackStore(Path(temporary) / "feedback.sqlite3")
            first = FeedbackRecord(
                feedback_id="pending",
                created_at="pending",
                updated_at="pending",
                conversation_id="conversation-1",
                trace_id="trace-1",
                run_id="run-1",
                scope_snapshot={"allowed_session_ids": ("qq:1",)},
                rating="good",
                note="clear",
            )
            second = FeedbackRecord(
                feedback_id="pending",
                created_at="pending",
                updated_at="pending",
                conversation_id="conversation-1",
                trace_id="trace-1",
                run_id="run-2",
                scope_snapshot={"allowed_session_ids": ("qq:1",)},
                rating="bad",
                note="needs context",
            )

            saved_first = store.save(first)
            saved_second = store.save(second)
            restored = store.get("conversation-1", "trace-1")

            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(saved_first.feedback_id, saved_second.feedback_id)
            self.assertEqual(restored.rating, "bad")
            self.assertEqual(restored.note, "needs context")
            self.assertEqual(restored.feedback_kind, "user_experiential")
            store.close()

    def test_application_readiness_is_local_and_does_not_rebuild(self) -> None:
        """新数据库 readiness 显示空数据与 missing semantic，而非触发重建。"""

        with tempfile.TemporaryDirectory() as temporary:
            with create_application(Path(temporary) / "app.sqlite3") as application:
                readiness = application.readiness()

            self.assertEqual(readiness.database_status, "ready")
            self.assertEqual(readiness.session_count, 0)
            self.assertEqual(readiness.message_count, 0)
            self.assertIsNotNone(readiness.semantic)
            assert readiness.semantic is not None
            self.assertEqual(readiness.semantic.status, "missing")


if __name__ == "__main__":
    unittest.main()
