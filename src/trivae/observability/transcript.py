"""从 canonical StoredTrace 派生人工可读的 Agent execution transcript。"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Literal

from trivae.observability.contracts import NormalizedQueryEvent, StoredTrace

TranscriptContextMode = Literal["delta", "full"]


def format_trace_summary(trace: StoredTrace) -> str:
    """从 canonical events 生成顶部摘要，不对执行质量做未经证实的归因。"""

    model_turns = sum(
        1 for event in trace.events if event.operation == "model.turn" and event.phase == "started"
    )
    tool_calls = sum(
        _model_action_count(event.payload.get("observable_output"))
        for event in trace.events
        if event.operation == "model.output"
    )
    planner_failures = sum(1 for event in trace.events if event.operation == "planner.failed")
    retrieval_events = tuple(
        event
        for event in trace.events
        if event.operation.startswith("retrieval.search.")
        and event.phase in {"completed", "failed", "skipped"}
    )
    partial_retrievals = sum(
        1
        for event in retrieval_events
        if event.outcome == "partial" or event.payload.get("partial") is True
    )
    truncated_retrievals = sum(
        1 for event in retrieval_events if event.payload.get("truncated") is True
    )
    final_answer_available = any(
        event.operation == "answer.finalization.completed"
        and isinstance(event.payload.get("answer_text"), str)
        for event in trace.events
    ) or any(
        event.operation == "runtime.run"
        and event.phase in {"completed", "failed", "aborted"}
        and _answer_from_runtime_payload(event.payload) is not None
        for event in trace.events
    )
    return "\n".join(
        (
            "Trace Summary",
            "-------------",
            f"terminal_outcome: {trace.terminal_outcome or '-'}",
            f"duration_ms: {_trace_duration_ms(trace)}",
            f"event_count: {len(trace.events)}",
            f"model_turns: {model_turns}",
            f"tool_calls: {tool_calls}",
            f"planner_failures: {planner_failures}",
            f"retrieval_partial_events: {partial_retrievals}",
            f"retrieval_truncated_events: {truncated_retrievals}",
            f"final_answer: {'available' if final_answer_available else 'not available'}",
            "",
        )
    )


def format_execution_transcript(
    trace: StoredTrace,
    *,
    context_mode: TranscriptContextMode = "delta",
) -> str:
    """按 Trace sequence 渲染 execution facts，不访问其他数据源。"""

    if context_mode not in {"delta", "full"}:
        raise ValueError(f"unsupported transcript context mode: {context_mode!r}")
    events = trace.events
    model_groups = _model_event_groups(events)
    call_names = _tool_call_names(events)
    rendered_turns: set[str] = set()
    lines = [
        "====================",
        "EXECUTION TRANSCRIPT",
        "====================",
        "",
    ]
    final_answer: str | None = None
    final_answer_limitations: tuple[str, ...] = ()
    turn_number = 0
    previous_model_context: tuple[Mapping[str, object], ...] | None = None

    for event in events:
        if event.operation == "query.received":
            _render_query(lines, event)
        elif event.operation == "context.prepared":
            _render_context(lines, event)
        elif event.operation == "router.decision":
            _render_router(lines, event)
        elif event.operation == "router.degraded":
            _render_router_degradation(lines, event)
        elif event.operation == "planner.started":
            _render_planner_started(lines, event)
        elif event.operation in {"planner.completed", "planner.failed", "planner.skipped"}:
            _render_planner(lines, event)
        elif event.operation == "model.turn" and event.phase == "started":
            if event.operation_id not in rendered_turns:
                turn_number += 1
                current_model_context = _render_model_turn_with_context(
                    lines,
                    turn_number,
                    event,
                    model_groups.get(event.operation_id, ()),
                    call_names,
                    context_mode=context_mode,
                    previous_context=previous_model_context,
                )
                previous_model_context = current_model_context
                rendered_turns.add(event.operation_id)
        elif event.operation == "runtime.tool.completed":
            _render_tool_execution(lines, event)
        elif event.operation.startswith("retrieval.search.") and event.phase in {
            "completed",
            "failed",
            "skipped",
        }:
            _render_retrieval(lines, event)
        elif event.operation == "evidence.prepare.completed":
            _render_evidence(lines, event)
        elif event.operation == "citation.validation.completed":
            _render_citation(lines, event)

        if event.operation == "answer.finalization.completed":
            answer_text = event.payload.get("answer_text")
            if isinstance(answer_text, str):
                final_answer = answer_text
                final_answer_limitations = event.limitations
        elif event.operation == "runtime.run" and event.phase in {
            "completed",
            "failed",
            "aborted",
        }:
            # 兼容早于 answer snapshot amendment 的 Trace；新 Trace 优先使用 finalization snapshot。
            if final_answer is None:
                final_answer = _answer_from_runtime_payload(event.payload)
                final_answer_limitations = event.limitations

    if final_answer is not None:
        _render_final_answer(lines, final_answer, final_answer_limitations)
    else:
        _section(lines, "[FINAL ANSWER]", ("not available",))
    return "\n".join(lines).rstrip() + "\n"


def _model_event_groups(
    events: tuple[NormalizedQueryEvent, ...],
) -> dict[str, tuple[NormalizedQueryEvent, ...]]:
    """把同一 model turn 的 started/output/usage/completed 事件按 operation 绑定。"""

    groups: dict[str, list[NormalizedQueryEvent]] = {}
    for event in events:
        if event.stage == "model" and event.operation in {"model.turn", "model.output", "model.usage"}:
            groups.setdefault(event.operation_id, []).append(event)
    return {operation_id: tuple(group) for operation_id, group in groups.items()}


def _tool_call_names(events: tuple[NormalizedQueryEvent, ...]) -> dict[str, str]:
    """建立 call_id 到 tool name 的短映射，供 Tool Result 标题使用。"""

    names: dict[str, str] = {}
    for event in events:
        for item in _items(event.payload.get("model_visible_context")):
            _remember_tool_call(names, item)
        for item in _items(event.payload.get("observable_output")):
            _remember_tool_call(names, item)
    return names


def _remember_tool_call(names: dict[str, str], item: Mapping[str, object]) -> None:
    """只从已经过 adapter 的 plain item 读取 tool call identity。"""

    if item.get("type") not in {"function_call", "custom_tool_call"}:
        return
    call_id = item.get("call_id")
    name = item.get("name")
    if isinstance(call_id, str) and isinstance(name, str) and name:
        names[call_id] = name


def _render_query(lines: list[str], event: NormalizedQueryEvent) -> None:
    """渲染 query 与 trusted scope，避免主 Transcript 展示过多内部 identity。"""

    payload = event.payload
    lines.extend(("[USER]", str(payload.get("query", "-")), ""))
    scope = payload.get("scope")
    if isinstance(scope, Mapping):
        _section(
            lines,
            "[CONTEXT]",
            (
                f"conversation_id: {_display_identity(payload.get('conversation_id'))}",
                f"allowed_session_ids: {_pretty_value(scope.get('allowed_session_ids'))}",
                f"start_timestamp: {_pretty_value(scope.get('start_timestamp'))}",
                f"end_timestamp: {_pretty_value(scope.get('end_timestamp'))}",
                f"max_results: {_pretty_value(scope.get('max_results'))}",
            ),
        )


def _render_context(lines: list[str], event: NormalizedQueryEvent) -> None:
    """渲染 context preparation 的数量事实，不重复恢复会话正文。"""

    payload = event.payload
    _section(
        lines,
        "[CONTEXT PREPARATION]",
        (
            f"conversation_id: {_display_identity(payload.get('conversation_id'))}",
            f"prior_context_count: {_pretty_value(payload.get('prior_context_count'))}",
        ),
    )


def _render_router(lines: list[str], event: NormalizedQueryEvent) -> None:
    """渲染 Router 显式 reason；它是 execution fact，不是 hidden reasoning。"""

    payload = event.payload
    _section(
        lines,
        "[ROUTER]",
        (
            f"route: {_pretty_value(payload.get('route'))}",
            f"confidence: {_pretty_value(payload.get('confidence'))}",
            f"source: {_pretty_value(payload.get('source'))}",
            f"reason: {_pretty_value(payload.get('reason'))}",
            f"degraded: {_pretty_value(payload.get('degraded'))}",
            f"degradation_code: {_pretty_value(payload.get('degradation_code'))}",
        ),
    )


def _render_router_degradation(lines: list[str], event: NormalizedQueryEvent) -> None:
    """把 Router degradation 单独显示，避免 reason 被 failure metadata 淹没。"""

    payload = event.payload
    _section(
        lines,
        "[ROUTER DEGRADATION]",
        (
            f"code: {_pretty_value(payload.get('degradation_code'))}",
            f"handling: {_failure_field(event, 'handling', 'static_route_retained')}",
        ),
    )


def _render_planner(lines: list[str], event: NormalizedQueryEvent) -> None:
    """成功和失败 Planner 都显示明确 handling，便于定位 fallback execution。"""

    payload = event.payload
    if event.operation == "planner.completed":
        lines.append("[PLANNER]")
        lines.append("status: completed")
        lines.extend(_planner_observation_lines(payload))
        lines.append(f"title: {_pretty_value(payload.get('title'))}")
        lines.append(f"intent: {_pretty_value(payload.get('intent'))}")
        lines.append("steps:")
        steps = payload.get("steps")
        if isinstance(steps, (list, tuple)) and steps:
            for index, step in enumerate(steps, 1):
                lines.append(f"  {index}. {_pretty_value(step)}")
        else:
            lines.append("  -")
        criteria = payload.get("success_criteria")
        lines.append("success criteria:")
        if isinstance(criteria, (list, tuple)) and criteria:
            for criterion in criteria:
                lines.append(f"  - {_pretty_value(criterion)}")
        else:
            lines.append(f"  {_pretty_value(payload.get('criterion_count', '-'))}")
        lines.append("")
        return

    failure = event.failure
    _section(
        lines,
        "[PLANNER]",
        (
            "status: failed" if event.operation == "planner.failed" else "status: skipped",
            *_planner_observation_lines(payload),
            f"error_code: {_pretty_value(payload.get('error_code') or _failure_value(failure, 'error_code'))}",
            f"failure category: {_pretty_value(payload.get('failure_category') or _failure_value(failure, 'category'))}",
            f"failure detail: {_pretty_value(payload.get('failure_detail_code'))}",
            f"parse stage: {_pretty_value(payload.get('parse_stage'))}",
            f"diagnostic: {_pretty_value(payload.get('diagnostic'))}",
            f"handling: {_failure_value(failure, 'handling') or '-'}",
            f"fallback: {'executed_without_plan' if 'executed_without_plan' in event.limitations else '-'}",
        ),
    )


def _render_planner_started(lines: list[str], event: NormalizedQueryEvent) -> None:
    """渲染 Planner invocation boundary，让 timeout/request 在没有 response 时仍可见。"""

    payload = event.payload
    request = payload.get("completion_request")
    request_mapping = request if isinstance(request, Mapping) else {}
    _section(
        lines,
        "[PLANNER]",
        (
            "status: started",
            f"route: {_pretty_value(payload.get('route'))}",
            f"provider: {_pretty_value(request_mapping.get('provider'))}",
            f"model: {_pretty_value(request_mapping.get('model'))}",
            f"completion timeout_seconds: {_pretty_value(payload.get('completion_timeout_seconds'))}",
            f"request max_tokens: {_pretty_value(request_mapping.get('max_tokens'))}",
            f"json mode: {_pretty_value(request_mapping.get('json_mode'))}",
        ),
    )


def _planner_observation_lines(payload: Mapping[str, object]) -> tuple[str, ...]:
    """渲染 Planner 的 Provider/预算/响应事实，不重新解析或猜测 response。"""

    request = payload.get("completion_request")
    request_mapping = request if isinstance(request, Mapping) else {}
    provider = payload.get("provider") or request_mapping.get("provider")
    model = payload.get("model") or request_mapping.get("model")
    lines = [
        f"provider: {_pretty_value(provider)}",
        f"model: {_pretty_value(model)}",
        f"planner latency_ms: {_pretty_value(payload.get('planner_latency_ms'))}",
        f"provider latency_ms: {_pretty_value(payload.get('provider_latency_ms'))}",
        f"request max_tokens: {_pretty_value(request_mapping.get('max_tokens'))}",
        f"json mode: {_pretty_value(request_mapping.get('json_mode'))}",
        f"finish_reason: {_pretty_value(payload.get('finish_reason'))}",
        f"usage: {_pretty_value(payload.get('usage'))}",
        f"output_tokens: {_pretty_value(payload.get('output_tokens'))}",
        f"response length: {_pretty_value(payload.get('response_length'))}",
    ]
    response_content = payload.get("response_content")
    if isinstance(response_content, str):
        # 只有 Debug capture 才会带 response_content；这里直接显示同源安全文本。
        lines.extend(("output:", response_content))
    return tuple(lines)


def _render_model_turn_with_context(
    lines: list[str],
    turn_number: int,
    started: NormalizedQueryEvent,
    related: tuple[NormalizedQueryEvent, ...],
    call_names: Mapping[str, str],
    *,
    context_mode: TranscriptContextMode,
    previous_context: tuple[Mapping[str, object], ...] | None,
) -> tuple[Mapping[str, object], ...]:
    """按 delta/full 模式渲染 input，并返回本轮完整 context 供下一轮比较。"""

    lines.append(f"[MODEL TURN {turn_number}]")
    lines.append("")
    context_items = tuple(_items(started.payload.get("model_visible_context")))
    if context_mode == "full":
        lines.extend(("Full model-visible context", "----------------------------"))
        items_to_render = context_items
        context_note: str | None = None
    elif previous_context is None:
        lines.extend(("Input", "-----"))
        items_to_render = context_items
        context_note = None
    else:
        lines.extend(("New input since previous turn", "----------------------------"))
        items_to_render, context_note = _context_delta(context_items, previous_context)

    if context_note is not None:
        lines.append(f"[context note] {context_note}")
    if not items_to_render:
        if context_items:
            lines.append("[no new model-visible input]")
        else:
            lines.append("[model-visible input not captured]")
    else:
        for item in items_to_render:
            _render_model_item(lines, item, call_names)
    if context_mode == "delta" and previous_context is not None and context_items:
        lines.append("[full model-visible context available with context=full]")

    lines.extend(("", "Output / Actions", "----------------"))
    output_events = [event for event in related if event.operation == "model.output"]
    output_items: list[Mapping[str, object]] = []
    for event in output_events:
        output_items.extend(_items(event.payload.get("observable_output")))
    if output_items:
        for item in output_items:
            _render_model_item(lines, item, call_names)
    else:
        lines.append("[no assistant-visible output captured]")

    limitations = _event_limitations((started, *related))
    if limitations:
        lines.append(f"capture limitations: {', '.join(limitations)}")

    usage_events = [event for event in related if event.operation == "model.usage"]
    if usage_events:
        usage = usage_events[-1].payload.get("usage")
        lines.append(f"usage: {_pretty_value(usage)}")
    lines.append(f"tool_round: {_pretty_value(started.payload.get('tool_round'))}")
    lines.append("")
    return context_items


def _context_delta(
    current: tuple[Mapping[str, object], ...],
    previous: tuple[Mapping[str, object], ...],
) -> tuple[tuple[Mapping[str, object], ...], str | None]:
    """只去掉确认属于上一轮前缀的 item，避免把变化误当成重复历史。"""

    common = 0
    while common < len(current) and common < len(previous):
        current_key = _model_item_key(current[common])
        previous_key = _model_item_key(previous[common])
        if current_key is None or previous_key is None or current_key != previous_key:
            return current, "previous context is not a stable prefix; showing full captured input"
        common += 1
    return current[common:], None


def _model_item_key(item: Mapping[str, object]) -> str | None:
    """用 plain item 的稳定 JSON 比较 context，不把 identity 重新写入日志。"""

    try:
        return json.dumps(dict(item), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _model_action_count(value: object) -> int:
    """统计已经由 adapter 投影的 observable tool action 数量。"""

    return sum(
        1
        for item in _items(value)
        if item.get("type") in {"function_call", "custom_tool_call"}
    )


def _trace_duration_ms(trace: StoredTrace) -> str:
    """从 Trace metadata 的时间边界计算摘要时长，未知时保持显式短标记。"""

    if trace.terminal_at is None:
        return "-"
    try:
        started = datetime.fromisoformat(trace.started_at)
        terminal = datetime.fromisoformat(trace.terminal_at)
    except ValueError:
        return "-"
    return f"{(terminal - started).total_seconds() * 1000:.3f}"


def _render_model_item(lines: list[str], item: Mapping[str, object], call_names: Mapping[str, str]) -> None:
    """将 plain model item 渲染为 message、Tool Call 或 Tool Result。"""

    item_type = item.get("type")
    if item_type in {"function_call", "custom_tool_call"}:
        name = item.get("name") or "unknown_tool"
        lines.append(f"[TOOL CALL] {name}")
        call_id = item.get("call_id")
        if isinstance(call_id, str):
            lines.append(f"tool_call_id: {_display_identity(call_id)}")
        lines.append("Arguments:")
        lines.append(_pretty_value(item.get("arguments")))
        lines.append("")
        return
    if item_type in {"function_call_output", "custom_tool_call_output"}:
        call_id = item.get("call_id")
        tool_name = call_names.get(call_id, "unknown_tool") if isinstance(call_id, str) else "unknown_tool"
        lines.append(f"[TOOL RESULT: {tool_name}]")
        if isinstance(call_id, str):
            lines.append(f"tool_call_id: {_display_identity(call_id)}")
        lines.extend(_tool_result_lines(_tool_result_projection(item)))
        lines.append("")
        return
    if item_type == "unsupported_visible_item":
        lines.append(f"[MODEL ITEM OMITTED] type: {_pretty_value(item.get('item_type'))}")
        lines.append("capture: visible item has no safe Trivae projection")
        lines.append("")
        return

    role = item.get("role")
    if isinstance(role, str):
        lines.append(f"[{role.upper()}]")
        lines.extend(_content_lines(item.get("content")))
        lines.append("")
        return
    lines.append(f"[MODEL ITEM] {_pretty_value(item_type)}")
    lines.append("")


def _tool_result_lines(output: object) -> list[str]:
    """正文优先展示模型实际 Tool Result，随后给出检索完整性 metadata。"""

    parsed = _parse_structured_output(output)
    if not isinstance(parsed, Mapping):
        return _content_lines(output)

    data = parsed.get("data")
    body_lines: list[str] = []
    if isinstance(data, Mapping):
        entries = _message_entries(data)
        for entry in entries:
            body_lines.extend(_message_entry_lines(entry))
        if not entries:
            body_lines.append(_pretty_value(data))
    else:
        # data 为空时只显示 status/error，不把 provenance 中的内部 locator 塞进主 Transcript。
        visible_result = {
            key: parsed[key]
            for key in ("status", "error")
            if key in parsed
        }
        body_lines.append(_pretty_value(visible_result or {"output": output}))

    metadata = _tool_result_metadata(parsed, data)
    if metadata:
        body_lines.append("")
        body_lines.append("Tool Result Metadata:")
        body_lines.extend(f"{key}: {_pretty_value(value)}" for key, value in metadata.items())
    return body_lines


def _tool_result_projection(item: Mapping[str, object]) -> object:
    """优先读取 adapter 从同一模型输入字符串派生的结构化 Tool Result。"""

    projection = item.get("output_projection")
    if isinstance(projection, (Mapping, list, tuple)):
        return projection
    return item.get("output")


def _message_entries(data: Mapping[str, object]) -> list[Mapping[str, object]]:
    """从 ToolEnvelope 的既有 model-visible data 中提取消息正文，不访问 Conversation Store。"""

    entries: list[Mapping[str, object]] = []
    for key in ("messages", "hits", "expanded_messages"):
        raw_entries = data.get(key)
        if not isinstance(raw_entries, (list, tuple)):
            continue
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, Mapping):
                continue
            message = raw_entry.get("message", raw_entry)
            if isinstance(message, Mapping):
                entries.append(message)
    return entries


def _message_entry_lines(message: Mapping[str, object]) -> list[str]:
    """渲染检索消息的时间、作者和正文，保留模型实际看到的 bounded content。"""

    timestamp = message.get("timestamp")
    timestamp_text = _timestamp_text(timestamp)
    author = message.get("sender_name") or message.get("sender_user_id") or "unknown"
    session = message.get("session_display")
    prefix = f"{timestamp_text} {author}"
    if isinstance(session, str) and session:
        prefix += f" [{session}]"
    content = message.get("normalized_content") or message.get("content") or ""
    return [prefix, *(_content_lines(content)), ""]


def _tool_result_metadata(parsed: Mapping[str, object], data: object) -> dict[str, object]:
    """只展示人工定位需要的 Tool/Retrieval 完整性字段。"""

    metadata: dict[str, object] = {}
    status = parsed.get("status")
    if status is not None:
        metadata["status"] = status
    if isinstance(data, Mapping):
        for key in ("returned_messages", "returned_count", "total_hits", "partial", "truncated", "coverage"):
            if key in data:
                metadata[key] = data[key]
    meta = parsed.get("meta")
    if isinstance(meta, Mapping):
        for key in ("returned_messages", "total_hits", "truncated"):
            if key not in metadata and key in meta:
                metadata[key] = meta[key]
    return metadata


def _render_tool_execution(lines: list[str], event: NormalizedQueryEvent) -> None:
    """保留没有出现在下一轮 input 中的工具终态，避免失败调用失去可见状态。"""

    payload = event.payload
    _section(
        lines,
        "[TOOL EXECUTION]",
        (
            f"tool: {_pretty_value(payload.get('tool_name'))}",
            f"status: {_pretty_value(payload.get('tool_status') or payload.get('status') or event.outcome)}",
            f"error_code: {_pretty_value(payload.get('tool_error_code') or payload.get('error_code'))}",
        ),
    )


def _render_retrieval(lines: list[str], event: NormalizedQueryEvent) -> None:
    """只投影 Retrieval 主诊断，候选 IDs/scores 留在 Raw Events。"""

    payload = event.payload
    query = payload.get("query")
    query_text = query.get("keyword") if isinstance(query, Mapping) else query
    returned = payload.get("returned_messages", payload.get("returned_count"))
    total = payload.get("total_hits")
    ratio = f"{_pretty_value(returned)} / {_pretty_value(total)}" if total is not None else _pretty_value(returned)
    _section(
        lines,
        "[RETRIEVAL]",
        (
            f"status: {event.phase}",
            f"strategy: {_pretty_value(payload.get('strategy'))}",
            f"query: {_pretty_value(query_text)}",
            f"returned / total: {ratio}",
            f"partial: {_pretty_value(payload.get('partial'))}",
            f"truncated: {_pretty_value(payload.get('truncated'))}",
            f"coverage: {_pretty_value(payload.get('coverage'))}",
        ),
    )


def _render_evidence(lines: list[str], event: NormalizedQueryEvent) -> None:
    """显示 Evidence 选择数量，不展开内部 source identity。"""

    payload = event.payload
    _section(
        lines,
        "[EVIDENCE]",
        (
            f"selected sources: {_pretty_value(payload.get('selected_source_count'))}",
            f"evidence items: {_pretty_value(payload.get('evidence_count'))}",
            f"limitations: {_pretty_value(payload.get('limitations'))}",
        ),
    )


def _render_citation(lines: list[str], event: NormalizedQueryEvent) -> None:
    """显示 Citation binding 和 unresolved 数量。"""

    payload = event.payload
    _section(
        lines,
        "[CITATION]",
        (
            f"citation bindings: {_pretty_value(payload.get('binding_count'))}",
            f"unresolved: {_pretty_value(payload.get('unresolved_count'))}",
        ),
    )


def _render_final_answer(lines: list[str], answer: str, limitations: tuple[str, ...]) -> None:
    """渲染完整 answer snapshot，并明确标注 CapturePolicy 截断。"""

    lines.append("[FINAL ANSWER]")
    lines.extend(answer.splitlines() or [""])
    if limitations:
        lines.append(f"capture limitations: {', '.join(limitations)}")
    lines.append("")


def _event_limitations(events: tuple[NormalizedQueryEvent, ...]) -> tuple[str, ...]:
    """聚合当前 Transcript block 的 capture limitation，避免正文看起来无条件完整。"""

    limitations: list[str] = []
    for event in events:
        for limitation in event.limitations:
            if limitation not in limitations:
                limitations.append(limitation)
    return tuple(limitations)


def _answer_from_runtime_payload(payload: Mapping[str, object]) -> str | None:
    """从旧 Trace 的 runtime final output 提取可读答案；新 Trace 使用 answer snapshot。"""

    raw_answer = payload.get("final_answer")
    if not isinstance(raw_answer, str):
        return None
    parsed = _parse_structured_output(raw_answer)
    if isinstance(parsed, Mapping):
        content_blocks = parsed.get("content_blocks")
        if isinstance(content_blocks, (list, tuple)):
            texts: list[str] = []
            for block in content_blocks:
                if isinstance(block, Mapping):
                    text = block.get("text")
                    if isinstance(text, str):
                        texts.append(text)
            if texts:
                return "\n\n".join(texts)
    return raw_answer


def _failure_value(failure: object, key: str) -> object | None:
    """读取 FailureInfo.to_dict 的稳定字段，不泄漏 exception object。"""

    if failure is None:
        return None
    to_dict = getattr(failure, "to_dict", None)
    if callable(to_dict):
        value = to_dict().get(key)
        return value
    return None


def _failure_field(event: NormalizedQueryEvent, key: str, default: object) -> object:
    """从 failure 或 limitation 读取一个人工诊断字段。"""

    value = _failure_value(event.failure, key)
    return default if value is None else value


def _items(value: object) -> list[Mapping[str, object]]:
    """只消费 Collector 已经保存的 mapping item。"""

    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _content_lines(value: object) -> list[str]:
    """把 plain string 或 content block 投影为多行正文。"""

    if isinstance(value, str):
        return value.splitlines() or [""]
    if isinstance(value, (list, tuple)):
        lines: list[str] = []
        for block in value:
            if isinstance(block, str):
                lines.extend(block.splitlines())
            elif isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str):
                    lines.extend(text.splitlines())
                elif isinstance(block.get("type"), str):
                    lines.append(f"[{block['type']}]")
        return lines or [""]
    return [_pretty_value(value)]


def _parse_structured_output(value: object) -> object:
    """解析 SDK 可能产生的 JSON 或 Python dict 文本；解析失败时保留原正文。"""

    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        pass
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def _timestamp_text(value: object) -> str:
    """将 canonical 毫秒时间转换为 UTC 可读时间，非法值保留原值。"""

    if isinstance(value, int) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            pass
    return _pretty_value(value)


def _display_identity(value: object) -> str:
    """主 Transcript 只显示短 identity，完整 identity 仍保留在 Raw Events。"""

    if not isinstance(value, str) or not value:
        return "-"
    return value.rsplit("/", 1)[-1][:24]


def _pretty_value(value: object) -> str:
    """稳定渲染普通值，避免把大段 JSON metadata 混入正文。"""

    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    except (TypeError, ValueError):
        return str(value)


def _section(lines: list[str], title: str, body: tuple[str, ...]) -> None:
    """追加一个带空行的人工阅读区块。"""

    lines.append(title)
    lines.extend(body)
    lines.append("")
