"""对已暴露 Development Case 做 P0/P1 Planner-only 重复实验。"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from dataclasses import asdict
from pathlib import Path

from trivae.capabilities.contracts import ExecutionScope
from trivae.capabilities.execute_sql import ExecuteSQLCapability
from trivae.capabilities.find_members import FindMembersCapability
from trivae.capabilities.get_message_context import GetMessageContextCapability
from trivae.capabilities.get_schema import GetSchemaCapability
from trivae.capabilities.recent_messages import RecentMessagesCapability
from trivae.capabilities.search_messages import LexicalSearchCapability
from trivae.capabilities.semantic_search import SemanticSearchCapability
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.query.contracts import QueryContext, QueryRequest
from trivae.query.planner import PlannerCapabilitySummary, SoftPlanner
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "evaluation/planner-utility/manifest-v1.json"
CASE_IDS = (
    "pu-dependent-mattpocock",
    "dev-context-archify",
    "pu-aggregate-utc-types",
    "dev-zero-empty-3",
    "dev-temporal-30d",
    "dev-lexical-forge",
    "dev-cite-archify",
    "pu-rank-utc-session",
)
CAPABILITY_METADATA = (
    LexicalSearchCapability.metadata,
    SemanticSearchCapability.metadata,
    RecentMessagesCapability.metadata,
    GetMessageContextCapability.metadata,
    FindMembersCapability.metadata,
    GetSchemaCapability.metadata,
    ExecuteSQLCapability.metadata,
)


def p0_prompt(context: QueryContext) -> str:
    """冻结 `12f2f75` 的旧 Planner prompt；只用于离线对照。"""

    # 以下文本逐字保留任务起点 `_build_prompt` 的旧模板，动态字段顺序也相同。
    snapshot = json.dumps(dict(context.data_snapshot), ensure_ascii=False, default=str)
    history = "\n".join(f"{message.role}: {message.content}" for message in context.prior_context)
    return (
        "Create a concise soft plan for this Trivae query. Return JSON only with keys: "
        "version (1), title, intent, steps, success_criteria. "
        "intent MUST be exactly one of: summary, trend, relationship, search, comparison, evidence, mixed. "
        "steps MUST be a JSON array with 1 to 5 objects. Each step MUST have a non-empty string goal, "
        "suggested_tools as a JSON array of strings (it may be empty), and evidence_needed as a JSON array "
        "of strings (it may be empty). success_criteria MUST be a non-empty JSON array of strings with at "
        "most 5 items. Do not use a sentence or explanation as intent. Do not use null, an object, or a "
        "string where an array is required. Do not wrap the JSON in Markdown fences. Use only the supplied "
        "capabilities. The plan is guidance only, not an executable workflow. Keep every text concise. "
        "For a time-bounded question asking whether messages exist and what was discussed, suggest "
        "get_recent_messages before SQL: a complete empty window settles both questions. A SQL count "
        "alone is not verified zero-result evidence; do not add schema or SQL solely to reconfirm "
        "a complete empty retrieval.\n"
        f"locale: {context.locale}\nquery: {context.query}\n"
        f"prior model context:\n{history or '<none>'}\n"
        f"available capabilities: {list(context.available_capabilities)!r}\n"
        f"data snapshot: {snapshot}"
    )


class P0Planner(SoftPlanner):
    """P0 仅替换 prompt builder，保留当前同一 parser 与 Provider boundary。"""

    @staticmethod
    def _build_prompt(
        context: QueryContext,
        capability_summaries: tuple[PlannerCapabilitySummary, ...] = (),
    ) -> str:
        # P0 原版没有 capability summary；故意忽略此参数以保持对照真实性。
        return p0_prompt(context)


def load_cases() -> list[dict[str, object]]:
    """只读取已有暴露 Development manifest 所指向的八条 Case。"""

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["fresh"] or manifest["blind"] or manifest["source_suite"] != "resume-benchmark-dev@v2":
        raise ValueError("planner-only suite must remain exposed Development data")
    entries = {item["case_id"]: item for item in manifest["cases"]}
    cases = []
    for case_id in CASE_IDS:
        entry = entries[case_id]
        source = ROOT / entry["case_bundle"]
        bundle = json.loads(source.read_text(encoding="utf-8"))
        # 来源和版本来自同一现有 manifest；不创建独立 GT 或查询改写。
        cases.append({
            "case_id": case_id,
            "version": entry["case_version"],
            "source": entry["case_bundle"],
            "workload_slice": entry["workload_slice"],
            "query": bundle["query"],
            "locale": bundle["locale"],
            "snapshot": bundle["dataset_snapshot"]["manifest"],
        })
    return cases


def context_for(case: dict[str, object]) -> QueryContext:
    """从已固定 Case/Snapshot 构造两路完全相同的 Planner 输入。"""

    snapshot = case["snapshot"]
    assert isinstance(snapshot, dict)
    # Planner 只需 compact coverage，完整 DatasetSnapshot 和聊天正文都不进入本实验。
    compact_snapshot = {
        "message_count": snapshot["message_count"],
        "first_timestamp": snapshot["first_timestamp"],
        "last_timestamp": snapshot["last_timestamp"],
        "lexical_index": snapshot["lexical_index"],
    }
    return QueryContext(
        query=str(case["query"]),
        locale=str(case["locale"]),
        prior_context=(),
        data_snapshot=compact_snapshot,
        available_capabilities=QueryRequest(query="planner-only", scope=ExecutionScope()).available_capabilities,
    )


def _plan_card(record: dict[str, object]) -> str:
    """只渲染 Plan 内容，避免盲审包泄漏 P0/P1 标签。"""

    plan = record["plan"]
    if plan is None:
        return f"Plan unavailable: {record['failure']}"
    assert isinstance(plan, dict)
    lines = [f"Title: {plan['title']}", f"Intent: {plan['intent']}"]
    for index, step in enumerate(plan["steps"], 1):
        lines.extend([
            f"{index}. Goal: {step['goal']}",
            f"   Suggested tools: {', '.join(step['suggested_tools']) or '(none)'}",
            f"   Evidence needed: {'; '.join(step['evidence_needed']) or '(none)'}",
        ])
    lines.append("Success criteria: " + "; ".join(plan["success_criteria"]))
    return "\n".join(lines)


def write_packet(records: list[dict[str, object]], output_dir: Path, repeats: int) -> None:
    """每个 Case/repeat 独立随机 A/B；映射另存，正文不显示版本。"""

    keyed = {(str(r["case_id"]), int(r["repeat"]), str(r["variant"])): r for r in records}
    rng = random.Random(20260927)
    key: list[dict[str, object]] = []
    lines = [
        "# Planner-only blind review packet",
        "",
        "Reviewer: ______   Date: ______",
        "",
        "For each pair choose A better / B better / indifferent / uncertain and give a short reason.",
        "Check entity preservation, scope discipline, tool relevance, incremental value, evidence alignment,",
        "context/relation quality, redundancy, overplanning, and parse/provider failures separately.",
        "These are soft plans only; no Runtime answer or human adjudication is implied.",
        "",
    ]
    for case in load_cases():
        case_id = str(case["case_id"])
        for repeat in range(1, repeats + 1):
            variants = ["P0", "P1"]
            rng.shuffle(variants)
            pair_id = f"{case_id}-r{repeat}"
            key.append({"pair_id": pair_id, "A": variants[0], "B": variants[1]})
            lines.extend([f"## {pair_id}", "", f"User Query: {case['query']}", ""])
            for label, variant in zip(("A", "B"), variants, strict=True):
                lines.extend([f"### Plan {label}", "", "```text", _plan_card(keyed[(case_id, repeat, variant)]), "```", ""])
            lines.extend(["Decision: ______", "Reason: ______", ""])
    (output_dir / "blind-review-packet.md").write_text("\n".join(lines), encoding="utf-8")
    (output_dir / "blind-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def run(output_dir: Path, repeats: int) -> None:
    """只调用 Planner completion；每次请求即时落盘，失败仍计入分母。"""

    output_dir.mkdir(parents=True, exist_ok=False)
    load_environment_file()
    settings = load_settings()
    runtime = OpenAIAgentsRuntimeAdapter(settings=settings)
    request = runtime.completion_request_projection()
    completion = runtime.complete_text_with_observation
    planners = {
        "P0": P0Planner(completion, completion_request=request),
        "P1": SoftPlanner(completion, completion_request=request, capability_metadata=CAPABILITY_METADATA),
    }
    cases = load_cases()
    records: list[dict[str, object]] = []
    try:
        with (output_dir / "runs.jsonl").open("w", encoding="utf-8") as sink:
            for case in cases:
                context = context_for(case)
                for repeat in range(1, repeats + 1):
                    # 交替顺序削弱时间漂移；每次仍是独立的单次 completion，不自动重试。
                    for variant in (("P0", "P1") if repeat % 2 else ("P1", "P0")):
                        result = await planners[variant].plan(context)
                        observation = result.observation
                        record: dict[str, object] = {
                            "run_id": f"pqc:{case['case_id']}:{variant}:r{repeat}",
                            "case_id": case["case_id"],
                            "case_version": case["version"],
                            "source": case["source"],
                            "repeat": repeat,
                            "variant": variant,
                            "provider": None if observation is None else observation.provider,
                            "model": None if observation is None else observation.model,
                            "latency_ms": None if observation is None else observation.latency_ms,
                            "provider_latency_ms": None if observation is None else observation.provider_latency_ms,
                            "request": None if observation is None else dict(observation.request),
                            "usage": None if observation is None or observation.usage is None else dict(observation.usage),
                            "finish_reason": None if observation is None else observation.finish_reason,
                            "parse_stage": None if observation is None else observation.parse_stage,
                            "parse_success": result.plan is not None,
                            "failure_detail_code": None if observation is None else observation.failure_detail_code,
                            "prompt": None if observation is None else observation.prompt,
                            "response_content": None if observation is None else observation.response_content,
                            "plan": None if result.plan is None else asdict(result.plan),
                            "failure": None if result.failure is None else asdict(result.failure),
                            "degraded": result.failure is not None,
                            "degradation_code": None if result.failure is None else result.failure.code,
                            "cost": {"status": "unavailable"},
                        }
                        sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                        sink.flush()
                        records.append(record)
                        print(f"{record['run_id']} {'ok' if result.plan is not None else result.failure.detail_code}", flush=True)
    finally:
        await runtime.aclose()
    write_packet(records, output_dir, repeats)
    (output_dir / "run-config.json").write_text(json.dumps({
        "source_manifest": str(MANIFEST.relative_to(ROOT)),
        "case_ids": list(CASE_IDS),
        "repeats": repeats,
        "p0_source_commit": "12f2f75",
        "chatlab_commit": "3e0e0fbbfb2b80051d261d34bf8349d64ab4c6e8",
        "provider": settings.provider,
        "model": settings.model_name,
        "completion_max_tokens": settings.completion_max_tokens,
        "runtime_tool_loop_executed": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 2:
        raise ValueError("Planner-only comparison requires at least two repetitions")
    asyncio.run(run(args.output_dir, args.repeats))
