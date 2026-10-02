"""对已暴露 Development Case 做 P0/P1/P1-B/P2 Planner-only 交错实验。"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import subprocess
from dataclasses import asdict
from pathlib import Path
from statistics import mean, median
from typing import Any

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
P1_PROMPTS = json.loads((Path(__file__).parent / "frozen-p1-prompts.json").read_text(encoding="utf-8"))
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


class P1Planner(SoftPlanner):
    """从上一轮的实际 request 固定 P1 prompt，防止本轮 P2 代码污染对照。"""

    @staticmethod
    def _build_prompt(
        context: QueryContext,
        capability_summaries: tuple[PlannerCapabilitySummary, ...] = (),
    ) -> str:
        # 本实验只含八个固定 Development query；缺失 fixture 必须显式失败。
        return str(P1_PROMPTS[context.query])


class NonThinkingAdapter(OpenAIAgentsRuntimeAdapter):
    """仅供离线 ablation：请求 DeepSeek 非思考模式，其余 Provider 边界保持原样。"""

    def _resolved_reasoning_effort(self) -> Any:
        # 官方 Chat Completions 接受 none；实验前不改生产共享 completion 配置。
        return "none"


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
    """只渲染 Plan 内容，避免盲审包泄漏三路标签。"""

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
    """每个 Case/repeat 独立随机 A/B/C；映射另存，正文不显示版本。"""

    keyed = {(str(r["case_id"]), int(r["repeat"]), str(r["variant"])): r for r in records}
    rng = random.Random(20260928)
    key: list[dict[str, object]] = []
    lines = [
        "# Planner-only blind review packet",
        "",
        "Reviewer: ______   Date: ______",
        "",
        "For each triple rank A/B/C or mark uncertain; give a short reason for each rubric axis.",
        "Check entity preservation, scope discipline, tool relevance, incremental value, evidence alignment,",
        "context/relation quality, redundancy, overplanning, and parse/provider failures separately.",
        "These are soft plans only; no Runtime answer or human adjudication is implied.",
        "",
    ]
    for case in load_cases():
        case_id = str(case["case_id"])
        for repeat in range(1, repeats + 1):
            # P1-B 仅用于根因 ablation；正式质量盲审比较三条候选路线。
            variants = ["P0", "P1", "P2"]
            rng.shuffle(variants)
            review_id = f"{case_id}-r{repeat}"
            key.append({"review_id": review_id, **dict(zip(("A", "B", "C"), variants, strict=True))})
            lines.extend([f"## {review_id}", "", f"User Query: {case['query']}", ""])
            for label, variant in zip(("A", "B", "C"), variants, strict=True):
                lines.extend([f"### Plan {label}", "", "```text", _plan_card(keyed[(case_id, repeat, variant)]), "```", ""])
            lines.extend(["Ranking / uncertain: ______", "Rubric observations: ______", ""])
    (output_dir / "blind-review-packet.md").write_text("\n".join(lines), encoding="utf-8")
    (output_dir / "blind-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def metrics_for(
    records: list[dict[str, object]],
    repeats: int,
    variant_names: tuple[str, ...] = ("P0", "P1", "P1-B", "P2"),
) -> dict[str, object]:
    """从原始 run 生成操作性指标；所有失败都保留在正式分母。"""

    metrics: dict[str, object] = {"case_count": len(CASE_IDS), "repeats": repeats, "provider_calls": len(records), "runtime_tool_loop_calls": 0, "cost_status": "unavailable", "variants": {}}
    variants = metrics["variants"]
    assert isinstance(variants, dict)
    for variant in variant_names:
        calls = [record for record in records if record["variant"] == variant]
        successes = [record for record in calls if record["parse_success"]]
        latencies = [float(record["latency_ms"]) for record in calls]
        failures: dict[str, int] = {}
        finish_reasons: dict[str, int] = {}
        for record in calls:
            reason = str(record["finish_reason"])
            finish_reasons[reason] = finish_reasons.get(reason, 0) + 1
            if not record["parse_success"]:
                code = str(record["failure_detail_code"] or record["degradation_code"])
                failures[code] = failures.get(code, 0) + 1
        # usage 仅累计 Provider 实际返回的字段；缺失 reasoning 明细不补造。
        usage_totals = {name: sum(int(record["usage"].get(name, 0)) for record in calls if isinstance(record["usage"], dict)) for name in ("input_tokens", "output_tokens", "total_tokens")}
        reasoning_observed = sum(isinstance(record["usage"], dict) and "reasoning_tokens" in record["usage"] for record in calls)
        # 非思考请求不返回 reasoning 明细；unknown 不能显示成测得的零。
        usage_totals["reasoning_tokens"] = None if not reasoning_observed else sum(int(record["usage"].get("reasoning_tokens", 0)) for record in calls if isinstance(record["usage"], dict))
        step_counts = [len(record["plan"]["steps"]) for record in successes]
        variants[variant] = {
            "calls": len(calls), "valid_plans": len(successes), "failure_detail_counts": failures,
            "finish_reason_counts": finish_reasons, "usage_totals": usage_totals,
            "reasoning_usage_observed_calls": reasoning_observed,
            "latency_ms": {"mean": round(mean(latencies), 1), "median": round(median(latencies), 1)},
            "mean_successful_plan_steps": None if not step_counts else round(mean(step_counts), 2),
            "prompt_chars_mean": round(mean(int(record["prompt_chars"]) for record in calls), 1),
            "case_success": {case_id: sum(record["case_id"] == case_id and bool(record["parse_success"]) for record in calls) for case_id in CASE_IDS},
        }
    return metrics


async def run(output_dir: Path, repeats: int, *, final: bool = False) -> None:
    """只调用 Planner completion；每次请求即时落盘，失败仍计入分母。"""

    output_dir.mkdir(parents=True, exist_ok=False)
    load_environment_file()
    settings = load_settings()
    runtime = OpenAIAgentsRuntimeAdapter(settings=settings)
    request = runtime.completion_request_projection()
    planners: dict[str, SoftPlanner] = {
        "P0": P0Planner(runtime.complete_text_with_observation, completion_request=request),
        "P1": P1Planner(runtime.complete_text_with_observation, completion_request=request),
    }
    if final:
        # 最终 P2 使用生产 adapter 的 Planner 专属请求，确保实验与候选实现同一边界。
        planners["P2"] = SoftPlanner(
            runtime.complete_planner_text_with_observation,
            completion_request=runtime.planner_completion_request_projection(),
            capability_metadata=CAPABILITY_METADATA,
        )
        variant_names = ("P0", "P1", "P2")
        nonthinking_runtime = None
    else:
        # 第一轮归因实验保留压缩 prompt + thinking 的 P1-B 消融。
        nonthinking_runtime = NonThinkingAdapter(settings=settings)
        planners["P1-B"] = SoftPlanner(runtime.complete_text_with_observation, completion_request=request, capability_metadata=CAPABILITY_METADATA)
        planners["P2"] = SoftPlanner(nonthinking_runtime.complete_text_with_observation, completion_request=nonthinking_runtime.completion_request_projection(), capability_metadata=CAPABILITY_METADATA)
        variant_names = ("P0", "P1", "P1-B", "P2")
    cases = load_cases()
    source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=ROOT, text=True).strip()
    # 运行配置先落盘，异常中断时保留精确身份与已完成调用。
    (output_dir / "run-config.json").write_text(json.dumps({
        "experiment_id": "planner-p1-stability-final-v3" if final else "planner-p1-stability-development-v1",
        "source_commit": source_commit,
        "source_manifest": str(MANIFEST.relative_to(ROOT)),
        "case_ids": list(CASE_IDS), "repeats": repeats,
        "p0_source_commit": "12f2f75",
        "p1_source_commit": "68286d569025718c88029b66bc028e89a5a10c72",
        "p1_prompt_fixture": "evaluation/planner-p1-stability/frozen-p1-prompts.json",
        "provider": settings.provider, "model": settings.model_name,
        "completion_max_tokens": settings.completion_max_tokens,
        "variants": (
            {"P0": "frozen baseline, thinking low", "P1": "frozen previous candidate, thinking low", "P2": "compressed v3 prompt, thinking none via production Planner completion"}
            if final else
            {"P0": "frozen baseline, thinking low", "P1": "frozen previous candidate, thinking low", "P1-B": "compressed prompt ablation, thinking low", "P2": "compressed prompt candidate, thinking none"}
        ),
        "runtime_tool_loop_executed": False, "auto_retry": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    records: list[dict[str, object]] = []
    try:
        with (output_dir / "runs.jsonl").open("w", encoding="utf-8") as sink:
            for case_index, case in enumerate(cases):
                context = context_for(case)
                for repeat in range(1, repeats + 1):
                    # 每个 Case/repeat 都轮换顺序，避免按版本整批运行造成时间漂移。
                    base_order = variant_names
                    offset = (case_index + repeat - 1) % len(base_order)
                    for variant in base_order[offset:] + base_order[:offset]:
                        result = await planners[variant].plan(context)
                        observation = result.observation
                        record: dict[str, object] = {
                            "run_id": f"{'p1s-final' if final else 'p1s'}:{case['case_id']}:{variant}:r{repeat}",
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
                            "prompt_chars": None if observation is None else len(observation.prompt),
                            "response_content": None if observation is None else observation.response_content,
                            "response_chars": None if observation is None else len(observation.response_content or ""),
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
        if nonthinking_runtime is not None:
            await nonthinking_runtime.aclose()
    write_packet(records, output_dir, repeats)
    (output_dir / "metrics.json").write_text(json.dumps(metrics_for(records, repeats, variant_names), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    if args.repeats < 2:
        raise ValueError("Planner-only comparison requires at least two repetitions")
    asyncio.run(run(args.output_dir, args.repeats, final=args.final))
