"""运行确定性的 Agent/https synthetic Tool Result projection benchmark。"""

from __future__ import annotations

import json
import statistics
import time

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
    """构造稳定的长消息，Agent 与 https 只改变可见正文标签。"""

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
    """创建与真实 lexical Tool Result 相同形状的 canonical envelope。"""

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
    """使用三次重复的中位数，避免单次调度抖动冒充 projection 事实。"""

    return round(statistics.median(values), 3)


def main() -> None:
    """输出 JSONL，供任务 validation.md 直接引用 measured facts。"""

    configurations = (
        ("fixed", ToolResultBudgetConfig()),
        ("dynamic-128k", ToolResultBudgetConfig(mode="dynamic", context_window_tokens=128_000)),
    )
    for label in ("Agent", "https"):
        for count in (100, 300, 1000):
            envelope = _envelope(label, count)
            record_started = time.perf_counter()
            record = build_tool_result_record(
                run_id="synthetic-run",
                tool_call_id="synthetic-run/tool-call/1",
                tool_result_id="synthetic-run/tool-call/1/result",
                tool_name="lexical_search",
                envelope=envelope,
                scope=ExecutionScope(max_results=count),
            )
            build_ms = (time.perf_counter() - record_started) * 1000
            for mode, config in configurations:
                projection_times: list[float] = []
                projected = None
                snapshot = None
                for _ in range(3):
                    policy = config.new_policy()
                    reservation = policy.begin_call()
                    started = time.perf_counter()
                    projected = project_tool_result_for_model(
                        envelope,
                        record,
                        token_budget=reservation.effective_budget,
                    )
                    projection_times.append((time.perf_counter() - started) * 1000)
                    metrics = projected["model_projection"]
                    snapshot = policy.complete_call(
                        reservation,
                        projected_estimated_tokens=metrics["estimated_tokens"],
                        truncated=metrics["truncated"],
                        omitted_context_messages=metrics["omitted_context_messages"],
                        omitted_hit_messages=metrics["omitted_hit_messages"],
                    )
                assert projected is not None and snapshot is not None
                projected_bytes = len(
                    json.dumps(projected, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                )
                visible_messages = len(projected["provenance"]["message_sources"])
                print(
                    json.dumps(
                        {
                            "benchmark": "synthetic_projection",
                            "query": label,
                            "canonical_messages": len(record.message_items),
                            "requested_hits": count,
                            "mode": mode,
                            "effective_budget": snapshot.effective_tool_result_budget,
                            "build_ms": round(build_ms, 3),
                            "projection_ms_median": _median(projection_times),
                            "visible_messages": visible_messages,
                            "projected_bytes": projected_bytes,
                            "projected_estimated_tokens": snapshot.projected_estimated_tokens,
                            "truncated": snapshot.truncated,
                            "omitted_context_messages": snapshot.omitted_context_messages,
                            "omitted_hit_messages": snapshot.omitted_hit_messages,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )


if __name__ == "__main__":
    main()
