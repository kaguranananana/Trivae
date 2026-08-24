from __future__ import annotations

import unittest
from io import StringIO

from trivae.interfaces.cli_renderer import CliEventRenderer
from trivae.query.streaming import QueryStreamEvent, QueryStreamEventType


def _event(event_type: QueryStreamEventType, sequence: int, **values: object) -> QueryStreamEvent:
    """以最小字段构造流事件，让测试只关注 Renderer 的终端职责。"""

    return QueryStreamEvent(type=event_type, sequence=sequence, **values)


class CliEventRendererTests(unittest.TestCase):
    """验证真实事件顺序、流式片段和终端段恢复。"""

    def test_multi_tool_sequence_preserves_fragment_order_without_cot(self) -> None:
        """多轮 Action/Result 后 Answer token 保持顺序，CoT 不进入终端。"""

        output = StringIO()
        renderer = CliEventRenderer(output)
        events = (
            _event("thinking.delta", 1, content="先检索"),
            _event("tool.started", 2, tool_name="search_a", arguments={"keyword": "GitHub"}),
            _event("tool.completed", 3, tool_name="search_a"),
            _event("thinking.delta", 4, content="再核对"),
            _event("tool.started", 5, tool_name="search_b", arguments={"days": 14}),
            _event("tool.completed", 6, tool_name="search_b"),
            _event("answer.delta", 7, content="近两周"),
            _event("answer.delta", 8, content="推荐了两个项目。"),
            _event("answer.completed", 9, content="近两周推荐了两个项目。"),
            _event("query.completed", 10),
        )

        for event in events:
            renderer.handle(event)
        renderer.finish()

        self.assertEqual(
            output.getvalue(),
            "Action: search_a\n"
            "  keyword: GitHub\n"
            "✓ search_a completed\n"
            "Action: search_b\n"
            "  days: 14\n"
            "✓ search_b completed\n"
            "Answer:\n"
            "近两周推荐了两个项目。\n",
        )

    def test_empty_or_missing_reasoning_does_not_print_thinking(self) -> None:
        """Provider 不返回 reasoning 或只返回空 delta 时完全不出现 Thinking 标签。"""

        output = StringIO()
        renderer = CliEventRenderer(output)

        renderer.handle(_event("thinking.delta", 1, content=""))
        renderer.handle(_event("answer.delta", 2, content="直接回答"))
        renderer.handle(_event("answer.completed", 3, content="直接回答"))

        self.assertEqual(output.getvalue(), "Answer:\n直接回答\n")
        self.assertNotIn("Thinking", output.getvalue())

    def test_retrieval_uses_only_real_structured_counts_including_zero(self) -> None:
        """0 result 必须按真实结构化统计显示，不能用漂亮文案编造数量。"""

        output = StringIO()
        renderer = CliEventRenderer(output)

        renderer.handle(
            _event(
                "retrieval.completed",
                1,
                result_summary={"candidate_count": 0, "total_hits": 0, "returned_messages": 0},
            )
        )

        self.assertEqual(output.getvalue(), "✓ Retrieval completed: 0 hits, 0 total, 0 messages\n")

    def test_failure_closes_open_segment_and_restores_next_line(self) -> None:
        """Provider/Query failure 先关闭已有 preview，再输出错误并恢复终端。"""

        output = StringIO()
        renderer = CliEventRenderer(output)

        renderer.handle(_event("answer.delta", 1, content="未完成"))
        renderer.handle(
            _event(
                "query.failed",
                2,
                error_code="PROVIDER.STREAM_FAILED",
                error_message="stream interrupted",
            )
        )
        renderer.finish()

        self.assertEqual(
            output.getvalue(),
            "Answer:\n未完成\nError: The model stream stopped before the answer completed.\n",
        )
        self.assertTrue(renderer.answer_rendered)
        self.assertTrue(renderer.failure_rendered)

    def test_tool_failure_is_followed_by_recovery_and_answer(self) -> None:
        """已分类 Tool failure 结束当前段；Agent 恢复后可继续 Thinking 和 Answer。"""

        output = StringIO()
        renderer = CliEventRenderer(output)

        events = (
            _event("thinking.delta", 1, content="先尝试检索"),
            _event("tool.started", 2, tool_name="search_messages", arguments={"keyword": "repo"}),
            _event("tool.failed", 3, tool_name="search_messages", error_code="RETRIEVAL_UNAVAILABLE"),
            _event("thinking.delta", 4, content="改用已有证据"),
            _event("answer.delta", 5, content="当前只能给出部分结果。"),
            _event("answer.completed", 6, content="当前只能给出部分结果。"),
        )
        for event in events:
            renderer.handle(event)

        self.assertEqual(
            output.getvalue(),
            "Action: Search messages\n"
            "  keyword: repo\n"
            "✗ Search messages failed: Search is unavailable; the answer may be partial.\n"
            "Answer:\n"
            "当前只能给出部分结果。\n",
        )

    def test_verbose_adds_diagnostics_without_raw_payload(self) -> None:
        """verbose 展示归一化 metadata、duration 与 usage，不读取 provider raw 字段。"""

        output = StringIO()
        renderer = CliEventRenderer(output, verbose=True)

        renderer.handle(
            _event(
                "route.completed",
                1,
                trace_id="trace-1",
                route="planned_execution",
                source_operation="router.decision",
                source_sequence=5,
                metadata={"source": "llm", "confidence": 0.8, "reason": "multi-stage"},
            )
        )
        renderer.handle(
            _event(
                "retrieval.completed",
                2,
                result_summary={
                    "candidate_count": 3,
                    "expanded_count": 9,
                    "coverage": {"status": "complete"},
                    "partial": False,
                    "truncated": False,
                },
                duration_ms=12.5,
            )
        )
        renderer.handle(_event("usage.updated", 3, usage={"input_tokens": 11, "output_tokens": 7}))

        rendered = output.getvalue()
        self.assertIn("Route: planned", rendered)
        self.assertIn("confidence=0.8", rendered)
        self.assertIn("source: router.decision", rendered)
        self.assertIn("3 hits, 9 expanded", rendered)
        self.assertIn("duration_ms=12.5", rendered)
        self.assertIn("input_tokens=11", rendered)
        self.assertNotIn("stream_sequence", rendered)
        self.assertNotIn("trace-1", rendered)
        self.assertNotIn("{\"", rendered)

    def test_authoritative_answer_is_used_when_provider_sent_no_delta(self) -> None:
        """没有 content delta 时，answer.completed 仍展示 Finalizer 的完整正式回答。"""

        output = StringIO()
        renderer = CliEventRenderer(output)

        renderer.handle(_event("answer.completed", 1, content="完整答案"))

        self.assertEqual(output.getvalue(), "Answer:\n完整答案\n")
        self.assertTrue(renderer.answer_rendered)


if __name__ == "__main__":
    unittest.main()
