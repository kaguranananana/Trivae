"""交互式 CLI 的 QueryStreamEvent 终端投影。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, TextIO

from trivae.query.streaming import QueryStreamEvent

_Segment = Literal["thinking", "answer"]

_TOOL_LABELS = {
    "search_messages": "Search messages",
    "lexical_search": "Search messages",
    "semantic_search": "Semantic search",
    "get_message_context": "Read nearby context",
    "find_members": "Find members",
    "get_schema": "Inspect schema",
    "execute_sql": "Run structured query",
}

_ERROR_LABELS = {
    "SEMANTIC_INDEX_NOT_READY": "Semantic index is not ready; run `trivae semantic rebuild` explicitly.",
    "SEMANTIC_INDEX_STALE": "Semantic index is stale; run `trivae semantic rebuild` explicitly.",
    "SEMANTIC_INDEX_STORAGE": "Semantic index storage is unavailable.",
    "PROVIDER.STREAM_FAILED": "The model stream stopped before the answer completed.",
    "CONVERSATION_COMMIT_FAILED": "The answer was generated but could not be saved.",
    "QUERY_EXCEPTION": "The query failed unexpectedly; check the trace log.",
    "RETRIEVAL_LEXICAL_INDEX": "Keyword search is unavailable; rebuild the lexical index explicitly.",
    "RETRIEVAL_UNAVAILABLE": "Search is unavailable; the answer may be partial.",
    "SCOPE_VIOLATION": "That request is outside the selected data scope.",
    "MESSAGE_NOT_FOUND": "The cited message is no longer available in the selected scope.",
    "SQL_READ_ONLY_VIOLATION": "The structured query was rejected because it is not read-only.",
    "SQL_SCOPE_VIOLATION": "The structured query attempted to leave the selected scope.",
    "STRUCTURED_VALUE_MISMATCH": "The answer cited a structured value that was not returned by the tool; the answer was not saved.",
    "STRUCTURED_SOURCE_ID_MISMATCH": "The answer cited an unknown structured source; the answer was not saved.",
    "UNRESOLVED_STRUCTURED_SOURCE": "The cited structured source was not found in the tool result; the answer was not saved.",
    "MISSING_EVIDENCE": "The tool-backed answer did not include claim evidence; the answer was not saved.",
}


class CliEventRenderer:
    """集中处理流式片段、阶段切换和 normal/verbose 展示策略。"""

    def __init__(self, stream: TextIO, *, verbose: bool = False) -> None:
        """绑定一个支持 write/flush 的文本流，不在业务模块中直接打印。"""

        self._stream = stream
        self._verbose = verbose
        self._segment: _Segment | None = None
        self._line_open = False
        self._answer_rendered = False
        self._failure_rendered = False

    @property
    def answer_rendered(self) -> bool:
        """报告正式回答或回答增量是否已经出现在终端。"""

        return self._answer_rendered

    @property
    def failure_rendered(self) -> bool:
        """报告 Query terminal failure 是否已经投影，避免完成结果重复报错。"""

        return self._failure_rendered

    def handle(self, event: QueryStreamEvent) -> None:
        """按真实事件类型顺序投影；Renderer 不推断 Agent 当前业务阶段。"""

        if event.type == "thinking.delta":
            self._render_thinking_delta(event)
            return
        if event.type == "thinking.completed":
            self._close_segment("thinking")
            return
        if event.type == "answer.delta":
            self._render_answer_delta(event)
            return
        if event.type == "answer.completed":
            self._render_answer_completed(event)
            return

        # 状态事件必须先关闭开放文本段，避免 Tool/Route 行粘到 reasoning 或 answer 后面。
        self._close_segment()
        if event.type == "query.started":
            if self._verbose:
                self._line("Query started")
        elif event.type == "route.completed":
            self._render_route(event)
        elif event.type in {"plan.completed", "plan.failed"}:
            self._render_plan(event)
        elif event.type == "tool.started":
            self._render_tool_started(event)
        elif event.type in {"tool.completed", "tool.failed"}:
            self._render_tool_terminal(event)
        elif event.type == "retrieval.started":
            if self._verbose:
                self._line("Retrieval started")
        elif event.type in {"retrieval.completed", "retrieval.failed"}:
            self._render_retrieval_terminal(event)
        elif event.type == "usage.updated":
            if self._verbose and event.usage:
                self._line(f"Usage: {self._format_mapping(event.usage, max_items=12, max_chars=800)}")
        elif event.type == "query.completed":
            if self._verbose:
                self._line("✓ Query completed")
        elif event.type == "query.failed":
            self._render_query_terminal(event, prefix="Error")
        elif event.type == "query.aborted":
            self._render_query_terminal(event, prefix="Aborted")

        self._render_verbose_source(event)

    def finish(self) -> None:
        """在完成、异常或 Ctrl+C 后恢复到完整行，保证下一次 prompt 不粘连。"""

        self._close_segment()
        self._stream.flush()

    def _render_thinking_delta(self, event: QueryStreamEvent) -> None:
        """消费 reasoning stream 以保持顺序，但不把 provider 推理文本投影到终端。"""

        # provider 字段名不能证明内容是安全摘要；真实 smoke 已证明 summary 也可能是长内部推理。
        return

    def _render_answer_delta(self, event: QueryStreamEvent) -> None:
        """连续写入 AnswerArtifact 正文片段，不为每个 token 自动换行。"""

        if not event.content:
            return
        if self._segment != "answer":
            self._close_segment()
            self._line("Answer:")
            self._segment = "answer"
        self._answer_rendered = True
        self._fragment(event.content)

    def _render_answer_completed(self, event: QueryStreamEvent) -> None:
        """无 delta 时展示 authoritative answer；已有 preview 时只完成段落。"""

        if not self._answer_rendered and event.content:
            self._line("Answer:")
            self._segment = "answer"
            self._answer_rendered = True
            self._fragment(event.content)
        self._close_segment("answer")
        self._render_verbose_source(event)

    def _render_route(self, event: QueryStreamEvent) -> None:
        """展示 Router 的真实决定；verbose 才附带诊断字段。"""

        route = {
            "planned_execution": "planned",
            "standard_execution": "standard",
        }.get(event.route or "", event.route or "unknown")
        self._line(f"Route: {route}")
        if not self._verbose:
            return
        details = {
            key: event.metadata[key]
            for key in ("source", "confidence", "reason")
            if key in event.metadata and event.metadata[key] not in (None, "")
        }
        if details:
            self._line(f"  {self._format_mapping(details, max_items=3, max_chars=1000)}")

    def _render_plan(self, event: QueryStreamEvent) -> None:
        """展示 Planner 已产生的 bounded soft guidance，不制造 step 执行状态。"""

        if event.type == "plan.failed":
            self._line(f"✗ Plan failed: {self._error_text(event)}")
            if self._verbose and event.metadata:
                # verbose 只显示 normalized Planner facts；response 正文留给完整 Debug Trace。
                keys = (
                    "provider",
                    "model",
                    "planner_latency_ms",
                    "provider_latency_ms",
                    "finish_reason",
                    "output_tokens",
                    "response_length",
                    "parse_stage",
                    "failure_detail_code",
                    "diagnostic",
                )
                details = {key: event.metadata[key] for key in keys if key in event.metadata}
                if details:
                    self._line(f"  {self._format_mapping(details, max_items=12, max_chars=1800)}")
            return
        if not event.plan:
            self._line("Plan: ready")
            return

        self._line("Plan: ready")
        if not self._verbose:
            return
        steps = event.plan.get("steps")
        if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes, bytearray)):
            for index, step in enumerate(steps, start=1):
                if isinstance(step, Mapping):
                    goal = step.get("goal")
                else:
                    goal = step
                if goal not in (None, ""):
                    self._line(f"  {index}. {self._bounded_text(goal, 240)}")

        for key in ("title", "intent", "success_criteria"):
            value = event.plan.get(key)
            if value not in (None, "", (), []):
                self._line(f"  {key}: {self._bounded_text(value, 800)}")

    def _render_tool_started(self, event: QueryStreamEvent) -> None:
        """Tool 确定调用后立即显示名称与经过 Query adapter 投影的参数。"""

        tool_name = _TOOL_LABELS.get(event.tool_name or "", event.tool_name or "unknown")
        self._line(f"Action: {tool_name}")
        if not event.arguments:
            return
        max_items = 20 if self._verbose else 5
        max_chars = 1800 if self._verbose else 480
        for key, value in list(event.arguments.items())[:max_items]:
            if value not in (None, "", (), [], {}):
                self._line(f"  {key}: {self._bounded_text(value, max_chars)}")

    def _render_tool_terminal(self, event: QueryStreamEvent) -> None:
        """Tool Result 默认只展示结构化摘要，不 dump 聊天正文。"""

        tool_name = _TOOL_LABELS.get(event.tool_name or "", event.tool_name or "tool")
        if event.type == "tool.failed":
            self._line(f"✗ {tool_name} failed: {self._error_text(event)}")
            return
        self._line(f"✓ {tool_name} completed")
        if self._verbose and event.result_summary:
            self._line(f"  result: {self._format_mapping(event.result_summary, max_items=20, max_chars=1800)}")

    def _render_retrieval_terminal(self, event: QueryStreamEvent) -> None:
        """Retrieval 仅显示底层真实提供的命中、扩展和完整性数据。"""

        if event.type == "retrieval.failed":
            self._line(f"✗ Retrieval failed: {self._error_text(event)}")
            return

        summary = event.result_summary or {}
        counts: list[str] = []
        for key, label in (
            ("candidate_count", "hits"),
            ("total_hits", "total"),
            ("expanded_count", "expanded"),
            ("returned_messages", "messages"),
        ):
            value = summary.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                counts.append(f"{value} {label}")
        suffix = ": " + ", ".join(counts) if counts else ""
        self._line(f"✓ Retrieval completed{suffix}")

        if self._verbose:
            details = {
                key: summary[key] for key in ("coverage", "partial", "truncated", "latency_ms") if key in summary
            }
            if event.duration_ms is not None:
                details["duration_ms"] = event.duration_ms
            if details:
                self._line(f"  {self._format_mapping(details, max_items=8, max_chars=1200)}")

    def _render_query_terminal(self, event: QueryStreamEvent, *, prefix: str) -> None:
        """显示 secret-safe terminal error，并标记本轮已经完成失败投影。"""

        self._failure_rendered = True
        self._line(f"{prefix}: {self._error_text(event)}")

    def _render_verbose_source(self, event: QueryStreamEvent) -> None:
        """verbose 模式只展示阶段来源名称，不输出 raw event/sequence/identity。"""

        if not self._verbose or event.type.endswith(".delta"):
            return
        if event.source_operation:
            self._line(f"  source: {event.source_operation}")

    def _error_text(self, event: QueryStreamEvent) -> str:
        """组合 adapter 已归一化的错误信息，不猜测底层异常。"""

        friendly = _ERROR_LABELS.get(event.error_code or "")
        if friendly is not None:
            return f"{friendly} ({event.error_code})" if self._verbose else friendly
        if event.error_message:
            return event.error_message
        if event.error_code:
            return (
                f"Operation failed ({event.error_code})"
                if self._verbose
                else "Operation failed; inspect the trace diagnostics."
            )
        return "unknown error"

    def _close_segment(self, expected: _Segment | None = None) -> None:
        """只关闭指定或当前开放段；没有输出字符时不额外制造空行。"""

        if self._segment is None or (expected is not None and self._segment != expected):
            return
        if self._line_open:
            self._stream.write("\n")
            self._stream.flush()
        self._segment = None
        self._line_open = False

    def _fragment(self, content: str) -> None:
        """原样写入流式片段，并依据最后一个字符维护终端行状态。"""

        self._stream.write(content)
        self._stream.flush()
        self._line_open = not content.endswith("\n")

    def _line(self, content: str) -> None:
        """输出一个完整状态行；所有阶段行统一走此处，便于稳定测试。"""

        self._stream.write(f"{content}\n")
        self._stream.flush()
        self._line_open = False

    def _bounded_text(self, value: object, max_chars: int) -> str:
        """把普通结构格式化为单行 key=value 摘要，避免 JSON 污染终端。"""

        if isinstance(value, str):
            rendered = value
        elif isinstance(value, Mapping):
            rendered = ", ".join(
                f"{key}={self._bounded_text(item, max(80, max_chars // 4))}"
                for key, item in list(value.items())[:12]
            )
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            rendered = ", ".join(
                self._bounded_text(item, max(80, max_chars // 4))
                for item in list(value)[:12]
            )
        else:
            rendered = str(value)
        rendered = rendered.replace("\n", "\\n")
        if len(rendered) <= max_chars:
            return rendered
        return f"{rendered[:max_chars]}…"

    def _format_mapping(self, value: Mapping[str, object], *, max_items: int, max_chars: int) -> str:
        """在既定 item/字符上限内生成稳定的 key=value 摘要。"""

        items = list(value.items())
        selected = items[:max_items]
        rendered = ", ".join(f"{key}={self._bounded_text(item, max_chars)}" for key, item in selected)
        if len(items) > max_items:
            rendered = f"{rendered}, …"
        return self._bounded_text(rendered, max_chars)
