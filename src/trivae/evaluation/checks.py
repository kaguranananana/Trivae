"""Evaluation 的确定性检查与 operational projection。"""

from __future__ import annotations

import re
from typing import Mapping

from trivae.observability.contracts import TraceProjection
from trivae.query.contracts import QueryRequest, QueryResult
from trivae.query.evidence import AnswerArtifact, MessageSource, StructuredSource

from .contracts import (
    MAX_EVALUATION_ITEMS,
    MAX_EVALUATION_TEXT_CHARS,
    DatasetSnapshot,
    DeterministicCheck,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationResult,
    scope_identity,
)
from .quality import QUALITY_AXES
from .variant import ControlledVariant

_INDEX_SUBSCRIPT = re.compile(r"\[\d+\]")


def _normalize_limitation_name(name: str) -> str:
    """把 projection-path limitation 的数组下标归一化为固定标记。

    Trace 的 projection-path limitation（如 ``payload...hits[37]``）按条目生成；
    归一化后同一路径只贡献一条 limitation，避免大结果集时无界膨胀。
    """

    return _INDEX_SUBSCRIPT.sub("[]", name)[:MAX_EVALUATION_TEXT_CHARS]

# retrieval tool → benchmark 消费的 strategy 标签；非 retrieval tool 不进入 retrieval_calls。
_RETRIEVAL_STRATEGY_BY_TOOL = {
    "lexical_search": "lexical",
    "search_messages": "lexical",
    "semantic_search": "semantic",
    "get_recent_messages": "recent",
    "get_message_context": "context",
}

# 全 Run 累计落盘边界：per-call 与 per-run 双重 cap，超界以 count/omitted 表达。
_MAX_RECORDED_DIRECT_HITS = 50
_MAX_RECORDED_EXPANDED_IDS = 50
_MAX_RECORDED_RETRIEVAL_CALLS = 8
_MAX_RECORDED_EVIDENCE_SOURCES = 50
_MAX_RECORDED_EVIDENCE_MESSAGE_IDS = 20


# no_result final 的确定性 artifact 形态（compile_model_no_result_answer contract）：
# 单一 "answer" block、无 evidence、无 citation；claims 路径的 block id 固定为 "claim-N"。
_NO_RESULT_BLOCK_ID = "answer"

# Tier 2 judge 消费的 block/citation 投影边界；数组仍受 MAX_EVALUATION_ITEMS 约束。
_MAX_RECORDED_BLOCKS = 20
_MAX_BLOCK_TEXT_CHARS = 2000


def _content_blocks_projection(artifact: AnswerArtifact | None) -> list[dict[str, object]]:
    """按 block 落盘 bounded 正文，供 atomic claim 切分与 citation 正确性判定。"""

    if artifact is None:
        return []
    return [
        {"block_id": block.block_id, "text": block.text[:_MAX_BLOCK_TEXT_CHARS]}
        for block in artifact.content_blocks[:_MAX_RECORDED_BLOCKS]
    ]


def _citation_bindings_projection(artifact: AnswerArtifact | None) -> list[dict[str, object]]:
    """落盘 block→evidence 绑定；citation 存在 ≠ citation 正确，后者由 Tier 2 判定。"""

    if artifact is None:
        return []
    return [
        {"content_block_id": binding.content_block_id, "evidence_ids": list(binding.evidence_ids)}
        for binding in artifact.citation_bindings[:_MAX_RECORDED_BLOCKS]
    ]


def _answer_form(artifact: AnswerArtifact | None) -> str | None:
    """返回 bounded answer 形态标签；no_result 形态是 zero-result 指标的判定输入。"""

    if artifact is None:
        return None
    if (
        len(artifact.content_blocks) == 1
        and artifact.content_blocks[0].block_id == _NO_RESULT_BLOCK_ID
        and not artifact.evidence_items
        and not artifact.citation_bindings
    ):
        return "no_result_signature"
    return "claims"


def _answer_text_projection(result: QueryResult | None) -> str | None:
    """保留 bounded answer 正文，供 Expected Fact Answer Coverage 确定性匹配。"""

    if result is None or result.answer_artifact is None:
        return None
    return result.answer_artifact.answer_text[: MAX_EVALUATION_TEXT_CHARS]


