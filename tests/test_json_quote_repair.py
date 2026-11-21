"""Tests for narrowly scoped unescaped ASCII quote repair in structured final answers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.query.contracts import QueryRequest
from trivae.query.evidence import (
    ToolMessageItem,
    ToolResultRecord,
    finalize_answer,
    finalize_answer_gracefully,
    scope_snapshot,
)
from trivae.query.json_repair import repair_unescaped_json_quotes
from trivae.query.runtime.contracts import RuntimeEvent, RuntimeResult, RuntimeToolCall
from trivae.query.streaming import AnswerDeltaParseError, QueryStreamAdapter, QueryStreamEvent
from trivae.retrieval.structured import MessageProjection


def _tool_record(run_id: str = "run-json-repair") -> ToolResultRecord:
    message = MessageProjection(
        internal_message_id="qq:100:1",
        session_id="qq:100",
        source_message_id="m1",
        sender_user_id="qq:u1",
        sender_platform_id="u1",
        sender_uin="10001",
        sender_name="Trusted Author",
        timestamp=1_000,
        seq=1,
        message_type="text",
        normalized_content="跨会话续做建议写进度文档，不要只靠聊天上下文。",
        reply_to_source_message_id=None,
        recalled=False,
        system=False,
        session_display="测试群",
    )
    return ToolResultRecord(
        run_id=run_id,
        tool_call_id=f"{run_id}/tool-call/1",
        tool_result_id=f"{run_id}/tool-call/1/result",
        tool_name="lexical_search",
        status="ok",
        scope_snapshot=scope_snapshot(ExecutionScope()),
        query_scope_snapshot={"keyword": "进度"},
        message_items=(ToolMessageItem(result_item_id="message/qq:100:m1", message=message, is_hit=True),),
    )


def test_repair_handles_case03_64k08_comma_and_embedded_json_shapes() -> None:
    case03 = (
        '{"claims": [{"text": "群里的共识是：跨会话续做的关键不是"不断提醒"，而是写进度文件", '
        '"finding": "跨会话靠进度文件", "criterion": "原文提及", "sufficiency": "sufficient", '
        '"sources": ["m1-1"], "limitations": []}], "limitations": []}'
    )
    repaired = repair_unescaped_json_quotes(case03)
    assert repaired is not None
    text, count = repaired
    assert count == 2
    assert json.loads(text)["claims"][0]["text"] == '群里的共识是：跨会话续做的关键不是"不断提醒"，而是写进度文件'

    sample64k = (
        '{"claims": [{"text": "2026-10-24 "卡普迪姆的 AI 交流小屋" 里有人反馈耗时较长", '
        '"finding": "耗时观察", "criterion": "原消息", "sufficiency": "partial", '
        '"sources": ["m1-1"], "limitations": ["来源称为"个人记录", 非基准测试"]}], "limitations": []}'
    )
    repaired2 = repair_unescaped_json_quotes(sample64k)
    assert repaired2 is not None
    text2, count2 = repaired2
    assert count2 == 4
    decoded2 = json.loads(text2)
    assert '"卡普迪姆的 AI 交流小屋"' in decoded2["claims"][0]["text"]
    assert '"个人记录", 非基准测试' in decoded2["claims"][0]["limitations"][0]

    embedded_snippet = (
        '{"claims": [{"text": "可以传 {"kind": "relative"}, 但注意由 Host 解析", '
        '"finding": "参数示例", "criterion": "原文", "sufficiency": "sufficient", '
        '"sources": ["m1-1"], "limitations": []}], "limitations": []}'
    )
    repaired3 = repair_unescaped_json_quotes(embedded_snippet)
    assert repaired3 is not None
    assert '{"kind": "relative"}, 但注意由 Host 解析' in json.loads(repaired3[0])["claims"][0]["text"]


@pytest.mark.parametrize(
    "payload",
    [
        '{"claims": []}',
        '{"claims": [],}',
        '{"claims": [{"text": "unclosed',
        r'{"claims": [{"text": "坏\x尾部"}]}',
        '[1, 2, 3]',
        'plain text answer',
        '{"claims": []} trailing',
        '{"claims": [{"text": "line1\nline2"}]}',
    ],
)
def test_repair_rejects_valid_or_non_quote_malformed_inputs(payload: str) -> None:
    assert repair_unescaped_json_quotes(payload) is None


@pytest.mark.parametrize("provisional", [False, True])
@pytest.mark.parametrize("chunk_width", [1, 7, 200])
def test_stream_adapter_recovers_unescaped_quote_across_chunk_boundaries(
    provisional: bool,
    chunk_width: int,
) -> None:
    raw = (
        '{"claims":[{"text":"关键不是"不断提醒"，而是进度文档","finding":"f","criterion":"c",'
        '"sufficiency":"sufficient","sources":["m1-1"],"limitations":[]}],"limitations":[]}'
    )
    events: list[QueryStreamEvent] = []
    adapter = QueryStreamAdapter(events.append, trace_id="trace-1", provisional_answer_streaming=provisional)
    adapter.handle_runtime_event(RuntimeEvent("turn_started", "deepseek", "deepseek-flash", 1, run_id="r1"))
    seq = 2
    for offset in range(0, len(raw), chunk_width):
        adapter.handle_runtime_event(
            RuntimeEvent("content_delta", "deepseek", "deepseek-flash", seq, text=raw[offset : offset + chunk_width], run_id="r1")
        )
        seq += 1
    adapter.handle_runtime_event(RuntimeEvent("turn_completed", "deepseek", "deepseek-flash", seq, run_id="r1"))
    adapter.handle_runtime_event(
        RuntimeEvent(
            "completed",
            "deepseek",
            "deepseek-flash",
            seq + 1,
            result=RuntimeResult(
                final_answer=raw, provider="deepseek", model="deepseek-flash", termination="completed", tool_calls=(), run_id="r1"
            ),
            run_id="r1",
        )
    )
    emitted = "".join(event.content or "" for event in events if event.type == "answer.delta")
    assert emitted == '关键不是"不断提醒"，而是进度文档'


def test_stream_adapter_re_raises_original_error_when_truncated_after_quote() -> None:
    raw = '{"claims":[{"text":"关键不是"不断'
    events: list[QueryStreamEvent] = []
    adapter = QueryStreamAdapter(events.append, trace_id="trace-2")
    adapter.handle_runtime_event(RuntimeEvent("turn_started", "deepseek", "deepseek-flash", 1, run_id="r2"))
    adapter.handle_runtime_event(RuntimeEvent("content_delta", "deepseek", "deepseek-flash", 2, text=raw, run_id="r2"))
    with pytest.raises(AnswerDeltaParseError) as exc_info:
        adapter.handle_runtime_event(RuntimeEvent("turn_completed", "deepseek", "deepseek-flash", 3, run_id="r2"))
    assert exc_info.value.diagnostics["unexpected"] == "不"


def test_finalize_answer_gracefully_repairs_quotes_without_weakening_strict_validation() -> None:
    record = _tool_record()
    raw = (
        '{"claims":[{"text":"关键不是"不断提醒"，而是进度文档","finding":"跨会话进度",'
        '"criterion":"原消息支持","sufficiency":"sufficient","sources":["m1-1"],"limitations":[]}],'
        '"limitations":[]}'
    )
    # Strict finalize_answer remains strict.
    with pytest.raises(Exception):
        finalize_answer(raw, run_id=record.run_id, tool_results=(record,), scope=ExecutionScope())

    result = finalize_answer_gracefully(raw, run_id=record.run_id, tool_results=(record,), scope=ExecutionScope())
    assert result.error is None
    assert result.artifact is not None
    assert result.diagnostics.status == "valid"
    assert result.diagnostics.degradation_codes == ("repaired_unescaped_json_quotes",)
    assert result.diagnostics.normalization_count == 2
    assert result.diagnostics.validated_citation_count == 1
    assert result.artifact.answer_text == '关键不是"不断提醒"，而是进度文档'

    # Forged citation must still fail / degrade strictly even after quote repair.
    forged = raw.replace('"m1-1"', '"m9-999"')
    forged_result = finalize_answer_gracefully(forged, run_id=record.run_id, tool_results=(record,), scope=ExecutionScope())
    assert forged_result.diagnostics.status == "degraded"
    assert forged_result.diagnostics.dropped_citation_count == 1
    assert "repaired_unescaped_json_quotes" in forged_result.diagnostics.degradation_codes


class _UnescapedQuoteStreamingRuntime:
    def __init__(self, record: ToolResultRecord, raw: str) -> None:
        self._record = record
        self._raw = raw

    async def stream(self, request):
        yield RuntimeEvent("run_started", "deepseek", "deepseek-flash", 1, run_id=self._record.run_id)
        yield RuntimeEvent("turn_started", "deepseek", "deepseek-flash", 2, run_id=self._record.run_id)
        tool_call = RuntimeToolCall(
            name="lexical_search",
            status="ok",
            tool_call_id=self._record.tool_call_id,
            round=1,
            tool_result_id=self._record.tool_result_id,
        )
        yield RuntimeEvent("tool_started", "deepseek", "deepseek-flash", 3, tool_name="lexical_search", tool_call=tool_call, run_id=self._record.run_id)
        yield RuntimeEvent("tool_completed", "deepseek", "deepseek-flash", 4, tool_name="lexical_search", tool_call=tool_call, tool_result=self._record, run_id=self._record.run_id)
        yield RuntimeEvent("turn_completed", "deepseek", "deepseek-flash", 5, run_id=self._record.run_id)
        yield RuntimeEvent("turn_started", "deepseek", "deepseek-flash", 6, run_id=self._record.run_id)
        seq = 7
        for offset in range(0, len(self._raw), 11):
            yield RuntimeEvent("content_delta", "deepseek", "deepseek-flash", seq, text=self._raw[offset : offset + 11], run_id=self._record.run_id)
            seq += 1
        yield RuntimeEvent("turn_completed", "deepseek", "deepseek-flash", seq, run_id=self._record.run_id)
        terminal = RuntimeResult(
            final_answer=self._raw,
            provider="deepseek",
            model="deepseek-flash",
            termination="completed",
            tool_calls=(tool_call,),
            tool_rounds=1,
            run_id=self._record.run_id,
            tool_results=(self._record,),
        )
        yield RuntimeEvent("completed", "deepseek", "deepseek-flash", seq + 1, result=terminal, run_id=self._record.run_id)

    async def run(self, request):
        terminal = None
        async for event in self.stream(request):
            if event.result is not None:
                terminal = event.result
        assert terminal is not None
        return terminal


def test_application_query_recovers_unescaped_quote_json_end_to_end(tmp_path: Path) -> None:
    record = _tool_record("run-e2e-quote")
    raw = (
        '{"claims":[{"text":"群友建议用"进度文件"跨会话续做。","finding":"进度文件",'
        '"criterion":"原消息支持","sufficiency":"sufficient","sources":["m1-1"],"limitations":[]}],'
        '"limitations":[]}'
    )
    app = create_application(tmp_path / "quote-repair.sqlite3", agent_runtime=_UnescapedQuoteStreamingRuntime(record, raw))
    try:
        result = asyncio.run(app.query(QueryRequest("怎么跨会话续做？", ExecutionScope())))
        assert result.is_successful
        assert result.finalization_status == "valid"
        assert result.answer_artifact is not None
        assert result.answer_artifact.answer_text == '群友建议用"进度文件"跨会话续做。'
        assert len(result.answer_artifact.evidence_items) == 1
        assert result.finalization_diagnostics is not None
        assert result.finalization_diagnostics.degradation_codes == ("repaired_unescaped_json_quotes",)
        assert result.finalization_diagnostics.normalization_count == 2
        trace = app.read_trace(result.trace_id)
        assert trace.terminal_status == "completed"
        fin = next(e for e in trace.timeline if e.operation == "answer.finalization.completed")
        assert fin.payload["degradation_codes"] == ["repaired_unescaped_json_quotes"]
        assert fin.payload["normalization_count"] == 2
    finally:
        app.close()
