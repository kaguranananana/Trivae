"""冻结 P1 prompt，单独检验非思考模式或 Planner output budget。"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path

from run_planner_only import NonThinkingAdapter, P1Planner, context_for, load_cases

from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter


async def run(output_dir: Path, repeats: int, mode: str, max_tokens: int | None) -> None:
    """独立执行 24 次诊断调用；失败保留且不用于正式三路 gate。"""

    output_dir.mkdir(parents=True, exist_ok=False)
    load_environment_file()
    settings = load_settings()
    # 两组消融只改一个因素：none 保持 2048，budget 保持 low 思考。
    if mode == "none":
        runtime = NonThinkingAdapter(settings=settings)
        variant = "P1-none"
    else:
        if max_tokens is None or max_tokens <= settings.completion_max_tokens:
            raise ValueError("budget mode requires a larger max_tokens")
        runtime = OpenAIAgentsRuntimeAdapter(settings=replace(settings, completion_max_tokens=max_tokens))
        variant = f"P1-budget-{max_tokens}"
    request = runtime.completion_request_projection()
    planner = P1Planner(runtime.complete_text_with_observation, completion_request=request)
    (output_dir / "run-config.json").write_text(json.dumps({
        "experiment_id": f"p1-original-prompt-{mode}-ablation-v1",
        "p1_source_commit": "68286d569025718c88029b66bc028e89a5a10c72",
        "repeats": repeats, "provider": settings.provider, "model": settings.model_name,
        "variant": variant,
        "request": request, "runtime_tool_loop_executed": False, "auto_retry": False,
        "formal_gate_run": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        with (output_dir / "runs.jsonl").open("w", encoding="utf-8") as sink:
            for case in load_cases():
                context = context_for(case)
                for repeat in range(1, repeats + 1):
                    # 单次调用的 observation 原样保存；没有失败后补跑。
                    result = await planner.plan(context)
                    observation = result.observation
                    record = {
                        "run_id": f"{variant}:{case['case_id']}:r{repeat}",
                        "case_id": case["case_id"], "case_version": case["version"],
                        "source": case["source"], "query": case["query"],
                        "repeat": repeat, "variant": variant,
                        "provider": None if observation is None else observation.provider,
                        "model": None if observation is None else observation.model,
                        "prompt": None if observation is None else observation.prompt,
                        "request": None if observation is None else dict(observation.request),
                        "usage": None if observation is None else observation.usage,
                        "latency_ms": None if observation is None else observation.latency_ms,
                        "provider_latency_ms": None if observation is None else observation.provider_latency_ms,
                        "finish_reason": None if observation is None else observation.finish_reason,
                        "response_content": None if observation is None else observation.response_content,
                        "parse_stage": None if observation is None else observation.parse_stage,
                        "failure_detail_code": None if observation is None else observation.failure_detail_code,
                        "plan": None if result.plan is None else asdict(result.plan),
                        "failure": None if result.failure is None else asdict(result.failure),
                        "cost": {"status": "unavailable"},
                    }
                    sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                    sink.flush()
                    print(f"{record['run_id']} {'ok' if result.plan else result.failure.detail_code}", flush=True)
    finally:
        await runtime.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--mode", choices=("none", "budget"), required=True)
    parser.add_argument("--max-tokens", type=int)
    args = parser.parse_args()
    if args.repeats < 2:
        raise ValueError("at least two independent repetitions are required")
    asyncio.run(run(args.output_dir, args.repeats, args.mode, args.max_tokens))