def _retrieval_calls_projection(result: QueryResult | None) -> dict[str, object]:
    """分层落盘每次 retrieval call 的 direct hits 与 context expansion IDs。

    direct_hits（is_hit=true，保持工具返回 rank 顺序）与 expanded_ids（is_hit=false）
    分开记录，保证 Retrieval Recall 只看 direct 层、Evidence/Context Recovery 看
    evidence 层时互不混合。coverage/partial/truncated 直接携带 ToolResultRecord
    limitations 里的 Host 派生事实，不在此处重新计算 production coverage。
    """

    empty: dict[str, object] = {"calls": [], "total": 0, "omitted": 0}
    if result is None:
        return empty
    calls: list[dict[str, object]] = []
    omitted_calls = 0
    for record in result.runtime_result.tool_results:
        strategy = _RETRIEVAL_STRATEGY_BY_TOOL.get(record.tool_name)
        if strategy is None:
            continue
        if len(calls) >= _MAX_RECORDED_RETRIEVAL_CALLS:
            omitted_calls += 1
            continue
        direct_hits: list[dict[str, object]] = []
        expanded_ids: list[str] = []
        direct_count = 0
        expanded_count = 0
        for item in record.message_items:
            if item.is_hit:
                direct_count += 1
                if direct_count <= _MAX_RECORDED_DIRECT_HITS:
                    direct_hits.append(
                        {"rank": direct_count, "internal_message_id": item.message.internal_message_id}
                    )
            else:
                expanded_count += 1
                if len(expanded_ids) < _MAX_RECORDED_EXPANDED_IDS:
                    expanded_ids.append(item.message.internal_message_id)
        coverage_status = next(
            (
                limitation.removeprefix("coverage:")
                for limitation in record.limitations
                if limitation.startswith("coverage:")
            ),
            None,
        )
        calls.append(
            {
                "tool_call_id": record.tool_call_id,
                "tool_name": record.tool_name,
                "strategy": strategy,
                "status": record.status,
                "coverage_status": coverage_status,
                "partial": any(limitation in ("retrieval_partial", "tool_result_partial") for limitation in record.limitations),
                "truncated": "retrieval_truncated" in record.limitations,
                "direct_hit_count": direct_count,
                "direct_hits": direct_hits,
                "omitted_direct_ids": max(0, direct_count - _MAX_RECORDED_DIRECT_HITS),
                "expanded_count": expanded_count,
                "expanded_ids": expanded_ids,
                "omitted_expanded_ids": max(0, expanded_count - _MAX_RECORDED_EXPANDED_IDS),
            }
        )
    return {"calls": calls, "total": len(calls) + omitted_calls, "omitted": omitted_calls}


def _evidence_sources_projection(result: QueryResult | None) -> dict[str, object]:
    """按 evidence 分组落盘可追溯的 source message IDs / structured locator kinds。"""

    empty: dict[str, object] = {"sources": [], "total": 0, "omitted": 0}
    if result is None or not isinstance(result.answer_artifact, AnswerArtifact):
        return empty
    artifact = result.answer_artifact
    sources: list[dict[str, object]] = []
    omitted_sources = 0
    for evidence in artifact.evidence_items:
        if len(sources) >= _MAX_RECORDED_EVIDENCE_SOURCES:
            omitted_sources += 1
            continue
        message_ids: list[str] = []
        locator_kinds: list[str] = []
        for evidence_source in evidence.sources:
            reference = evidence_source.reference
            if isinstance(reference, MessageSource):
                if len(message_ids) < _MAX_RECORDED_EVIDENCE_MESSAGE_IDS:
                    message_ids.append(reference.internal_message_id)
            elif isinstance(reference, StructuredSource) and len(locator_kinds) < _MAX_RECORDED_EVIDENCE_MESSAGE_IDS:
                locator_kinds.append(reference.locator_kind)
        sources.append(
            {
                "evidence_id": evidence.evidence_id,
                "sufficiency": evidence.sufficiency,
                "message_ids": message_ids,
                "structured_locator_kinds": locator_kinds,
            }
        )
    return {"sources": sources, "total": len(sources) + omitted_sources, "omitted": omitted_sources}


