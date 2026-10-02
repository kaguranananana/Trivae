"""对同一 P1 canonical prompt 执行 8 组 low/none Planner-only 配对实验。"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any

from run_planner_only import CAPABILITY_METADATA, CASE_IDS, P1_PROMPTS, context_for, load_cases

from trivae.config.dotenv import load_environment_file
from trivae.config.settings import DEFAULT_DEEPSEEK_BASE_URL, load_settings
from trivae.query.planner import SoftPlanner
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter

PROMPT_IDENTITY = "P1 canonical; exact frozen fixture and current production builder"
UNKNOWN = "unknown"


def write_json(path: Path, value: object) -> None:
    """实验配置和映射各写一次，保持可复核的原始文件。"""

    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def preflight() -> tuple[OpenAIAgentsRuntimeAdapter, dict[str, SoftPlanner], list[dict[str, object]], list[dict[str, object]], dict[str, str], dict[str, dict[str, object]]]:
    """首次 Provider 请求前检查全部 Case、prompt 和请求参数。"""

    # 只读取本地配置；此处创建 client 但不会发出网络请求。
    load_environment_file()
    settings = load_settings()
    if (settings.provider, settings.model_name, settings.completion_max_tokens) != ("deepseek", "deepseek-flash", 2048):
        raise ValueError("experiment requires deepseek/deepseek-flash and max_tokens=2048")
    if settings.base_url.rstrip("/") != DEFAULT_DEEPSEEK_BASE_URL:
        raise ValueError("experiment requires the official DeepSeek endpoint")

    runtime = OpenAIAgentsRuntimeAdapter(settings=settings)
    try:
        # 两侧使用同一个 adapter 方法；partial 只固定唯一实验变量。
        requests = {
            effort: runtime.completion_request_projection(reasoning_effort_override=effort)
            for effort in ("low", "none")
        }
        low_without_effort = {key: value for key, value in requests["low"].items() if key != "reasoning_effort"}
        none_without_effort = {key: value for key, value in requests["none"].items() if key != "reasoning_effort"}
        if low_without_effort != none_without_effort:
            raise ValueError("request parameters differ beyond reasoning_effort")
        if requests["low"]["reasoning_effort"] != "low" or requests["none"]["reasoning_effort"] != "none":
            raise ValueError("reasoning treatment mismatch")
        if requests["low"]["temperature"] != 0 or requests["low"]["response_format"] != {"type": "json_object"}:
            raise ValueError("temperature or JSON mode differs from canonical completion")
        if runtime.completion_request_projection()["reasoning_effort"] != "low":
            raise ValueError("registry low treatment is no longer canonical")

        planners = {
            effort: SoftPlanner(
                partial(runtime.complete_text_with_observation, reasoning_effort_override=effort),
                completion_request=requests[effort],
                capability_metadata=CAPABILITY_METADATA,
            )
            for effort in ("low", "none")
        }
        cases = load_cases()
        if tuple(case["case_id"] for case in cases) != CASE_IDS or len(cases) != 8:
            raise ValueError("exposed Development Case set changed")
        if len(CAPABILITY_METADATA) != 7 or any(planner.completion_timeout_seconds != 20.0 for planner in planners.values()):
            raise ValueError("capability metadata or Planner timeout changed")

        # 每条 Case 的生产 builder 必须与历史 P1 实际请求全文相同。
        prompts: dict[str, str] = {}
        for case in cases:
            context = context_for(case)
            case_id = str(case["case_id"])
            prompt = planners["low"]._build_prompt(context, planners["low"]._capability_summaries)
            other_prompt = planners["none"]._build_prompt(context, planners["none"]._capability_summaries)
            if prompt != other_prompt or prompt != P1_PROMPTS[str(case["query"])]:
                raise ValueError(f"P1 canonical prompt differs for {case_id}")
            if tuple(context.available_capabilities) != tuple(metadata.name for metadata in CAPABILITY_METADATA):
                raise ValueError(f"capability allowlist differs for {case_id}")
            prompts[case_id] = prompt

        # 奇偶 Case 反转请求顺序；固定表在任何结果出现前写盘。
        schedule = [
            {"run_order": 2 * index + offset + 1, "case_id": case["case_id"], "treatment": treatment}
            for index, case in enumerate(cases)
            for offset, treatment in enumerate(("low", "none") if index % 2 == 0 else ("none", "low"))
        ]
        if len(schedule) != 16:
            raise ValueError("hard request budget is not 16")
        return runtime, planners, cases, schedule, prompts, requests
    except Exception:
        # 预检失败不能留下可误用的 Provider client。
        asyncio.run(runtime.aclose())
        raise


def failure_category(result: Any) -> str:
    """把无效 Plan 的 Provider 与 parser 失败分开统计。"""

    if result.plan is not None:
        return "none"
    if result.failure is None:
        raise ValueError("Planner returned neither Plan nor failure")
    if result.failure.detail_code == "provider_length":
        return "provider_length"
    if result.failure.code == "invalid_output":
        return "parse_failure"
    return result.failure.code


def write_blind_packet(cases: list[dict[str, object]], prompts: dict[str, str], records: list[dict[str, object]], output_dir: Path) -> None:
    """只公开共同问题、共同 prompt 和 Plan 正文；标签映射另存。"""

    by_case = {(str(record["case_id"]), str(record["treatment"])): record for record in records}
    rng = random.SystemRandom()
    review_cases = list(cases)
    rng.shuffle(review_cases)
    key: list[dict[str, str]] = []
    lines = [
        "# P1 Planner blind semantic review",
        "",
        "每组只比较有效 Plan 的语义质量；无有效 Plan 时记 unjudgeable，可靠性单独分析。",
        "检查实体锚、Tool 相关性、步骤增量、direct hit→follow-up 证据关系、zero-result/时间窗、SQL、重复检索、success criteria 与无关目标。",
        "不要按篇幅、步骤数、Tool 数或 criteria 数量评高低；轻微差异判 same。",
        "",
    ]
    for case in review_cases:
        case_id = str(case["case_id"])
        treatments = ["low", "none"]
        rng.shuffle(treatments)
        key.append({"case_id": case_id, "A": treatments[0], "B": treatments[1]})
        lines.extend([f"## {case_id}", "", "### Common P1 canonical Planner input", "", "```text", prompts[case_id], "```", ""])
        for label, treatment in zip(("A", "B"), treatments, strict=True):
            record = by_case[(case_id, treatment)]
            plan = record["parsed_plan_json"]
            visible_plan = "No valid Plan" if plan is None else json.dumps(plan, ensure_ascii=False, indent=2)
            lines.extend([f"### Plan {label}", "", "```json", visible_plan, "```", ""])
        lines.extend(["Blind judgment (A better / B better / same / unjudgeable):", "Reason:", ""])
    (output_dir / "blind-review-packet.md").write_text("\n".join(lines), encoding="utf-8")
    write_json(output_dir / "blind-key.json", key)


async def execute(output_dir: Path, prepared: tuple[OpenAIAgentsRuntimeAdapter, dict[str, SoftPlanner], list[dict[str, object]], list[dict[str, object]], dict[str, str], dict[str, dict[str, object]]]) -> None:
    """按已固定顺序各发一次请求，响应后立刻保存原始记录。"""

    runtime, planners, cases, schedule, prompts, requests = prepared
    if output_dir.exists():
        raise FileExistsError(f"experiment output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    write_json(output_dir / "run-config.json", {
        "experiment_id": "p1-canonical-low-vs-none-development-2026-09-28",
        "prompt_identity": PROMPT_IDENTITY,
        "case_ids": list(CASE_IDS),
        "source_manifest": "evaluation/planner-utility/manifest-v1.json",
        "requests": requests,
        "planner_timeout_seconds": planners["low"].completion_timeout_seconds,
        "provider_request_budget": 16,
        "runtime_tool_loop_executed": False,
        "retry_or_replacement": False,
    })
    write_json(output_dir / "schedule.json", schedule)
    case_by_id = {str(case["case_id"]): case for case in cases}
    records: list[dict[str, object]] = []
    try:
        with (output_dir / "attempts.jsonl").open("w", encoding="utf-8") as attempts, (output_dir / "runs.jsonl").open("w", encoding="utf-8") as sink:
            for item in schedule:
                # attempt 先落盘；即使本进程中断，这次请求也占预算，不允许补跑。
                attempts.write(json.dumps(item, ensure_ascii=False) + "\n")
                attempts.flush()
                case_id = str(item["case_id"])
                effort = str(item["treatment"])
                result = await planners[effort].plan(context_for(case_by_id[case_id]))
                observation = result.observation
                if observation is None:
                    raise ValueError(f"missing Planner observation for {case_id}")
                usage = dict(observation.usage) if observation.usage is not None else {}
                record: dict[str, object] = {
                    "case_id": case_id,
                    "case_version": case_by_id[case_id]["version"],
                    "case_source": case_by_id[case_id]["source"],
                    "treatment": effort,
                    "run_order": item["run_order"],
                    "prompt_identity": PROMPT_IDENTITY,
                    "prompt": observation.prompt,
                    "provider": observation.provider or UNKNOWN,
                    "model": observation.model or UNKNOWN,
                    "reasoning_effort": effort,
                    "max_tokens": requests[effort]["max_tokens"],
                    "request": dict(observation.request),
                    "latency_ms": observation.latency_ms,
                    "provider_latency_ms": observation.provider_latency_ms if observation.provider_latency_ms is not None else UNKNOWN,
                    "finish_reason": observation.finish_reason or UNKNOWN,
                    "input_tokens": usage.get("input_tokens", UNKNOWN),
                    "completion_tokens": usage.get("output_tokens", UNKNOWN),
                    "reasoning_tokens": usage.get("reasoning_tokens", UNKNOWN),
                    "usage": usage or UNKNOWN,
                    "raw_visible_planner_output": observation.response_content if observation.response_content is not None else UNKNOWN,
                    "parse_result": {"success": result.plan is not None, "stage": observation.parse_stage or UNKNOWN},
                    "parsed_plan_json": None if result.plan is None else asdict(result.plan),
                    "failure_category": failure_category(result),
                    "failure_detail_code": result.failure.detail_code if result.failure is not None else "not_applicable",
                    "failure": None if result.failure is None else asdict(result.failure),
                    "monetary_cost": "unavailable",
                }
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                sink.flush()
                records.append(record)
                print(f"{item['run_order']}/16 {case_id} {effort}: {record['failure_category']}", flush=True)
    finally:
        await runtime.aclose()
    if len(records) != 16:
        raise ValueError(f"experiment ended with {len(records)} completed records; no replacement calls allowed")
    write_blind_packet(cases, prompts, records, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    prepared = preflight()
    if args.check_only:
        print("provider-free preflight passed: 8 canonical P1 prompts, 16 fixed requests, one differing parameter")
        asyncio.run(prepared[0].aclose())
        return
    if args.output_dir is None:
        asyncio.run(prepared[0].aclose())
        parser.error("--output-dir is required for execution")
    asyncio.run(execute(args.output_dir, prepared))


if __name__ == "__main__":
    main()
