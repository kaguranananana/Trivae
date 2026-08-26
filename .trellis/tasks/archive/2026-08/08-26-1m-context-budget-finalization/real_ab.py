"""在真实 provider 上运行 4 个固定 prompt 的 3×A/B/C 配对实验。"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter

from trivae.bootstrap.application import TrivaeApplication, create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import SettingsError, load_settings
from trivae.query.contracts import QueryRequest

CASES = {
    "github_skills_resources": "最近的这一个月之内，有没有讨论过一些有价值的 GitHub 仓库、Skills、有价值的一些资源之类的东西",
    "agent_learning_materials": "最近一个月群里推荐过哪些 Agent 学习资料？",
    "taste_skill": "群里对 taste-skill 的评价是什么？有没有人实际用过？",
    "deepseek_projects": "最近两周讨论过哪些 DeepSeek 相关项目？",
}

VARIANTS: dict[str, tuple[str, int | None]] = {
    # fixed 只保留历史 16k per-call 行为，不配置 shared run pool。
    "fixed-16k": ("fixed", None),
    # 两个 dynamic cell 只改变 run-level pool，per-call ceiling 保持 1M 模型的 128k。
    "dynamic-run-128k": ("dynamic", 128_000),
    "dynamic-run-256k": ("dynamic", 256_000),
}
REAL_CELL_TIMEOUT_SECONDS = 30


def _set_budget_environment(mode: str, run_budget: int | None) -> None:
    """只切换实验预算变量，provider/model 仍来自当前 `.env`。"""

    # 每个 cell 都明确写入 per-call 百分比和 cap，避免 shell 中残留旧变量改变实验条件。
    os.environ["TRIVAE_TOOL_RESULT_BUDGET_MODE"] = mode
    os.environ["TRIVAE_PER_CALL_TOOL_RESULT_PERCENT"] = "50"
    os.environ["TRIVAE_PER_CALL_TOOL_RESULT_CAP"] = "128000"
    os.environ["TRIVAE_RUN_TOOL_EVIDENCE_PERCENT"] = "25"
    os.environ["TRIVAE_RUN_TOOL_EVIDENCE_CAP"] = "256000"
    # 删除显式 context 让 opencode-go/deepseek-v4-flash 走 verified registry，验证真实默认解析。
    os.environ.pop("TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS", None)
    if run_budget is None:
        # fixed 的契约禁止携带 run-level override，不能留下上一 variant 的值。
        os.environ.pop("TRIVAE_RUN_TOOL_EVIDENCE_BUDGET", None)
    else:
        os.environ["TRIVAE_RUN_TOOL_EVIDENCE_BUDGET"] = str(run_budget)


def _trace_facts(application: TrivaeApplication, trace_id: str | None) -> dict[str, object]:
    """提取 Trace 中可比较的运行事实，不输出回答正文或 provider 原始对象。"""

    if trace_id is None:
        return {"trace_available": False}
    trace = application.read_trace(trace_id)
    budget_snapshots: list[dict[str, object]] = []
    for item in trace.timeline:
        raw_budget = item.payload.get("tool_result_budget")
        if item.operation == "runtime.tool.completed" and isinstance(raw_budget, Mapping):
            budget_snapshots.append(dict(raw_budget))
    finalization_events = [
        item
        for item in trace.timeline
        if item.operation == "answer.finalization.completed"
    ]
    finalization_facts = []
    for item in finalization_events:
        # Debug Trace 可能包含 answer_text；实验报告只需要状态和计数，绝不复制回答正文。
        allowed_keys = (
            "answer_length",
            "limitation_count",
            "finalization_status",
            "user_answer_preserved",
            "error_code",
            "error_path",
            "degradation_codes",
            "dropped_field_count",
            "dropped_field_paths",
            "dropped_citation_count",
            "normalization_count",
            "validated_citation_count",
        )
        finalization_facts.append(
            {key: item.payload[key] for key in allowed_keys if key in item.payload}
        )
    return {
        "trace_available": True,
        "trace_terminal_status": trace.terminal_status,
        "trace_completeness": trace.completeness,
        "trace_failures": tuple(
            failure.failure.error_code
            for failure in trace.failures
            if failure.failure.error_code
        ),
        "latency_ms": trace.metrics.total_duration_ms,
        "trace_tool_count": trace.metrics.tool_count,
        "trace_retrieval_count": trace.metrics.retrieval_count,
        "trace_usage": dict(trace.metrics.usage),
        "trace_tool_result_estimated_tokens": trace.metrics.tool_result_estimated_tokens,
        "trace_tool_result_projection_truncated_count": trace.metrics.tool_result_projection_truncated_count,
        "trace_tool_result_projection_omitted_context_messages": (
            trace.metrics.tool_result_projection_omitted_context_messages
        ),
        "trace_tool_result_projection_omitted_hit_messages": (
            trace.metrics.tool_result_projection_omitted_hit_messages
        ),
        "budget_snapshots": tuple(budget_snapshots),
        "finalization_events": tuple(finalization_facts),
    }


async def _run_one(
    application: TrivaeApplication,
    case_name: str,
    prompt: str,
    variant: str,
    repetition: int,
) -> dict[str, object]:
    """运行一个真实 cell，并将异常保留为显式 harness 结果。"""

    request_id = f"1m-budget-{variant}-{case_name}-{repetition}"
    started = perf_counter()
    try:
        result = await application.query(
            QueryRequest(
                prompt,
                ExecutionScope(),
                request_id=request_id,
                trace_profile="debug",
            )
        )
        trace_facts = _trace_facts(application, result.trace_id)
        calls = result.runtime_result.tool_calls
        return {
            "case": case_name,
            "variant": variant,
            "repetition": repetition,
            "request_id": request_id,
            "trace_id": result.trace_id,
            "provider": result.runtime_result.provider,
            "model": result.runtime_result.model,
            "termination": result.runtime_result.termination,
            "execution_status": result.execution_status,
            "finalization_status": result.finalization_status,
            "is_successful": result.is_successful,
            "is_degraded": result.is_degraded,
            "tool_calls": len(calls),
            "tool_rounds": result.runtime_result.tool_rounds,
            "evidence_count": len(result.runtime_result.tool_results),
            "citation_binding_count": (
                0 if result.answer_artifact is None else len(result.answer_artifact.citation_bindings)
            ),
            "projection_estimated_tokens": sum(
                call.model_result_estimated_tokens or 0 for call in calls
            ),
            "projection_truncated_count": sum(
                1 for call in calls if call.model_result_truncated is True
            ),
            "omitted_context_messages": sum(
                call.model_result_omitted_context_messages or 0 for call in calls
            ),
            "omitted_hit_messages": sum(
                call.model_result_omitted_hit_messages or 0 for call in calls
            ),
            "wall_clock_ms": round((perf_counter() - started) * 1000, 3),
            "finalization_diagnostics": (
                None
                if result.finalization_diagnostics is None
                else result.finalization_diagnostics.to_dict()
            ),
            **trace_facts,
        }
    except Exception as exc:
        # 真实 provider 错误只记录异常类型；继续其余配对 cell，绝不把失败伪装成成功。
        return {
            "case": case_name,
            "variant": variant,
            "repetition": repetition,
            "request_id": request_id,
            "status": "exception",
            "exception_type": type(exc).__name__,
            "exception_module": type(exc).__module__,
            "error_message": str(exc) if isinstance(exc, SettingsError) else None,
            "wall_clock_ms": round((perf_counter() - started) * 1000, 3),
        }


async def _run_worker(variant: str, case_name: str, repetition: int) -> None:
    """在独立 worker 进程中完成一个 cell，确保 provider hang 不污染其他 cell。"""

    mode, run_budget = VARIANTS[variant]
    _set_budget_environment(mode, run_budget)
    application = create_application(Path("data/trivae.sqlite3"))
    try:
        row = await _run_one(application, case_name, CASES[case_name], variant, repetition)
        print(json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)
    finally:
        # worker 自己拥有 Application，正常完成时仍必须在同一 event loop 内释放资源。
        await application.aclose()


def _worker_main(variant: str, case_name: str, repetition: int) -> None:
    """子进程入口；参数来自父 harness 的固定枚举，不解析任意 shell 文本。"""

    asyncio.run(_run_worker(variant, case_name, repetition))


def _run_cell_in_worker(
    variant: str,
    case_name: str,
    repetition: int,
    environment: dict[str, str],
) -> dict[str, object]:
    """以 OS 级 timebox 运行 cell，并区分 timeout、worker failure 与业务结果。"""

    request_id = f"1m-budget-{variant}-{case_name}-{repetition}"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        variant,
        case_name,
        str(repetition),
    ]
    started = perf_counter()
    try:
        completed = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=REAL_CELL_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # 独立进程由 OS 回收，主 harness 可以继续后续 cell；不创建虚假 Trace ID。
        return {
            "case": case_name,
            "variant": variant,
            "repetition": repetition,
            "request_id": request_id,
            "status": "timeout",
            "exception_type": "TimeoutExpired",
            "timeout_seconds": REAL_CELL_TIMEOUT_SECONDS,
            "wall_clock_ms": round((perf_counter() - started) * 1000, 3),
        }

    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    if completed.returncode == 0 and lines:
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            pass
    # worker 没有形成 typed row 时保留进程层失败，不把 stderr/raw provider text 带进报告。
    return {
        "case": case_name,
        "variant": variant,
        "repetition": repetition,
        "request_id": request_id,
        "status": "worker_failure",
        "exception_type": "WorkerProcessError",
        "returncode": completed.returncode,
        "wall_clock_ms": round((perf_counter() - started) * 1000, 3),
    }


def _run_all() -> None:
    """按 variant→case→repetition 完成全部 36 个 OS-isolated cells。"""

    settings = load_settings()
    if (settings.provider, settings.model_name) != ("opencode-go", "deepseek-v4-flash"):
        raise RuntimeError(
            "real 1M experiment requires the verified opencode-go/deepseek-v4-flash pair"
        )
    print(
        json.dumps(
            {
                "status": "preflight",
                "provider": settings.provider,
                "model": settings.model_name,
                "expected_context_source": "verified_model_registry",
                "variants": tuple(VARIANTS),
                "cells": len(CASES) * len(VARIANTS) * 3,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )

    for variant in VARIANTS:
        mode, run_budget = VARIANTS[variant]
        environment = os.environ.copy()
        _set_budget_environment(mode, run_budget)
        environment.update(os.environ)
        for case_name in CASES:
            for repetition in range(1, 4):
                row = _run_cell_in_worker(variant, case_name, repetition, environment)
                print(json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)


def main() -> None:
    """加载当前 `.env` 后运行真实 provider 实验；不打印 API key。"""

    load_environment_file(Path(".env"))
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        _worker_main(sys.argv[2], sys.argv[3], int(sys.argv[4]))
        return
    _run_all()


if __name__ == "__main__":
    main()