def query_result_snapshot(result: QueryResult | None) -> dict[str, object] | None:
    """只保存 QueryResult 的 bounded identity/状态，不把完整 Answer/Trace 复制进 Evaluation DB。"""

    if result is None:
        return None
    plan = result.plan
    runtime_error = result.runtime_result.error
    tool_behavior = agent_tool_behavior_projection(result)
    return {
        "termination": result.termination,
        "execution_status": result.execution_status,
        "is_successful": result.is_successful,
        # Runtime 尚未完成时没有进入 Finalizer；QueryResult 的 dataclass 默认值不能
        # 被当作真实 finalization 状态写入 Evaluation projection。
        "finalization_status": (
            result.finalization_status
            if result.runtime_result.termination == "completed"
            else "skipped"
        ),
        "route": result.route_decision.route,
        "route_source": result.route_decision.source,
        "route_confidence": result.route_decision.confidence,
        "route_probabilities": (
            None
            if result.route_decision.probabilities is None
            else dict(result.route_decision.probabilities)
        ),
        "route_provider": result.route_decision.provider,
        "route_model": result.route_decision.model,
        "route_provider_error_type": result.route_decision.provider_error_type,
        "router_primary_latency_ms": result.route_decision.primary_latency_ms,
        "route_degraded": result.route_decision.degraded,
        "route_degradation_code": result.route_decision.degradation_code,
        "router_shadow": (
            None
            if result.route_decision.shadow is None
            else {
                "provider": result.route_decision.shadow.provider,
                "model": result.route_decision.shadow.model,
                "route": result.route_decision.shadow.route,
                "confidence": result.route_decision.shadow.confidence,
                "probabilities": (
                    None
                    if result.route_decision.shadow.probabilities is None
                    else dict(result.route_decision.shadow.probabilities)
                ),
                "usage": (
                    None
                    if result.route_decision.shadow.usage is None
                    else dict(result.route_decision.shadow.usage)
                ),
                "latency_ms": result.route_decision.shadow.latency_ms,
                "degraded": result.route_decision.shadow.degraded,
                "degradation_code": result.route_decision.shadow.degradation_code,
                "provider_error_type": result.route_decision.shadow.provider_error_type,
            }
        ),
        "plan": None
        if plan is None
        else {
            "version": plan.version,
            "title": plan.title,
            "intent": plan.intent,
            "step_count": len(plan.steps),
            "criterion_count": len(plan.success_criteria),
        },
        "runtime": {
            "provider": result.runtime_result.provider,
            "model": result.runtime_result.model,
            "termination": result.runtime_result.termination,
            "tool_count": result.runtime_result.tool_count,
            "tool_rounds": result.runtime_result.tool_rounds,
            "tool_behavior": tool_behavior,
            "usage": None if result.runtime_result.usage is None else dict(result.runtime_result.usage),
            "run_id": result.runtime_result.run_id,
            "error": None
            if runtime_error is None
            else {
                "code": runtime_error.code,
                "stage": runtime_error.stage,
                "category": runtime_error.category,
                "diagnostic_type": runtime_error.diagnostic_type,
                "exception_type": runtime_error.exception_type,
                # Runtime boundary 已完成脱敏；保存可定位原因，不仅保留异常类型。
                "message": runtime_error.message,
            },
        },
        "finalization_error": None
        if result.finalization_error is None
        else {
            "code": result.finalization_error.code,
            "path": result.finalization_error.path,
        },
        "answer_form": _answer_form(
            result.answer_artifact if isinstance(result.answer_artifact, AnswerArtifact) else None
        ),
        "answer_text": _answer_text_projection(result),
        "retrieval_coverage": None
        if not isinstance(result.answer_artifact, AnswerArtifact)
        else result.answer_artifact.retrieval_coverage,
        "finalization_diagnostics": (
            None
            if result.finalization_diagnostics is None
            else result.finalization_diagnostics.to_dict()
        ),
        "answer_artifact_present": isinstance(result.answer_artifact, AnswerArtifact),
        "conversation_id": result.conversation_id,
        "trace_id": result.trace_id,
        "diagnostic_codes": [diagnostic.code for diagnostic in result.diagnostics],
        "retrieval_calls": _retrieval_calls_projection(result),
        "evidence_sources": _evidence_sources_projection(result),
        "content_blocks": _content_blocks_projection(
            result.answer_artifact if isinstance(result.answer_artifact, AnswerArtifact) else None
        ),
        "citation_bindings": _citation_bindings_projection(
            result.answer_artifact if isinstance(result.answer_artifact, AnswerArtifact) else None
        ),
    }


def agent_tool_behavior_projection(result: QueryResult | None) -> dict[str, object]:
    """保存 Agent Tool Selection 的公开行为事实，不替模型行为下质量结论。"""

    if result is None:
        return {
            "first_selected_tool": None,
            "tool_sequence": [],
            "retrieval_tool_sequence": [],
            "context_tool_sequence": [],
            "member_tool_sequence": [],
            "schema_tool_sequence": [],
            "sql_tool_sequence": [],
            "tool_call_count": 0,
            "tool_rounds": 0,
            "tool_errors": [],
        }
    calls = result.runtime_result.tool_calls
    retrieval_names = {"lexical_search", "semantic_search", "search_messages"}
    context_names = {"get_message_context"}
    member_names = {"find_members"}
    schema_names = {"get_schema"}
    sql_names = {"execute_sql"}
    return {
        "first_selected_tool": None if not calls else calls[0].name,
        "tool_sequence": [call.name for call in calls],
        "retrieval_tool_sequence": [call.name for call in calls if call.name in retrieval_names],
        # Stage B 保留 context/member 的公开 action sequence，是否合理仍交给 Case Review。
        "context_tool_sequence": [call.name for call in calls if call.name in context_names],
        "member_tool_sequence": [call.name for call in calls if call.name in member_names],
        # Stage C 将 schema inspection 与 SQL execution 分轴记录，便于判断 schema→SQL 链路。
        "schema_tool_sequence": [call.name for call in calls if call.name in schema_names],
        "sql_tool_sequence": [call.name for call in calls if call.name in sql_names],
        "tool_call_count": len(calls),
        "tool_rounds": result.runtime_result.tool_rounds,
        "tool_errors": [
            {
                "name": call.name,
                "status": call.status,
                "error_code": call.error_code,
            }
            for call in calls
            if call.status in {"error", "failed"} or call.error_code is not None
        ],
    }


