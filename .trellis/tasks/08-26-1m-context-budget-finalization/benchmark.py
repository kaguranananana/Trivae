"""运行 1M context 下 fixed/dynamic Tool Evidence projection 的确定性基准。"""

from __future__ import annotations

import json
import statistics
import time
import tracemalloc

from trivae.capabilities.contracts import ExecutionScope, ToolEnvelope
from trivae.query.evidence import build_tool_result_record, project_tool_result_for_model
from trivae.query.runtime.budget import ToolResultBudgetConfig
from trivae.retrieval.structured import (
    Coverage,
    LexicalQuery,
    MessageHit,
    MessageProjection,
    RetrievalMetadata,
    RetrievalResult,
)


def _message(index: int, label: str) -> MessageProjection:
    """构造固定长度 evidence；Agent 与 https 只改变 URL 形态。"""

    suffix = f" https://example.test/{label.lower()}/{index}" if label == "https" else ""
    return MessageProjection(
        internal_message_id=f"synthetic:{label}:{index}",
        session_id="synthetic-session",
        source_message_id=f"source-{index}",
        sender_user_id="synthetic-user",
        sender_platform_id=None,
        sender_uin=None,
        sender_name="Synthetic User",
        timestamp=1_700_000_000_000 + index,
        seq=index,
        message_type="text",
        normalized_content=(f"{label} evidence item {index} " + "long deterministic evidence " * 30 + suffix),
        reply_to_source_message_id=None,
        recalled=False,
        system=False,
        session_display="Synthetic Fixture",
    )


def _envelope(label: str, count: int) -> ToolEnvelope:
    """创建与 lexical Tool Result 相同形状的 bounded canonical envelope。"""

    messages = tuple(_message(index, label) for index in range(count))
    retrieval = RetrievalResult(
        query=LexicalQuery(keyword=label, limit=count, context_before=0, context_after=0),
        filters={},
        strategy="lexical",
        hits=tuple(MessageHit(message, (label,), 1.0, "synthetic") for message in messages),
        expanded_messages=(),
        total_hits=count,
        returned_messages=count,
        coverage=Coverage("complete", "canonical_plus_lexical_index"),
        partial=False,
        truncated=False,
        metadata=RetrievalMetadata(filters={}, ordering="synthetic", latency_ms=0.0),
    )
    return ToolEnvelope("ok", retrieval, {}, None)


def _median(values: list[float]) -> float:
    """用三次重复的中位数表示 projection latency，减少调度抖动。"""

    return round(statistics.median(values), 3)


def _configurations() -> tuple[tuple[str, ToolResultBudgetConfig], ...]:
    """返回核心三档和上一轮 64k reference，所有 dynamic candidate 使用 1M context。"""

    return (
        ("fixed-16k", ToolResultBudgetConfig(mode="fixed")),
        (
            "dynamic-run-128k",
            ToolResultBudgetConfig(
                mode="dynamic",
                context_window_tokens=1_000_000,
                run_tool_evidence_budget_override=128_000,
            ),
        ),
        (
            "dynamic-run-256k",
            ToolResultBudgetConfig(
                mode="dynamic",
                context_window_tokens=1_000_000,
                run_tool_evidence_budget_override=256_000,
            ),
        ),
        (
            "historical-dynamic-run-64k",
            ToolResultBudgetConfig(
                mode="dynamic",
                context_window_tokens=128_000,
                run_tool_evidence_budget_override=64_000,
            ),
        ),
    )


def _measure_projection(
    envelope: ToolEnvelope,
    record: object,
    config: ToolResultBudgetConfig,
) -> tuple[dict[str, object], float, float]:
    """运行三次同一 policy，返回稳定 snapshot、projection 中位数和峰值分配。"""

    projection_times: list[float] = []
    peak_allocations: list[float] = []
    snapshot = None
    projected = None
    for _ in range(3):
        policy = config.new_policy()
        reservation = policy.begin_call()
        tracemalloc.start()
        started = time.perf_counter()
        projected = project_tool_result_for_model(
            envelope,
            record,  # type: ignore[arg-type]
            token_budget=reservation.effective_per_call_budget,
        )
        projection_times.append((time.perf_counter() - started) * 1000)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_allocations.append(peak / 1024)
        metrics = projected["model_projection"]
        snapshot = policy.complete_call(
            reservation,
            projected_tool_result_tokens=metrics["estimated_tokens"],  # type: ignore[index]
            truncated=metrics["truncated"],  # type: ignore[index]
            omitted_context_messages=metrics["omitted_context_messages"],  # type: ignore[index]
            omitted_hit_messages=metrics["omitted_hit_messages"],  # type: ignore[index]
        )
    assert projected is not None and snapshot is not None
    visible_messages = len(projected["provenance"]["message_sources"])  # type: ignore[index]
    return (
        {
            "per_call_effective_budget": snapshot.effective_per_call_tool_result_budget,
            "per_call_ceiling": snapshot.per_call_tool_result_ceiling,
            "run_pool": snapshot.run_tool_evidence_budget,
            "final_remaining_run_pool": snapshot.remaining_run_tool_evidence_budget_after_call,
            "visible_message_count": visible_messages,
            "visible_estimated_tokens": snapshot.projected_tool_result_tokens,
            "omitted_hit_messages": snapshot.omitted_hit_messages,
            "omitted_context_messages": snapshot.omitted_context_messages,
            "truncated": snapshot.truncated,
            "budget_resolution": snapshot.budget_resolution,
            "context_window_tokens": snapshot.context_window_tokens,
            "context_window_source": snapshot.context_window_source,
        },
        _median(projection_times),
        round(statistics.median(peak_allocations), 3),
    )


def main() -> None:
    """输出 JSONL；这些是 projection operational facts，不自动推导答案质量。"""

    for label in ("Agent", "https"):
        for count in (100, 300, 1_000):
            retrieval_started = time.perf_counter()
            envelope = _envelope(label, count)
            retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
            record_started = time.perf_counter()
            record = build_tool_result_record(
                run_id="synthetic-run",
                tool_call_id="synthetic-run/tool-call/1",
                tool_result_id="synthetic-run/tool-call/1/result",
                tool_name="lexical_search",
                envelope=envelope,
                scope=ExecutionScope(max_results=count),
            )
            record_ms = (time.perf_counter() - record_started) * 1000
            for variant, config in _configurations():
                facts, projection_ms, peak_allocated_kib = _measure_projection(envelope, record, config)
                print(
                    json.dumps(
                        {
                            "benchmark": "1m_dynamic_tool_evidence_projection",
                            "query": label,
                            "requested_hits": count,
                            "total_hits": count,
                            "canonical_message_count": len(record.message_items),
                            "variant": variant,
                            "retrieval_ms": round(retrieval_ms, 3),
                            "record_build_ms": round(record_ms, 3),
                            "projection_ms_median": projection_ms,
                            "projection_peak_allocated_kib_median": peak_allocated_kib,
                            **facts,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )


if __name__ == "__main__":
    main()
