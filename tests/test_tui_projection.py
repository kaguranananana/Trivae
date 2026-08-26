"""TuiProjectionEngine 的确定性事件投影测试。"""

from __future__ import annotations

import unittest
from typing import cast

from trivae.interfaces.tui.models import TuiProjectionEngine
from trivae.query.streaming import QueryStreamEvent


def _event(event_type: str, **kwargs: object) -> QueryStreamEvent:
    """构造最小合法 QueryStreamEvent；sequence 由调用方给定。"""

    return QueryStreamEvent(type=cast(object, event_type), sequence=next(_COUNTER), **kwargs)  # type: ignore[arg-type]


from itertools import count  # noqa: E402

_COUNTER = count(start=1)


class ProjectionThinkingTests(unittest.TestCase):
    """thinking 事件的行维护与不渲染文本边界。"""

    def test_thinking_deltas_update_a_single_row_and_completed_records_duration(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        changes = []
        changes.extend(engine.apply(_event("thinking.delta", content="alpha")))
        # reasoning 文本不允许进入 UI state。
        self.assertIsNone(changes[0].block.streaming_text)
        changes.extend(engine.apply(_event("thinking.delta", content="beta")))

        thinking_blocks = [
            change.block for change in changes if change.block is not None and change.block.kind == "thinking"
        ]
        self.assertEqual(len(thinking_blocks), 1)
        created = [change for change in changes if change.action == "block_created"]
        self.assertEqual(len(created), 1)
        for change in changes[1:]:
            self.assertEqual(change.action, "block_updated")

        clock = {"now": 1.5}
        completed_engine = TuiProjectionEngine(clock=lambda: clock["now"])
        completed_engine.begin_round("问题")
        completed_engine.apply(_event("thinking.delta", content="x"))
        clock["now"] = 2.8
        end_changes = completed_engine.apply(_event("thinking.completed"))
        self.assertEqual(end_changes[0].action, "block_updated")
        assert end_changes[0].block is not None
        self.assertEqual(end_changes[0].block.status, "completed")
        self.assertAlmostEqual(end_changes[0].block.duration_ms or 0.0, 1300.0)

    def test_thinking_visibility_marker_does_not_leak_reasoning_text_into_state(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        changes = engine.apply(
            _event(
                "thinking.delta",
                content="secret internal scratchpad",
                thinking_visibility="public_summary",
            )
        )
        assert changes[0].block is not None
        self.assertNotIn("scratchpad", str(changes[0].block))


class ProjectionToolIdentityTests(unittest.TestCase):
    """同 tool 多次调用的 identity 关联与乱序完成。"""

    def test_same_tool_name_two_calls_update_their_own_blocks(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        engine.apply(_event("tool.started", tool_name="search_messages", tool_call_id="call-A"))
        engine.apply(_event("tool.started", tool_name="search_messages", tool_call_id="call-B"))

        engine.apply(
            _event(
                "tool.completed",
                tool_name="search_messages",
                tool_call_id="call-B",
                duration_ms=1700,
            )
        )
        updated_a = engine.apply(
            _event(
                "tool.completed",
                tool_name="search_messages",
                tool_call_id="call-A",
                duration_ms=900,
            )
        )

        round_blocks = engine.blocks_for_debug(1)
        by_id = {block.block_id: block for block in round_blocks}
        self.assertEqual(by_id["tool:call-B"].status, "completed")
        self.assertEqual(by_id["tool:call-B"].duration_ms, 1700)
        self.assertEqual(by_id["tool:call-A"].status, "completed")
        self.assertEqual(by_id["tool:call-A"].duration_ms, 900)
        self.assertEqual(updated_a[-1].block.block_id, "tool:call-A")

    def test_tool_failed_marks_the_same_block_expanded_with_error_fields(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        engine.apply(_event("tool.started", tool_name="execute_sql", tool_call_id="call-7"))
        changes = engine.apply(
            _event(
                "tool.failed",
                tool_name="execute_sql",
                tool_call_id="call-7",
                duration_ms=120,
                error_code="SQL_READ_ONLY_VIOLATION",
                error_message="not read-only",
            )
        )
        last = changes[-1]
        assert last.block is not None
        self.assertEqual(last.action, "block_updated")
        self.assertEqual(last.block.status, "failed")
        self.assertTrue(last.block.expanded)
        self.assertEqual(last.block.error_code, "SQL_READ_ONLY_VIOLATION")


class ProjectionStreamingTests(unittest.TestCase):
    """answer delta 累积与 authoritative 替换。"""

    def test_answer_deltas_accumulate_in_one_block_then_finalized_text_replaces(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        engine.apply(_event("answer.delta", content="最近"))
        engine.apply(_event("answer.delta", content="推荐包括…"))
        appended = engine.apply(_event("answer.delta", content=" GitHub repos"))
        self.assertEqual(appended[0].action, "answer_appended")

        finalized = engine.apply(_event("answer.completed", content="权威最终答案"))
        self.assertEqual(finalized[0].action, "answer_finalized")
        assert finalized[0].block is not None
        self.assertEqual(finalized[0].block.streaming_text, "权威最终答案")
        self.assertEqual(finalized[0].block.status, "completed")

        blocks = engine.blocks_for_debug(1)
        answers = [block for block in blocks if block.kind == "answer"]
        self.assertEqual(len(answers), 1)

    def test_answer_completed_without_any_delta_creates_full_answer_block(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        finalized = engine.apply(_event("answer.completed", content="完整回答"))
        assert finalized[0].block is not None
        self.assertEqual(finalized[0].action, "answer_finalized")
        self.assertTrue(finalized[0].block.expanded)


class ProjectionAggregationTests(unittest.TestCase):
    """retrieval 聚合、route/plan 行为与 usage 合并。"""

    def test_retrieval_completion_merges_into_running_tool_metrics(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        engine.apply(_event("tool.started", tool_name="search_messages", tool_call_id="c1"))
        retrieval = engine.apply(
            _event(
                "retrieval.completed",
                result_summary={"candidate_count": 128, "returned_messages": 100, "partial": False},
                duration_ms=1300,
            )
        )
        self.assertEqual(retrieval[0].action, "block_updated")
        blocks = engine.blocks_for_debug(1)
        tools = [block for block in blocks if block.kind == "tool"]
        retrievals = [block for block in blocks if block.kind == "retrieval"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(retrievals, [])
        self.assertEqual(tools[0].metrics.get("candidate_count"), 128)
        self.assertEqual(tools[0].metrics.get("returned_messages"), 100)

    def test_retrieval_without_running_tool_becomes_standalone_row(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        engine.apply(_event("retrieval.completed", result_summary={"candidate_count": 40}, duration_ms=900))
        blocks = engine.blocks_for_debug(1)
        self.assertTrue(any(block.kind == "retrieval" and block.status == "completed" for block in blocks))

    def test_partial_and_truncated_flags_survive_merge(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        engine.apply(_event("tool.started", tool_name="semantic_search", tool_call_id="s1"))
        engine.apply(
            _event(
                "retrieval.completed",
                result_summary={"candidate_count": 74, "truncated": True},
                duration_ms=800,
            )
        )
        blocks = engine.blocks_for_debug(1)
        tool = next(block for block in blocks if block.kind == "tool")
        self.assertTrue(bool(tool.metrics.get("truncated")))

    def test_route_plan_and_usage_are_recorded_from_real_events_only(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        engine.apply(_event("route.completed", route="planned_execution"))
        engine.apply(
            _event(
                "plan.completed",
                plan={
                    "steps": [
                        {"goal": "确定时间范围"},
                        {"goal": "搜索相关消息"},
                    ],
                    "success_criteria": "找到具体资源",
                },
            )
        )
        engine.apply(_event("usage.updated", usage={"input_tokens": 10}))
        engine.apply(_event("usage.updated", usage={"output_tokens": 20}))

        blocks = engine.blocks_for_debug(1)
        plan = next(block for block in blocks if block.kind == "plan")
        assert plan.result_summary is not None
        self.assertEqual(plan.title, "分析计划 · 2 步")
        self.assertFalse(plan.expanded)
        self.assertEqual(plan.result_summary["success_criteria"], "找到具体资源")

    def test_plan_failed_creates_auto_expanded_error_row(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        changes = engine.apply(
            _event("plan.failed", error_code="PLANNER_PARSE_FAILED", error_message="bad json")
        )
        created = changes[0]
        assert created.block is not None
        self.assertEqual(created.block.kind, "error")
        self.assertTrue(created.block.expanded)


class ProjectionFoldingTests(unittest.TestCase):
    """两阶段聚合与手动展开持久化。"""

    def _run_started_with_tools(self, engine: TuiProjectionEngine) -> None:
        engine.apply(_event("thinking.delta", content="a"))
        engine.apply(_event("thinking.completed"))
        engine.apply(_event("tool.started", tool_name="search_messages", tool_call_id="t1"))
        engine.apply(_event("tool.completed", tool_name="search_messages", tool_call_id="t1", duration_ms=800))
        engine.apply(_event("answer.delta", content="回答"))

    def test_completed_round_collapses_process_blocks_but_keeps_answer_outside(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        self._run_started_with_tools(engine)
        engine.apply(_event("query.completed"))
        change = engine.drain_pending_collapse()
        assert change is not None and change.group is not None

        self.assertEqual(change.group.step_count, 2)
        self.assertFalse(change.group.default_expanded)
        kinds = {block.kind for block in change.group.blocks}
        self.assertEqual(kinds, {"thinking", "tool"})
        remaining = [block for block in engine.blocks_for_debug(1)]
        self.assertEqual([block.kind for block in remaining], ["answer"])

    def test_manual_expansion_survives_collapse_and_automatic_policies(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        engine.apply(_event("tool.started", tool_name="semantic_search", tool_call_id="t2"))
        updated = engine.set_manual_expanded(1, "tool:t2", True)
        self.assertIsNotNone(updated)
        engine.apply(_event("tool.completed", tool_name="semantic_search", tool_call_id="t2", duration_ms=200))
        blocks = {block.block_id: block for block in engine.blocks_for_debug(1)}
        # 手动展开优先于自动折叠策略。
        self.assertTrue(blocks["tool:t2"].manually_expanded)
        self.assertTrue(blocks["tool:t2"].expanded)

    def test_failed_terminal_round_defaults_group_to_expanded(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        self._run_started_with_tools(engine)
        engine.apply(
            _event("query.failed", error_code="PROVIDER.STREAM_FAILED", error_message="stream stopped")
        )
        change = engine.drain_pending_collapse()
        assert change is not None and change.group is not None
        self.assertTrue(change.group.default_expanded)


class ProjectionTerminalTests(unittest.TestCase):
    """controller 级失败/中断收尾与轮外事件忽略。"""

    def test_finalize_interrupted_adds_error_row_and_ignores_late_events(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        engine.begin_round("问题")
        engine.apply(_event("tool.started", tool_name="find_members", tool_call_id="t9"))
        changes = engine.finalize_interrupted(1)
        created = changes[0]
        assert created.block is not None
        self.assertEqual(created.block.kind, "error")
        self.assertTrue(created.block.expanded)

        late = engine.apply(_event("answer.delta", content="too late"))
        self.assertEqual(late, ())
        # 中断轮同样会折叠，但默认展开便于用户检查中断现场。
        collapse = engine.drain_pending_collapse()
        assert collapse is not None and collapse.group is not None
        self.assertTrue(collapse.group.default_expanded)

    def test_finalize_failed_outside_active_round_is_ignored(self) -> None:
        engine = TuiProjectionEngine(clock=lambda: 0.0)
        self.assertEqual(
            engine.finalize_failed(99, error_code="X", message="boom"),
            (),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