def operational_measurements(
    result: QueryResult | None,
    trace: TraceProjection | None,
) -> dict[str, object]:
    """从 Runtime/Trace 派生运行事实，保持与回答质量分轴。"""

    tool_result_facts = () if trace is None else _tool_result_facts(trace)
    tool_result_budget = _tool_result_budget_measurements(result, trace)
    measurements: dict[str, object] = {
        "termination": None if result is None else result.termination,
        "tool_calls": None if result is None else result.runtime_result.tool_count,
        "tool_rounds": None if result is None else result.runtime_result.tool_rounds,
        "provider": None if result is None else result.runtime_result.provider,
        "model": None if result is None else result.runtime_result.model,
        "usage": None
        if result is None or result.runtime_result.usage is None
        else dict(result.runtime_result.usage),
        "trace_completeness": None if trace is None else trace.completeness,
        "retrieval_count": None if trace is None else trace.metrics.retrieval_count,
        "latency_ms": None if trace is None else trace.metrics.total_duration_ms,
        "trace_limitations": (),
        "coverage_statuses": (),
        "scope_enforcement": (),
        "structured_sql": None if trace is None else _structured_sql_measurements(trace),
        # 综合诊断需要按公开 Tool 保留 bounded 结果事实，而不是把原始 Trace 复制进 Evaluation。
        "tool_result_facts": tool_result_facts,
        "tool_result_budget": tool_result_budget,
        # 这是公开 action sequence 的 observation；preferred tool 仍由诊断 Case 和人工/模型 Review 分开判断。
        "agent_tool_behavior": agent_tool_behavior_projection(result),
        "planner": _planner_measurements(trace),
    }
    if trace is not None:
        limitations: list[str] = []
        coverage_statuses: list[str] = []
        for item in trace.timeline:
            # 配置来自本轮 Runtime 的安全 Trace projection，不能用 frozen Variant 冒充实际设置。
            if item.operation == "runtime.configuration" and item.phase == "completed":
                measurements["model_configuration"] = dict(item.payload)
            # Router/Planner terminal Provider 错误会在 Runtime 前停止，身份只能来自本轮安全 Trace。
            if result is None and item.operation == "query.failed" and item.phase == "failed":
                payload = item.payload
                # 未返回 QueryResult 时不把 frozen Variant 声明代替实际 Provider 观测。
                for name in ("provider", "model", "error_code", "error_message"):
                    if isinstance(payload.get(name), str):
                        measurements[name] = payload[name]
                # 请求参数与传输错误已由边界脱敏；没有观测时保持缺失，不构造成功 usage。
                for name in ("completion_request", "provider_observation"):
                    observation = payload.get(name)
                    if isinstance(observation, Mapping):
                        measurements[name] = dict(observation)
            limitations.extend(item.limitations)
            coverage = item.payload.get("coverage")
            if isinstance(coverage, Mapping):
                status = coverage.get("status")
                if isinstance(status, str):
                    coverage_statuses.append(status)
            if item.payload.get("truncated") is True:
                limitations.append("truncated")
            if item.payload.get("partial") is True:
                limitations.append("partial")
        # Trace 的 projection-path limitations（如 payload...data.hits[37]）按条目生成，
        # 大命中数时会无界膨胀；归一化下标后去重，并显式记录被截断的数量。
        normalized = {_normalize_limitation_name(name) for name in limitations}
        ordered = tuple(sorted(normalized))
        measurements["trace_limitations"] = ordered[:MAX_EVALUATION_ITEMS]
        measurements["trace_limitations_omitted"] = max(0, len(ordered) - MAX_EVALUATION_ITEMS)
        measurements["coverage_statuses"] = tuple(sorted(set(coverage_statuses)))
        # scope_enforcement 只汇总 Tool 已公开的 enforcement 摘要，不从 SQL 或数据库重新推断权限。
        measurements["scope_enforcement"] = tuple(
            sorted(
                {
                    value
                    for fact in tool_result_facts
                    if isinstance(fact, Mapping)
                    for value in (fact.get("scope_enforcement"),)
                    if isinstance(value, str)
                }
            )
        )
    measurements.update(_finalization_measurements(result, trace))
    return measurements


def _planner_measurements(trace: TraceProjection | None) -> dict[str, object]:
    """从 Planner Trace 提取有界执行事实，不推断 plan 是否改善了答案。"""

    if trace is None:
        return {"called": None, "status": "trace_unavailable"}
    # started 是实际调用边界；没有该事件的 standard 路不应算作 Planner failure。
    started = next((item for item in trace.timeline if item.operation == "planner.started"), None)
    if started is None:
        return {"called": False, "status": "not_called"}
    # terminal event 按真实阶段记录成功或失败；异常同样由 failed event 显式暴露。
    terminal = next(
        (item for item in trace.timeline if item.operation in {"planner.completed", "planner.failed"}),
        None,
    )
    if terminal is None:
        return {"called": True, "status": "missing_terminal"}
    payload = terminal.payload
    steps = payload.get("steps")
    suggested_tools: list[str] = []
    if isinstance(steps, (tuple, list)):
        for step in steps[:MAX_EVALUATION_ITEMS]:
            if isinstance(step, Mapping) and isinstance(step.get("suggested_tools"), (tuple, list)):
                for tool in step["suggested_tools"]:
                    if isinstance(tool, str) and tool not in suggested_tools:
                        suggested_tools.append(tool)
    # usage 只复制 Provider 已返回的数字；没有 cost 时不从定价反推。
    usage = payload.get("usage")
    return {
        "called": True,
        "status": "completed" if terminal.operation == "planner.completed" else "failed",
        "latency_ms": terminal.duration_ms,
        "provider": payload.get("provider"),
        "model": payload.get("model"),
        "usage": dict(usage) if isinstance(usage, Mapping) else None,
        "step_count": payload.get("step_count") if terminal.operation == "planner.completed" else None,
        "suggested_tools": suggested_tools[:MAX_EVALUATION_ITEMS],
        "failure_category": payload.get("failure_category"),
        "failure_detail_code": payload.get("failure_detail_code"),
    }


