"""在真实 Provider 上运行固定 prompt 的 paired budget 实验。

本 runner 只改变评测 harness 的时间边界和观测投影，不改变 Trivae 产品预算、prompt
或 Case。每个 cell 使用独立 worker，避免被杀死的 Provider 调用污染后续样本。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import cast

from trivae.bootstrap.application import TrivaeApplication, create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.evaluation.checks import operational_measurements, query_result_snapshot
from trivae.evaluation.contracts import EvaluationRun
from trivae.evaluation.review import build_review_packet
from trivae.observability.contracts import TraceProjection
from trivae.query.contracts import QueryRequest, QueryResult

CASES = {
    "github_skills_resources": "最近的这一个月之内，有没有讨论过一些有价值的 GitHub 仓库、Skills、有价值的一些资源之类的东西",
    "agent_learning_materials": "最近一个月群里推荐过哪些 Agent 学习资料？",
    "taste_skill": "群里对 taste-skill 的评价是什么？有没有人实际用过？",
    "deepseek_projects": "最近两周讨论过哪些 DeepSeek 相关项目？",
}


@dataclass(frozen=True)
class VariantSpec:
    """实验 variant 的唯一可变维度；prompt、Case 和 Provider 不放在这里。"""

    mode: str
    run_budget: int | None
    uses_default_run_pool: bool


VARIANTS = {
    # fixed 保留历史 16k 行为，作为回答质量的 baseline。
    "fixed-16k": VariantSpec("fixed", None, False),
    # dynamic128 只显式约束 run-level pool，per-call ceiling 保持 128k。
    "dynamic-run-128k": VariantSpec("dynamic", 128_000, False),
    # default variant 故意不设置 run-level override，验证 1M context 的产品默认解析。
    "dynamic-default-250k": VariantSpec("dynamic", None, True),
}

REAL_CELL_TIMEOUT_SECONDS = 120.0
REAL_EXPERIMENT_TIMEOUT_SECONDS = 75 * 60.0
RUN_REQUEST_PREFIX = "1m-paired-v2"
REVIEW_RUBRIC_VERSION = "m7-v1"
EXPECTED_PROVIDER = "opencode-go"
EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_CONTEXT_WINDOW = 1_000_000
EXPECTED_FIXED_BUDGET = 16_000
EXPECTED_PER_CALL_BUDGET = 128_000
EXPECTED_DEFAULT_RUN_BUDGET = 250_000


def _request_id(variant: str, case_name: str, repetition: int) -> str:
    """生成可在 SQLite Trace 中精确查找的稳定 request identity。"""

    # variant/case/repetition 均来自本文件固定枚举，避免把任意 shell 文本拼进 identity。
    return f"{RUN_REQUEST_PREFIX}-{variant}-{case_name}-r{repetition}"


def _apply_budget_environment(environment: dict[str, str], spec: VariantSpec) -> None:
    """为一个 worker 写入完整预算环境，清除上一个 variant 可能遗留的 override。"""

    # mode 是本轮唯一的 per-call budget 对照变量。
    environment["TRIVAE_TOOL_RESULT_BUDGET_MODE"] = spec.mode
    # 维持归档实验的 128k per-call ceiling，不让 run pool 实验同时改变 per-call 条件。
    environment["TRIVAE_PER_CALL_TOOL_RESULT_PERCENT"] = "50"
    environment["TRIVAE_PER_CALL_TOOL_RESULT_CAP"] = str(EXPECTED_PER_CALL_BUDGET)
    # 维持 1M default run pool 的 percent/cap 配置，只有显式 variant 才提供 budget override。
    environment["TRIVAE_RUN_TOOL_EVIDENCE_PERCENT"] = "25"
    environment["TRIVAE_RUN_TOOL_EVIDENCE_CAP"] = "256000"
    # 删除显式 context，让 verified model registry 提供 1M，而不是实验脚本硬编码 context。
    environment.pop("TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS", None)
    # fixed 与 default dynamic 都不能继承上一 variant 的显式 run budget。
    environment.pop("TRIVAE_RUN_TOOL_EVIDENCE_BUDGET", None)
    if spec.run_budget is not None:
        # 128k variant 明确设置 shared run-level pool，便于和默认 250k 配对比较。
        environment["TRIVAE_RUN_TOOL_EVIDENCE_BUDGET"] = str(spec.run_budget)


def _trace_facts(trace: TraceProjection | None) -> dict[str, object]:
    """读取 Trace 的 bounded operational facts，不复制回答正文或 Provider raw object。"""

    if trace is None:
        # 没有 Trace identity 时显式报告不可用，不能把 QueryResult 状态当作完整证据。
        return {"trace_available": False}
    budget_snapshots: list[dict[str, object]] = []
    finalization_events: list[dict[str, object]] = []
    retrieval_events: list[dict[str, object]] = []
    for item in trace.timeline:
        # 每个 runtime.tool.completed 的 snapshot 是产品实际采用的 budget resolution。
        raw_budget = item.payload.get("tool_result_budget")
        if item.operation == "runtime.tool.completed" and isinstance(raw_budget, Mapping):
            budget_snapshots.append(dict(raw_budget))
        # 只保留 finalization 状态/计数，禁止把 debug payload 中的 answer_text 带出。
        if item.operation == "answer.finalization.completed":
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
            finalization_events.append(
                {key: item.payload[key] for key in allowed_keys if key in item.payload}
            )
        # Retrieval payload 只取计数、coverage 和延迟，足以复核 Retriever→canonical 的链路。
        if item.operation == "retrieval.search.completed":
            fields = (
                "strategy",
                "total_hits",
                "candidate_count",
                "returned_messages",
                "partial",
                "truncated",
                "coverage",
                "latency_ms",
            )
            retrieval_events.append({key: item.payload[key] for key in fields if key in item.payload})
    # 这些 aggregate 只做计数汇总，具体每次 Retriever operation 仍保留在 retrieval_events 中。
    retrieval_total_hits = sum(
        value
        for event in retrieval_events
        for value in (event.get("total_hits"),)
        if isinstance(value, int) and not isinstance(value, bool)
    )
    retrieval_candidate_count = sum(
        value
        for event in retrieval_events
        for value in (event.get("candidate_count"),)
        if isinstance(value, int) and not isinstance(value, bool)
    )
    retrieval_returned_messages = sum(
        value
        for event in retrieval_events
        for value in (event.get("returned_messages"),)
        if isinstance(value, int) and not isinstance(value, bool)
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
        "retrieval_events": tuple(retrieval_events),
        "retrieval_total_hits": retrieval_total_hits,
        "retrieval_candidate_count": retrieval_candidate_count,
        "retrieval_returned_messages": retrieval_returned_messages,
        "retrieval_partial": any(event.get("partial") is True for event in retrieval_events),
        "retrieval_truncated": any(event.get("truncated") is True for event in retrieval_events),
        "finalization_events": tuple(finalization_events),
    }


def _projection_facts(result: QueryResult) -> dict[str, object]:
    """从 QueryResult 的现有 bounded records 计算 canonical 与 model-visible 数量。"""

    # 这里使用公开 RuntimeResult/ToolResultRecord，不重新运行预算算法，也不读数据库正文。
    runtime_result = result.runtime_result
    calls = runtime_result.tool_calls
    records = {record.tool_call_id: record for record in runtime_result.tool_results}
    per_call: list[dict[str, object]] = []
    canonical_message_count = 0
    canonical_structured_count = 0
    model_visible_message_count = 0
    model_visible_structured_count = 0
    omitted_context_messages = 0
    omitted_hit_messages = 0
    projection_consistent = True
    for call in calls:
        # 缺少 record 是 Trace/Runtime identity 问题，保留 unavailable 而不是猜测 canonical 数量。
        tool_call_id = call.tool_call_id
        if tool_call_id is None:
            # Runtime contract 允许缺少 local id；此时不能把其他 record 错配给当前 call。
            record = None
        else:
            record = records.get(tool_call_id)
        if record is None:
            per_call.append(
                {
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.name,
                    "canonical_message_count": None,
                    "canonical_structured_count": None,
                    "model_visible_message_count": None,
                    "model_visible_structured_count": None,
                    "projection_count_status": "record_unavailable",
                }
            )
            projection_consistent = False
            continue
        # canonical count 是 ToolResultRecord 已保留的 message/structured item 数量。
        canonical_messages = len(record.message_items)
        canonical_structured = len(record.structured_items)
        omitted_context = call.model_result_omitted_context_messages or 0
        omitted_hit = call.model_result_omitted_hit_messages or 0
        omitted_messages = omitted_context + omitted_hit
        visible_messages = canonical_messages - omitted_messages
        # 若 omission 大于 canonical，直接标记 invariant violation，不能用 max(0) 掩盖实现问题。
        count_status = "passed" if visible_messages >= 0 else "invariant_violation"
        if visible_messages < 0:
            projection_consistent = False
        canonical_message_count += canonical_messages
        canonical_structured_count += canonical_structured
        model_visible_message_count += visible_messages
        model_visible_structured_count += canonical_structured
        omitted_context_messages += omitted_context
        omitted_hit_messages += omitted_hit
        per_call.append(
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.name,
                "round": call.round,
                "canonical_message_count": canonical_messages,
                "canonical_structured_count": canonical_structured,
                "model_visible_message_count": visible_messages,
                "model_visible_structured_count": canonical_structured,
                "omitted_context_messages": omitted_context,
                "omitted_hit_messages": omitted_hit,
                "projection_truncated": call.model_result_truncated,
                "projection_count_status": count_status,
            }
        )
    return {
        "canonical_message_count": canonical_message_count,
        "canonical_structured_count": canonical_structured_count,
        "canonical_source_count": canonical_message_count + canonical_structured_count,
        "model_visible_message_count": model_visible_message_count,
        "model_visible_structured_count": model_visible_structured_count,
        "model_visible_source_count": model_visible_message_count + model_visible_structured_count,
        "omitted_context_messages": omitted_context_messages,
        "omitted_hit_messages": omitted_hit_messages,
        "projection_consistent": projection_consistent,
        "per_call_projection": tuple(per_call),
    }


def _budget_resolution_status(variant: str, snapshots: object) -> str:
    """验证 Trace 实际解析的 budget 是否符合 variant，不把标签当成事实。"""

    if not isinstance(snapshots, (tuple, list)) or not snapshots:
        # 没有 tool call 时没有 budget snapshot；这是 unavailable，不等同于通过或失败。
        return "not_observed"
    spec = VARIANTS[variant]
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            return "failed"
        if spec.mode == "fixed":
            # fixed compatibility path 不解析 model context；其 context source 正确地是 not_used。
            if snapshot.get("context_window_tokens") is not None:
                return "failed"
            if snapshot.get("context_window_source") != "not_used":
                return "failed"
            if snapshot.get("budget_mode") != "fixed":
                return "failed"
            if snapshot.get("effective_per_call_tool_result_budget") != EXPECTED_FIXED_BUDGET:
                return "failed"
            if snapshot.get("per_call_tool_result_ceiling") != EXPECTED_FIXED_BUDGET:
                return "failed"
            continue
        # dynamic path 必须来自 verified 1M registry，而不是脚本注入的 context window。
        if snapshot.get("context_window_tokens") != EXPECTED_CONTEXT_WINDOW:
            return "failed"
        if snapshot.get("context_window_source") != "verified_model_registry":
            return "failed"
        if snapshot.get("budget_mode") != "dynamic":
            return "failed"
        # shared run pool 消耗后 effective budget 可以小于 ceiling；只校验边界，不误报正常收紧。
        if snapshot.get("per_call_tool_result_ceiling") != EXPECTED_PER_CALL_BUDGET:
            return "failed"
        effective_budget = snapshot.get("effective_per_call_tool_result_budget")
        if not isinstance(effective_budget, int) or isinstance(effective_budget, bool):
            return "failed"
        if not 0 < effective_budget <= EXPECTED_PER_CALL_BUDGET:
            return "failed"
        expected_run_budget = spec.run_budget or EXPECTED_DEFAULT_RUN_BUDGET
        if snapshot.get("run_tool_evidence_budget") != expected_run_budget:
            return "failed"
    return "passed"


def _quality_file_name(variant: str, case_name: str, repetition: int) -> str:
    """固定枚举拼接为可读文件名，不引入 hash 或不可复核的指纹。"""

    return f"{variant}--{case_name}--r{repetition}.json"


def _write_review_packet(
    *,
    quality_dir: Path,
    request_id: str,
    case_name: str,
    prompt: str,
    variant: str,
    repetition: int,
    result: QueryResult,
    measurements: Mapping[str, object],
) -> str:
    """使用现有 ReviewPacket builder 写入本地人工复核材料，摘要不携带 answer_text。"""

    # ReviewPacket builder 只读取 run_id；cast 保留现有接口，同时避免伪造完整 EvaluationRun。
    packet = build_review_packet(
        run=cast(EvaluationRun, SimpleNamespace(run_id=request_id)),
        query=prompt,
        result=result,
        rubric_version=REVIEW_RUBRIC_VERSION,
    )
    # quality_dir 明确由 parent 创建在 /tmp，原始答案只用于本地人工比较，不进入 git report。
    quality_dir.mkdir(parents=True, exist_ok=True)
    output_path = quality_dir / _quality_file_name(variant, case_name, repetition)
    payload = {
        "case": case_name,
        "variant": variant,
        "repetition": repetition,
        "request_id": request_id,
        "trace_id": result.trace_id,
        "review_packet": packet.to_dict(),
        "operational_measurements": dict(measurements),
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return str(output_path)


async def _run_one(
    application: TrivaeApplication,
    case_name: str,
    prompt: str,
    variant: str,
    repetition: int,
    quality_dir: Path,
) -> dict[str, object]:
    """执行一个 cell，保留 Query/Trace/Review 的显式失败边界。"""

    request_id = _request_id(variant, case_name, repetition)
    started = perf_counter()
    try:
        # 所有 variant 复用同一个 Application-level query 入口，确保 prompt/scope/Provider 条件一致。
        try:
            result = await application.query(
                QueryRequest(
                    prompt,
                    ExecutionScope(),
                    request_id=request_id,
                    trace_profile="debug",
                )
            )
        except Exception as exc:
            # Query executor 自身抛出的 Provider/runtime 异常单独分类，不伪造 QueryResult。
            return {
                "case": case_name,
                "variant": variant,
                "repetition": repetition,
                "request_id": request_id,
                "status": "runtime_exception",
                "quality_eligible": False,
                "exception_type": type(exc).__name__,
                "exception_module": type(exc).__module__,
                "wall_clock_ms": round((perf_counter() - started) * 1000, 3),
            }
        # Query 返回后只读取一次同一个 Trace，保证所有 operational projection 观察的是同一快照。
        trace = None
        if result.trace_id is not None:
            try:
                trace = application.read_trace(result.trace_id)
            except Exception as exc:
                # Trace 读取失败不丢弃 Query identity，但该 cell 不能成为可复核质量样本。
                return {
                    "case": case_name,
                    "variant": variant,
                    "repetition": repetition,
                    "request_id": request_id,
                    "trace_id": result.trace_id,
                    "status": "trace_read_failure",
                    "quality_eligible": False,
                    "exception_type": type(exc).__name__,
                    "exception_module": type(exc).__module__,
                    "wall_clock_ms": round((perf_counter() - started) * 1000, 3),
                }
        trace_facts = _trace_facts(trace)
        measurements = operational_measurements(result, trace)
        snapshot = query_result_snapshot(result)
        projection = _projection_facts(result)
        budget_status = _budget_resolution_status(variant, trace_facts.get("budget_snapshots", ()))
        # runtime 非 completed 或没有 validated Artifact 时，finalization 只能记为 not_run。
        finalization_status = (
            result.finalization_status
            if result.finalization_error is None and result.is_successful
            else "failed"
            if result.finalization_error is not None
            else "not_run"
        )
        row: dict[str, object] = {
            "case": case_name,
            "variant": variant,
            "repetition": repetition,
            "request_id": request_id,
            "trace_id": result.trace_id,
            "status": "completed" if result.is_successful else "runtime_failed",
            "quality_eligible": result.is_successful and budget_status in {"passed", "not_observed"},
            "provider": result.runtime_result.provider,
            "model": result.runtime_result.model,
            "termination": result.runtime_result.termination,
            "execution_status": result.execution_status,
            "finalization_status": finalization_status,
            "is_successful": result.is_successful,
            "is_degraded": result.is_degraded,
            "tool_calls": len(result.runtime_result.tool_calls),
            "tool_rounds": result.runtime_result.tool_rounds,
            "evidence_records": len(result.runtime_result.tool_results),
            "citation_binding_count": (
                0 if result.answer_artifact is None else len(result.answer_artifact.citation_bindings)
            ),
            "wall_clock_ms": round((perf_counter() - started) * 1000, 3),
            "usage": None
            if result.runtime_result.usage is None
            else dict(result.runtime_result.usage),
            "query_result_snapshot": snapshot,
            "operational_measurements": measurements,
            "projection_facts": projection,
            "budget_resolution_status": budget_status,
            **trace_facts,
        }
        if result.is_successful and result.answer_artifact is not None:
            # 仅 completed sample 写 ReviewPacket；失败 Query 没有可审阅的最终答案。
            try:
                row["quality_material_path"] = _write_review_packet(
                    quality_dir=quality_dir,
                    request_id=request_id,
                    case_name=case_name,
                    prompt=prompt,
                    variant=variant,
                    repetition=repetition,
                    result=result,
                    measurements=measurements,
                )
                row["quality_material_status"] = "written"
            except Exception as exc:
                # ReviewPacket 失败必须显式影响质量资格，但不能抹掉已经完成的 Trace operational facts。
                row["quality_eligible"] = False
                row["quality_material_status"] = "write_failure"
                row["quality_material_exception_type"] = type(exc).__name__
        return row
    except Exception as exc:
        # Provider/Trace/Review 异常都保留类型和 request identity；不把可能含正文的 exception message 写入结果。
        return {
            "case": case_name,
            "variant": variant,
            "repetition": repetition,
            "request_id": request_id,
            "status": "worker_exception",
            "exception_type": type(exc).__name__,
            "exception_module": type(exc).__module__,
            "wall_clock_ms": round((perf_counter() - started) * 1000, 3),
        }


async def _run_worker(variant: str, case_name: str, repetition: int, quality_dir: Path) -> None:
    """在独立 worker 进程中运行一个 cell，并在同一 event loop 内释放 Application。"""

    # worker 只接受 parent 固定枚举的 variant，避免外部参数直接影响预算配置。
    spec = VARIANTS[variant]
    environment = dict(os.environ)
    _apply_budget_environment(environment, spec)
    os.environ.clear()
    os.environ.update(environment)
    # Application 使用已加载的 `.env` 和 worker 的 variant environment 初始化产品链路。
    application = create_application(Path("data/trivae.sqlite3"))
    try:
        row = await _run_one(application, case_name, CASES[case_name], variant, repetition, quality_dir)
        # stdout 只输出 bounded row；ReviewPacket 已经单独写到 quality_dir。
        print(json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)
    finally:
        # 正常完成和显式异常都需要释放 worker 自己创建的 provider/client 资源。
        await application.aclose()


def _worker_main(variant: str, case_name: str, repetition: int, quality_dir: Path) -> None:
    """子进程入口，所有参数均来自 parent 的固定枚举/路径。"""

    asyncio.run(_run_worker(variant, case_name, repetition, quality_dir))


def _run_cell_in_worker(
    variant: str,
    case_name: str,
    repetition: int,
    environment: dict[str, str],
    quality_dir: Path,
    timeout_seconds: float,
    deadline_limited: bool,
) -> dict[str, object]:
    """执行一个 OS-isolated cell，明确区分 cell timeout 与总实验 deadline。"""

    request_id = _request_id(variant, case_name, repetition)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        variant,
        case_name,
        str(repetition),
        "--quality-dir",
        str(quality_dir),
    ]
    started = perf_counter()
    try:
        # timeout 是 parent 计算的剩余 wall-clock，不允许 Provider 无限挂起。
        completed = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # OS 级 worker 被回收；不伪造 result/answer/Trace，后续只通过 request_id 审计 open Trace。
        return {
            "case": case_name,
            "variant": variant,
            "repetition": repetition,
            "request_id": request_id,
            "status": "experiment_timeout" if deadline_limited else "cell_timeout",
            "quality_eligible": False,
            "exception_type": "TimeoutExpired",
            "timeout_seconds": timeout_seconds,
            "wall_clock_ms": round((perf_counter() - started) * 1000, 3),
        }

    # worker 正常 stdout 的最后一行是 JSON row，前面的日志即使存在也不进入报告。
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    if completed.returncode == 0 and lines:
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            # malformed worker output 属于 worker failure，不尝试从 raw output 猜测业务结果。
            pass
    return {
        "case": case_name,
        "variant": variant,
        "repetition": repetition,
        "request_id": request_id,
        "status": "worker_failure",
        "quality_eligible": False,
        "exception_type": "WorkerProcessError",
        "returncode": completed.returncode,
        "stdout_json_line_count": len(lines),
        "stderr_present": bool(completed.stderr.strip()),
        "wall_clock_ms": round((perf_counter() - started) * 1000, 3),
    }


class _SummaryWriter:
    """同时把 bounded inventory 写入 stdout 和可重放的 JSONL 文件。"""

    def __init__(self, path: Path | None) -> None:
        self._handle = None if path is None else path.open("w", encoding="utf-8")

    def emit(self, row: Mapping[str, object]) -> None:
        # 单行 JSON 便于后续按 request_id/case/variant 重放，不保存 answer正文。
        line = json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
        print(line, flush=True)
        if self._handle is not None:
            self._handle.write(line + "\n")
            self._handle.flush()

    def close(self) -> None:
        # parent 完成所有 cell 后关闭自身持有的 summary 文件。
        if self._handle is not None:
            self._handle.close()


def _run_all(
    *,
    cell_timeout_seconds: float,
    experiment_timeout_seconds: float,
    summary_output: Path | None,
    quality_dir: Path,
) -> None:
    """按 variant→case→repetition 执行 36 个 cell，受绝对总 deadline 约束。"""

    # preflight 只读取 Provider/model 名称，不打印任何 credential。
    settings = load_settings()
    if (settings.provider, settings.model_name) != (EXPECTED_PROVIDER, EXPECTED_MODEL):
        raise RuntimeError(
            "real 1M experiment requires the verified opencode-go/deepseek-v4-flash pair"
        )
    if cell_timeout_seconds <= 0 or experiment_timeout_seconds <= 0:
        raise ValueError("time limits must be positive")
    quality_dir.mkdir(parents=True, exist_ok=True)
    writer = _SummaryWriter(summary_output)
    try:
        writer.emit(
            {
                "status": "preflight",
                "request_prefix": RUN_REQUEST_PREFIX,
                "provider": settings.provider,
                "model": settings.model_name,
                "expected_context_source": "verified_model_registry",
                "cell_timeout_seconds": cell_timeout_seconds,
                "experiment_timeout_seconds": experiment_timeout_seconds,
                "variants": tuple(VARIANTS),
                "cases": tuple(CASES),
                "repetitions": 3,
                "cells": len(CASES) * len(VARIANTS) * 3,
                "quality_dir": str(quality_dir),
            }
        )
        # deadline 使用 monotonic clock，避免系统时钟调整延长 Provider 实验。
        deadline = perf_counter() + experiment_timeout_seconds
        base_environment = dict(os.environ)
        for variant, spec in VARIANTS.items():
            # 为每个 variant 构造一次干净 environment，三次 repetition 只共享 immutable 配置。
            environment = dict(base_environment)
            _apply_budget_environment(environment, spec)
            for case_name in CASES:
                for repetition in range(1, 4):
                    remaining = deadline - perf_counter()
                    if remaining <= 0:
                        # 总 deadline 已到，剩余 planned cells 显式入账，不再 spawn worker。
                        writer.emit(
                            {
                                "case": case_name,
                                "variant": variant,
                                "repetition": repetition,
                                "request_id": _request_id(variant, case_name, repetition),
                                "status": "experiment_timeout",
                                "quality_eligible": False,
                                "exception_type": "ExperimentDeadlineExceeded",
                                "timeout_seconds": experiment_timeout_seconds,
                                "wall_clock_ms": 0.0,
                            }
                        )
                        continue
                    # 如果本 cell 受总 deadline 限制，TimeoutExpired 应标记为 experiment_timeout。
                    effective_timeout = min(cell_timeout_seconds, remaining)
                    row = _run_cell_in_worker(
                        variant,
                        case_name,
                        repetition,
                        environment,
                        quality_dir,
                        effective_timeout,
                        remaining <= cell_timeout_seconds,
                    )
                    writer.emit(row)
    finally:
        # 即使某个 parent-level 异常，也关闭 summary 文件并将异常继续暴露给 shell。
        writer.close()


def _parse_args() -> argparse.Namespace:
    """解析 parent/worker 两种入口的显式参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", nargs=3, metavar=("VARIANT", "CASE", "REPETITION"))
    parser.add_argument("--quality-dir", type=Path, default=Path("/tmp/trivae-real-paired-v2-quality"))
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--cell-timeout-seconds", type=float, default=REAL_CELL_TIMEOUT_SECONDS)
    parser.add_argument(
        "--experiment-timeout-seconds",
        type=float,
        default=REAL_EXPERIMENT_TIMEOUT_SECONDS,
    )
    return parser.parse_args()


def main() -> None:
    """加载当前 `.env` 后运行 parent 或单 cell worker，不打印 API key。"""

    # dotenv 只补充当前 shell 未提供的变量，Provider secrets 不进入 stdout。
    load_environment_file(Path(".env"))
    args = _parse_args()
    if args.worker is not None:
        variant, case_name, repetition_text = args.worker
        if variant not in VARIANTS or case_name not in CASES:
            raise ValueError("worker variant/case is not part of the fixed experiment design")
        _worker_main(variant, case_name, int(repetition_text), args.quality_dir)
        return
    _run_all(
        cell_timeout_seconds=args.cell_timeout_seconds,
        experiment_timeout_seconds=args.experiment_timeout_seconds,
        summary_output=args.summary_output,
        quality_dir=args.quality_dir,
    )


if __name__ == "__main__":
    main()