_TOOL_RESULT_OPERATION_CATEGORIES = (
    ("retrieval.search.", "retrieval"),
    ("context.expansion.", "context"),
    ("member.lookup.", "member"),
    ("schema.inspect.", "schema"),
    ("sql.execute.", "sql"),
)


def _tool_result_facts(trace: TraceProjection) -> tuple[dict[str, object], ...]:
    """从公开 Tool/Capability terminal event 派生 bounded 结果摘要。"""

    # 先建立 operation_id 到 Tool 名称的映射，避免把内部 capability operation 当成一次新 Tool。
    tool_names: dict[str, str] = {}
    for item in trace.timeline:
        if item.operation not in {"tool.call.started", "tool.call.completed", "tool.call.failed"}:
            continue
        tool_name = item.payload.get("tool_name")
        if isinstance(tool_name, str) and tool_name:
            tool_names[item.operation_id] = tool_name

    facts: list[dict[str, object]] = []
    for item in trace.timeline:
        # started 事件只代表开始，不足以说明结果，Evaluation 只记录 terminal observation。
        if item.phase not in {"completed", "failed", "skipped"}:
            continue
        category = next(
            (
                category_name
                for prefix, category_name in _TOOL_RESULT_OPERATION_CATEGORIES
                if item.operation.startswith(prefix)
            ),
            None,
        )
        if category is None:
            continue
        # Retrieval 的内部 payload 没有重复写 Tool 名称，沿 parent operation 回到公开 Tool event。
        tool_name_value = item.payload.get("tool_name")
        tool_name = (
            tool_name_value
            if isinstance(tool_name_value, str) and tool_name_value
            else tool_names.get(item.parent_operation_id or "")
        )
        if tool_name is None:
            # 没有公开 Tool parent 的内部 event 不属于 Agent-facing behavior projection。
            continue
        status = item.outcome if item.outcome is not None else ("error" if item.phase != "completed" else "ok")
        fact: dict[str, object] = {
            "tool_name": tool_name,
            "category": category,
            "operation": item.operation,
            "status": status,
        }
        # 只复制稳定的计数、完整性、coverage 和 scope 摘要，不保存消息正文、SQL 或候选正文。
        for field_name in (
            "returned_messages",
            "returned_rows",
            "returned_candidates",
            "returned_tables",
            "candidate_count",
            "partial",
            "truncated",
            "coverage",
            "scope_enforcement",
            "result_bound",
            "sql_rewritten",
            "error_code",
        ):
            value = item.payload.get(field_name)
            if value is not None:
                fact[field_name] = value
        facts.append(fact)
    return tuple(facts)


def _tool_result_budget_measurements(
    result: QueryResult | None,
    trace: TraceProjection | None,
) -> tuple[dict[str, object], ...]:
    """保留每次 Tool projection 的预算事实，不把它转换成质量判断。"""

    measurements: list[dict[str, object]] = []
    if result is not None:
        for call in result.runtime_result.tool_calls:
            if call.tool_result_budget is not None:
                measurements.append(call.tool_result_budget.to_dict())
    if measurements:
        return tuple(measurements)
    if trace is None:
        return ()
    # Trace 是缺少 QueryResult 时的事实来源；只读取 runtime tool completed 的小型快照。
    for item in trace.timeline:
        if item.operation != "runtime.tool.completed":
            continue
        snapshot = item.payload.get("tool_result_budget")
        if isinstance(snapshot, Mapping):
            measurements.append(dict(snapshot))
    return tuple(measurements)


def _finalization_measurements(
    result: QueryResult | None,
    trace: TraceProjection | None,
) -> dict[str, object]:
    """汇总当前 Run 的 Evidence/Citation/Finalizer 状态，不把成功等同于答案质量。"""

    evidence_count: int | None = None
    citation_count: int | None = None
    citation_state = "not_available"
    finalization_state = "not_available"
    finalization_status = "not_available"
    user_answer_preserved: bool | None = None
    dropped_field_count = 0
    dropped_citation_count = 0
    normalization_count = 0
    validated_citation_count = 0
    if trace is not None:
        for item in trace.timeline:
            if item.operation == "evidence.prepare.completed":
                value = item.payload.get("evidence_count")
                if isinstance(value, int) and not isinstance(value, bool):
                    evidence_count = value
                status = item.payload.get("finalization_status")
                if isinstance(status, str):
                    finalization_status = status
            elif item.operation == "citation.validation.completed":
                value = item.payload.get("binding_count")
                if isinstance(value, int) and not isinstance(value, bool):
                    citation_count = value
                unresolved = item.payload.get("unresolved_count")
                status = item.payload.get("finalization_status")
                if isinstance(status, str):
                    finalization_status = status
                validated = item.payload.get("validated_citation_count")
                if isinstance(validated, int) and not isinstance(validated, bool):
                    validated_citation_count = validated
                citation_state = (
                    "degraded"
                    if status == "degraded" or unresolved not in (0, None)
                    else "passed"
                )
            elif item.operation == "citation.validation.failed":
                citation_state = "failed"
            elif item.operation == "answer.finalization.completed":
                raw_finalization_status = item.payload.get("finalization_status", "valid")
                finalization_status = (
                    raw_finalization_status if isinstance(raw_finalization_status, str) else "valid"
                )
                # finalization_state 保留 completed/failed/skipped 的 operational lifecycle；
                # valid/degraded 的产品语义单独由 finalization_status 承载。
                finalization_state = "completed"
                preserved = item.payload.get("user_answer_preserved")
                if isinstance(preserved, bool):
                    user_answer_preserved = preserved
                for name in ("dropped_field_count", "dropped_citation_count", "normalization_count", "validated_citation_count"):
                    value = item.payload.get(name)
                    if isinstance(value, int) and not isinstance(value, bool):
                        if name == "dropped_field_count":
                            dropped_field_count = value
                        elif name == "dropped_citation_count":
                            dropped_citation_count = value
                        elif name == "normalization_count":
                            normalization_count = value
                        else:
                            validated_citation_count = value
            elif item.operation == "answer.finalization.failed":
                finalization_state = "failed"
                finalization_status = "failed"
            elif item.operation == "answer.finalization.skipped":
                finalization_state = "skipped"
                finalization_status = "skipped"

    # Trace 缺失时只用当前 QueryResult 的已验证 artifact 补充计数，不补造 Trace 状态。
    if result is not None and isinstance(result.answer_artifact, AnswerArtifact):
        if evidence_count is None:
            evidence_count = len(result.answer_artifact.evidence_items)
        if citation_count is None:
            citation_count = len(result.answer_artifact.citation_bindings)
    if result is not None:
        if result.finalization_error is not None:
            citation_state = "failed"
            finalization_state = "failed"
            finalization_status = "failed"
        elif result.is_successful:
            finalization_status = result.finalization_status
            finalization_state = "completed"
            citation_state = "degraded" if result.is_degraded else "passed"
            if result.finalization_diagnostics is not None:
                diagnostics = result.finalization_diagnostics
                user_answer_preserved = diagnostics.user_answer_preserved
                dropped_field_count = diagnostics.dropped_field_count
                dropped_citation_count = diagnostics.dropped_citation_count
                normalization_count = diagnostics.normalization_count
                validated_citation_count = diagnostics.validated_citation_count

    return {
        "evidence_count": evidence_count,
        "citation_count": citation_count,
        "citation_state": citation_state,
        "finalization_state": finalization_state,
        "finalization_status": finalization_status,
        "user_answer_preserved": user_answer_preserved,
        "dropped_field_count": dropped_field_count,
        "dropped_citation_count": dropped_citation_count,
        "normalization_count": normalization_count,
        "validated_citation_count": validated_citation_count,
    }


def _structured_sql_measurements(trace: TraceProjection) -> dict[str, object]:
    """从 Trace 的公开 structured operation 摘要记录 SQL/schema 行为事实。"""

    schema_events = tuple(
        item
        for item in trace.timeline
        if item.operation == "schema.inspect.completed" and item.phase == "completed"
    )
    sql_events = tuple(
        item
        for item in trace.timeline
        if item.operation == "sql.execute.completed" and item.phase == "completed"
    )
    sql_failures = tuple(
        item
        for item in trace.timeline
        if item.operation == "sql.execute.failed" and item.phase == "failed"
    )
    return {
        "schema_calls": len(schema_events),
        "schema_returned_tables": tuple(
            value
            for item in schema_events
            for value in (item.payload.get("returned_tables"),)
            if isinstance(value, int) and not isinstance(value, bool)
        ),
        "sql_calls": len(sql_events),
        "sql_returned_rows": tuple(
            value
            for item in sql_events
            for value in (item.payload.get("returned_rows"),)
            if isinstance(value, int) and not isinstance(value, bool)
        ),
        "sql_truncated": tuple(item.payload.get("truncated") is True for item in sql_events),
        "sql_scope_enforcement": tuple(
            value
            for item in sql_events
            for value in (item.payload.get("scope_enforcement"),)
            if isinstance(value, str)
        ),
        "sql_errors": tuple(
            value
            for item in sql_failures
            for value in (item.payload.get("error_code"),)
            if isinstance(value, str)
        ),
    }


def _check(
    name: str,
    status: str,
    severity: str,
    message: str,
    *references: str,
) -> DeterministicCheck:
    """集中构造检查，实际 status 仍由 caller 的事实决定。"""

    return DeterministicCheck(
        name=name,
        status=status,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        message=message,
        evidence_references=tuple(references),
    )


def run_deterministic_checks(
    *,
    case: EvaluationCaseBundle,
    snapshot: DatasetSnapshot | None,
    variant: ControlledVariant,
    request: QueryRequest,
    result: QueryResult | None,
    trace: TraceProjection | None,
) -> tuple[DeterministicCheck, ...]:
    """对单次 Run 做 contract checks；不做自然语言质量判断。"""

    checks: list[DeterministicCheck] = []
    checks.append(_check("case_identity", "passed", "hard", f"resolved Case {case.identity}"))
    if snapshot is None:
        checks.append(_check("snapshot_identity", "failed", "hard", "Dataset Snapshot could not be resolved"))
    elif snapshot.status != "available":
        checks.append(_check("snapshot_identity", "failed", "hard", f"Snapshot status is {snapshot.status}"))
    elif snapshot.snapshot_id != case.dataset_snapshot.snapshot_id:
        checks.append(
            _check(
                "snapshot_identity",
                "failed",
                "hard",
                "resolved Snapshot does not match Case Snapshot",
                case.dataset_snapshot.snapshot_id,
                snapshot.snapshot_id,
            )
        )
    else:
        checks.append(_check("snapshot_identity", "passed", "hard", "Case and resolved Snapshot identities match"))

    try:
        variant_identity = variant.identity
    except EvaluationContractError as exc:
        checks.append(_check("variant_identity", "failed", "hard", str(exc)))
    else:
        checks.append(_check("variant_identity", "passed", "hard", f"resolved Variant {variant_identity}"))

    expected_scope = scope_identity(case.data_access_scope)
    request_scope = scope_identity(request.scope)
    if expected_scope != request_scope:
        checks.append(_check("data_access_scope", "failed", "hard", "QueryRequest scope differs from Case scope"))
    else:
        checks.append(_check("data_access_scope", "passed", "hard", "QueryRequest preserves Case Data Access Scope"))

    if result is None:
        checks.append(_check("query_terminal_state", "failed", "hard", "Query raised before a QueryResult was returned"))
    else:
        checks.append(_check("query_terminal_state", "passed", "hard", f"Query returned terminal state {result.termination}"))

    if result is None:
        checks.append(_check("answer_artifact_contract", "not_applicable", "hard", "Query did not produce a successful Answer Artifact"))
        checks.append(_check("finalization_state", "not_applicable", "hard", "Finalization was not successful"))
        checks.append(_check("citation_provenance", "not_applicable", "hard", "No successful citation finalization to validate"))
    elif result.finalization_error is not None:
        # Finalizer/Citation 已明确返回 failure 时必须成为 hard gate，不能被归类为“未适用”。
        checks.append(_check("answer_artifact_contract", "failed", "hard", "Answer Artifact was rejected by production Finalizer"))
        checks.append(
            _check(
                "finalization_state",
                "failed",
                "hard",
                f"Production Finalizer failed with {result.finalization_error.code}",
            )
        )
        checks.append(
            _check(
                "citation_provenance",
                "failed",
                "hard",
                f"Citation/provenance validation failed with {result.finalization_error.code}",
            )
        )
    elif not result.is_successful:
        checks.append(_check("answer_artifact_contract", "not_applicable", "hard", "Query did not produce a successful Answer Artifact"))
        checks.append(_check("finalization_state", "not_applicable", "hard", "Finalization was not successful"))
        checks.append(_check("citation_provenance", "not_applicable", "hard", "No successful citation finalization to validate"))
    else:
        if isinstance(result.answer_artifact, AnswerArtifact):
            checks.append(_check("answer_artifact_contract", "passed", "hard", "Answer Artifact passed the production contract"))
        else:
            checks.append(_check("answer_artifact_contract", "failed", "hard", "Successful QueryResult has no Answer Artifact"))
        if result.finalization_status == "degraded":
            # degraded Artifact 可交付但不能被质量检查误认为已完成 grounded citation。
            checks.append(_check("finalization_state", "degraded", "diagnostic", "Production Finalizer delivered a degraded Artifact"))
            checks.append(_check("citation_provenance", "degraded", "diagnostic", "Citation provenance was partially dropped or normalized"))
        elif result.finalization_error is None:
            checks.append(_check("finalization_state", "passed", "hard", "Production Finalizer completed"))
            checks.append(_check("citation_provenance", "passed", "hard", "Production citation/provenance validation completed"))
        else:
            checks.append(
                _check(
                    "finalization_state",
                    "failed",
                    "hard",
                    f"Production Finalizer failed with {result.finalization_error.code}",
                )
            )
            checks.append(
                _check(
                    "citation_provenance",
                    "failed",
                    "hard",
                    f"Citation/provenance validation failed with {result.finalization_error.code}",
                )
            )

    if trace is None:
        checks.append(_check("trace_exists", "failed", "hard", "Trace reference could not be read"))
    else:
        checks.append(_check("trace_exists", "passed", "hard", f"Trace {trace.trace_id} is readable"))
        if trace.completeness == "complete":
            checks.append(_check("trace_completeness", "passed", "diagnostic", "Trace projection is complete"))
        else:
            checks.append(
                _check(
                    "trace_completeness",
                    "failed",
                    "diagnostic",
                    f"Trace completeness is {trace.completeness}; quality is not inferred from this fact",
                )
            )

    if trace is None or result is None:
        checks.append(_check("trace_terminal_consistency", "unknown", "hard", "Trace/result terminal consistency cannot be checked"))
    else:
        expected_terminal = "completed" if result.is_successful else "aborted" if result.termination == "aborted" else "failed"
        if trace.terminal_status == expected_terminal:
            checks.append(_check("trace_terminal_consistency", "passed", "hard", f"Trace terminal matches {expected_terminal}"))
        else:
            checks.append(
                _check(
                    "trace_terminal_consistency",
                    "failed",
                    "hard",
                    f"Trace terminal {trace.terminal_status} does not match QueryResult {expected_terminal}",
                )
            )

    if trace is not None:
        forced_route = request.execution_override.forced_route
        operations = {item.operation: item for item in trace.timeline}
        router_decisions = [item for item in trace.timeline if item.operation == "router.decision"]
        if forced_route is None:
            if "router.started" in operations and "router.bypassed" not in operations:
                checks.append(_check("execution_override", "passed", "hard", "Normal execution retained Router decision"))
            else:
                checks.append(_check("execution_override", "failed", "hard", "Normal execution did not retain Router evidence"))
        else:
            override_decision = False
            for item in router_decisions:
                override_payload = item.payload.get("execution_override")
                if (
                    item.payload.get("source") == "evaluation_override"
                    and isinstance(override_payload, Mapping)
                    and override_payload.get("forced_route") == forced_route
                ):
                    override_decision = True
                    break
            bypassed = any(
                item.payload.get("route") == forced_route
                for item in trace.timeline
                if item.operation == "router.bypassed"
            )
            if override_decision and bypassed:
                checks.append(_check("execution_override", "passed", "hard", f"Forced route {forced_route} is explicit in Trace"))
            else:
                checks.append(_check("execution_override", "failed", "hard", f"Forced route {forced_route} is not explicit in Trace"))
    else:
        checks.append(_check("execution_override", "unknown", "hard", "Trace is unavailable for override validation"))

    _context_limit = request.execution_override.context_window_limit
    if _context_limit is None:
        checks.append(_check("context_expansion_override", "not_applicable", "hard", "No context window override requested"))
    elif trace is None:
        checks.append(_check("context_expansion_override", "unknown", "hard", "Trace is unavailable for context window override validation"))
    else:
        checked_calls = 0
        violations: list[str] = []
        for item in trace.timeline:
            if item.operation != "retrieval.search.completed":
                continue
            query_payload = item.payload.get("query")
            if not isinstance(query_payload, Mapping):
                continue
            checked_calls += 1
            before = query_payload.get("context_before")
            after = query_payload.get("context_after")
            if (
                isinstance(before, bool)
                or isinstance(after, bool)
                or not isinstance(before, int)
                or not isinstance(after, int)
                or before > _context_limit
                or after > _context_limit
            ):
                violations.append(f"{item.operation_id}:context={before!r}/{after!r}")
        if violations:
            checks.append(
                _check(
                    "context_expansion_override",
                    "failed",
                    "hard",
                    f"Executed retrieval context window exceeds override limit {_context_limit}: {violations[:3]!r}",
                )
            )
        else:
            checks.append(
                _check(
                    "context_expansion_override",
                    "passed",
                    "hard",
                    f"All {checked_calls} executed retrieval calls respect context window limit {_context_limit}",
                )
            )

    if result is None:
        checks.append(_check("limitation_preservation", "unknown", "diagnostic", "No RuntimeResult is available"))
    else:
        runtime_limitations = {
            limitation
            for record in result.runtime_result.tool_results
            for limitation in record.limitations
        }
        if not runtime_limitations:
            checks.append(_check("limitation_preservation", "not_applicable", "diagnostic", "Run has no Tool limitations"))
        elif trace is None:
            checks.append(_check("limitation_preservation", "failed", "diagnostic", "Tool limitations exist but Trace is unavailable"))
        else:
            # Trace canonical event 的 payload 记录 partial/truncated 事实，分析层把它映射回
            # Runtime limitation 名称；这里只读事实，不改写 append-only Trace。
            trace_limitations: set[str] = {
                limitation
                for item in trace.timeline
                for limitation in item.limitations
            }
            for item in trace.timeline:
                if item.payload.get("partial") is True:
                    trace_limitations.update(("retrieval_partial", "tool_result_partial"))
                if item.payload.get("truncated") is True:
                    trace_limitations.add("retrieval_truncated")
            missing = sorted(runtime_limitations - trace_limitations)
            if missing:
                checks.append(_check("limitation_preservation", "failed", "diagnostic", f"Trace lost limitations: {missing!r}"))
            else:
                checks.append(_check("limitation_preservation", "passed", "diagnostic", "Tool limitations remain visible in Trace"))

    checks.append(
        _check(
            "replay_identity",
            "passed" if request.request_id and (result is None or result.trace_id) else "failed",
            "hard",
            "Query request and Trace identity are available" if request.request_id and (result is None or result.trace_id) else "Required replay identity is missing",
        )
    )
    return tuple(checks)


def build_evaluation_result(
    *,
    run_id: str,
    checks: tuple[DeterministicCheck, ...],
    result: QueryResult | None,
    trace: TraceProjection | None,
) -> EvaluationResult:
    """把单次 Run 转成不含总分的 Result 投影。"""

    hard_failed = any(item.severity == "hard" and item.status == "failed" for item in checks)
    status = "failed" if result is None or (result is not None and not result.is_successful) or hard_failed else "not_reviewed"
    diagnostics_failed = any(item.name == "trace_completeness" and item.status == "failed" for item in checks)
    quality_axes = {axis: {"label": "not_reviewed"} for axis in QUALITY_AXES}
    diagnosability = {
        "trace_available": trace is not None,
        "trace_completeness": None if trace is None else trace.completeness,
        "trace_completeness_check_failed": diagnostics_failed,
    }
    return EvaluationResult(
        result_id=f"result:{run_id}",
        run_id=run_id,
        status=status,  # type: ignore[arg-type]
        quality_axes=quality_axes,
        diagnosability=diagnosability,
        operational_measurements=operational_measurements(result, trace),
    )
