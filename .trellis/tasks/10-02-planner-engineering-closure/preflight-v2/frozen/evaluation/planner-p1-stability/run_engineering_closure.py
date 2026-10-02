"""当前生产 Standard/Planned 的最后一次有界 E2E；不继续 effort 研究。"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import subprocess
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx2 as httpx
from run_frozen_plan_replay import snapshot_content, without_guidance
from run_p1_e2e import HTTPRecorder, append_json, frozen_files, usage_for
from run_p1_low_none import write_json
from run_planner_only import CASE_IDS, ROOT, load_cases

from trivae.bootstrap.application import create_application
from trivae.capabilities import GetMessageContextInput
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import DEFAULT_DEEPSEEK_BASE_URL, load_router_jev_settings, load_settings
from trivae.conversation.sqlite import SQLiteConversationStore
from trivae.evaluation.benchmark.gt import build_case_ground_truth
from trivae.evaluation.benchmark.metrics import evaluate_end_to_end_case
from trivae.evaluation.contracts import EvaluationCaseBundle, utc_now
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.store import SQLiteEvaluationStore
from trivae.evaluation.variant import ControlledVariant, variant_diff
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.planner import SoftPlanner, render_plan_guidance
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter, _RunState

TREATMENTS = ("standard", "planned")


class ProductionPlanner:
    """仅观测生产 SoftPlanner 的调用次数/结果，不改变输入、输出或 completion。"""

    def __init__(self, planner: SoftPlanner) -> None:
        self.planner = planner
        self.calls = 0
        self.result: Any = None

    async def plan(self, context: Any) -> Any:
        # 每次真实 Orchestrator 调用递增，Standard 应完全不进入此函数。
        self.calls += 1
        # 原样调用生产 P1 + none，并保留 observation/失败，不生成实验 Plan。
        self.result = await self.planner.plan(context)
        return self.result


def schedule(seed: int) -> list[dict[str, Any]]:
    """八个相邻配对、交替 AB/BA，每侧恰好一次；没有 repeats 参数。"""
    initial = random.Random(seed).randrange(2)
    return [{"order": 2 * i + j + 1, "case_id": case, "treatment": treatment, "attempt": 1}
        for i, case in enumerate(CASE_IDS)
        for j, treatment in enumerate(TREATMENTS if (i + initial) % 2 == 0 else TREATMENTS[::-1])]


def code_identity(cases: list[EvaluationCaseBundle]) -> dict[str, bytes]:
    """沿用历史逐字冻结，并补齐本入口及其 helper/真实 regression 身份。"""
    files = frozen_files(cases)
    for path in (Path(__file__), Path(__file__).with_name("run_frozen_plan_replay.py"),
                 Path(__file__).with_name("run_p1_e2e.py"), ROOT / "evaluation/regressions/archify-temporal-relation.json"):
        files[str(path.relative_to(ROOT))] = path.read_bytes()
    return files


def runtime_projection(runtime: OpenAIAgentsRuntimeAdapter, request: QueryRequest) -> dict[str, Any]:
    """读取真实生产 Agent builder；route 不进入模型提示，没有 Provider 调用。"""
    req = request.to_runtime_request()
    agent = runtime._build_agent(req, runtime._build_context(req), _RunState(provider="deepseek", model="deepseek-flash"))
    return {"instructions": agent.instructions(None, agent), "input": runtime._build_input(req),
        "model_settings": agent.model_settings.to_json_dict(),
        "tools": [{"name": t.name, "description": t.description, "parameters": t.params_json_schema,
            "strict": t.strict_json_schema} for t in agent.tools]}


async def serialize_planner(runtime: OpenAIAgentsRuntimeAdapter, prompt: str) -> dict[str, Any]:
    """只预检当前生产 none 请求；MockTransport 阻断任何付费请求。"""
    client = runtime._provider_client._client
    transport, mounts = client._transport, client._mounts
    body: dict[str, Any] = {}

    async def fake(request: httpx.Request) -> httpx.Response:
        body.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "preflight", "object": "chat.completion", "created": 0,
            "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "{}"}}]})
    client._transport, client._mounts = httpx.MockTransport(fake), {}
    try:
        # 使用与生产 Application 默认注入完全相同的 completion 方法。
        await runtime.complete_planner_text_with_observation(prompt)
    finally:
        client._transport, client._mounts = transport, mounts
    if body["reasoning_effort"] != "none" or body["max_tokens"] != 2048:
        raise ValueError("production Planner identity drift")
    return body


def verify_initial_requests(standard: dict[str, Any], planned: dict[str, Any], guidance: str | None) -> None:
    """真实 HTTP 对照只允许 production renderer 追加的 guidance 变化。"""
    normalized = planned if guidance is None else without_guidance(planned, guidance)
    if normalized != standard:
        raise ValueError("actual first Runtime requests differ beyond rendered Planner guidance")


async def execute(output: Path, database: Path, seed: int, preflight_only: bool = False) -> None:
    """固定 16 次，任何 preflight 错误落盘为零请求；不补跑、不覆盖目录。"""
    output.mkdir(parents=True, exist_ok=False)
    for name in ("raw", "traces", "answers", "evaluation", "frozen"):
        (output / name).mkdir()
    app = None
    recorder = HTTPRecorder(output / "raw")
    attempts = 0
    try:
        load_environment_file()
        settings = load_settings()
        if (settings.provider, settings.model_name, settings.completion_max_tokens) != ("deepseek", "deepseek-flash", 2048):
            raise ValueError("requires current official DeepSeek Flash production identity")
        if settings.base_url.rstrip("/") != DEFAULT_DEEPSEEK_BASE_URL:
            raise ValueError("requires official DeepSeek endpoint")
        cases = [EvaluationCaseBundle.from_json(ROOT / str(e["source"])) for e in load_cases()]
        runtime = OpenAIAgentsRuntimeAdapter(settings=settings)
        traces = SQLiteTraceStore(output / "trace.sqlite3")
        store = SQLiteEvaluationStore(output / "evaluation.sqlite3")
        app = create_application(database, agent_runtime=runtime, trace_store=traces,
            conversation_store=SQLiteConversationStore(output / "conversation.sqlite3"), evaluation_store=store,
            feedback_database_path=output / "feedback.sqlite3")
        runtime.capability_registry = app.capability_registry
        # 与 Application 默认生产构造器一致；wrapper 仅捕获调用事实。
        planner = ProductionPlanner(SoftPlanner(runtime.complete_planner_text_with_observation,
            completion_request=runtime.planner_completion_request_projection(),
            capability_metadata=app.capability_registry.metadata()))
        app._planner = planner
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
        snapshot = app.materialize_evaluation_snapshot()
        if any(c.dataset_snapshot.deterministic_fingerprint != snapshot.deterministic_fingerprint for c in cases):
            raise ValueError("canonical snapshot drift")
        frozen = code_identity(cases)
        order = schedule(seed)
        variants = {t: ControlledVariant(variant_id=f"closure-{t}", code_version=commit,
            provider=settings.provider, model=settings.model_name, prompt_identity="production-P1/Runtime",
            planner_configuration={"reasoning_effort": "none"}, runtime_configuration={k: v for k, v in settings.to_safe_dict().items() if k != "api_key_configured"},
            available_tools=QueryRequest(query="preflight", scope=cases[0].data_access_scope).available_capabilities,
            index_identity=json.dumps(snapshot.manifest["lexical_index"], sort_keys=True),
            execution_override=ExecutionOverride(forced_route=f"{t}_execution")) for t in TREATMENTS}
        preflight_cases = []
        for case in cases:
            truth = build_case_ground_truth(case)
            # 已存在的人工 GT 不修改；所有 benchmark gt finding 必须已 adjudicated。
            if any(not f.provenance.adjudicated for f in case.reference_findings if f.criterion.startswith("gt.")):
                raise ValueError(f"unadjudicated GT: {case.identity}")
            canonical_targets = []
            for message_id in truth.evidence_target_ids:
                envelope = app.invoke_tool("get_message_context", GetMessageContextInput(message_id,
                    context_before=0, context_after=0), case.data_access_scope)
                if envelope.error is not None or envelope.data is None:
                    raise ValueError(f"GT source unavailable: {case.identity} {message_id}: {envelope.error}")
                canonical_targets.extend(asdict(m) for m in envelope.data.messages)
            requests = {t: QueryRequest(query=case.query, scope=case.data_access_scope, locale=case.locale,
                data_snapshot={"snapshot_id": case.dataset_snapshot.snapshot_id, "schema_version": case.dataset_snapshot.schema_version,
                    "message_count": case.dataset_snapshot.message_count, "relevant_time_range": list(case.dataset_snapshot.relevant_time_range),
                    "evaluation_case": case.identity, "repetition": 0}, trace_profile="debug",
                available_capabilities=variants[t].available_tools, execution_override=variants[t].execution_override) for t in TREATMENTS}
            projections = {t: runtime_projection(runtime, requests[t]) for t in TREATMENTS}
            if projections["standard"] != projections["planned"]:
                raise ValueError("preset Runtime inputs differ")
            if projections["standard"]["model_settings"]["reasoning"]["effort"] != "low":
                raise ValueError("Runtime reasoning drift")
            prompt = planner.planner._build_prompt(requests["planned"].to_context(), planner.planner._capability_summaries)
            body = await serialize_planner(runtime, prompt)
            preflight_cases.append({"case": case.to_dict(), "ground_truth": asdict(truth),
                "canonical_gt_targets": canonical_targets, "application_requests": {t: asdict(r) for t, r in requests.items()},
                "runtime": projections["standard"], "planner_prompt": prompt, "serialized_planner": body})
        if runtime.completion_request_projection()["reasoning_effort"] != "low" or runtime._provider_client.max_retries != 0:
            raise ValueError("Router identity or provider retry drift")
        router = load_router_jev_settings()
        write_json(output / "preflight.json", {"passed": True, "network_requests": 0, "formal_attempts": 0,
            "treatment": "only forced route/one production Planner call and its guidance differ",
            "planner_calls": {"standard": 0, "planned": 1}, "cases": preflight_cases,
            "variant_diff": variant_diff(variants["standard"], variants["planned"]),
            "router": {"reasoning_effort": "low", "jev_enabled": router.enabled, "mode": router.mode,
                "experiment_router_calls": 0}, "credential_configured": settings.to_safe_dict()["api_key_configured"],
            "evaluation": "existing EvaluationRunner + benchmark GT/metrics + root source audit; no paid Judge",
            "sdk_retries": 0, "planner_timeout_seconds": planner.planner.completion_timeout_seconds,
            "semantic_index": asdict(app.semantic_index_status())})
        write_json(output / "manifest.json", {"execution_commit": commit, "git_status": dirty, "created_at": utc_now(),
            "snapshot": snapshot.to_dict(), "settings": settings.to_safe_dict(), "case_ids": list(CASE_IDS),
            "case_identities": [c.identity for c in cases], "planner": runtime.planner_completion_request_projection(),
            "router": runtime.completion_request_projection(), "logical_runs": 16,
            "monetary_cost": "unavailable", "repeat_policy": "none scheduled; new serious single-case failure only permits 2+2",
            "cache": "production prefix cache retained; fresh conversations; preloaded semantic embedding"})
        write_json(output / "variants.json", {t: v.to_dict() for t, v in variants.items()})
        write_json(output / "run_order.json", {"seed": seed, "order": order})
        (output / "execution.diff").write_text(subprocess.check_output(["git", "diff"], cwd=ROOT, text=True))
        for relative, content in frozen.items():
            path = output / "frozen" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        # 先检查本地 semantic 依赖并预热，再允许打开真实 HTTP recorder/开始正式 attempt。
        started = perf_counter()
        app.semantic_provider.preload()
        write_json(output / "warmup.json", {"duration_ms": (perf_counter() - started) * 1000, "provider_requests": 0})
        if preflight_only:
            return
        runtime._provider_client._client.event_hooks = {"request": [recorder.request], "response": [recorder.response]}
        results: dict[str, Any] = {}

        async def query(request: QueryRequest) -> Any:
            # EvaluationRunner 的每条请求都新建 conversation，不能沿用上一 treatment 历史。
            if request.conversation_id is not None or request.prior_context:
                raise ValueError("conversation isolation violated")
            result = await app.query(request)
            results[request.request_id] = result
            return result

        runner = EvaluationRunner(query_executor=query, trace_reader=app.read_trace, store=store,
            snapshot_resolver=app.materialize_evaluation_snapshot)
        runs = []
        initial_bodies: dict[str, dict[str, Any]] = {}
        guidance_by_case: dict[str, str | None] = {}
        for item in order:
            # 每次开始前校验完整字节身份与 snapshot，不掩盖中途数据漂移。
            if code_identity(cases) != frozen or snapshot_content(app.materialize_evaluation_snapshot().to_dict()) != snapshot_content(snapshot.to_dict()):
                raise ValueError("code/case/snapshot drift during formal execution")
            append_json(output / "attempts.jsonl", {**item, "started_at": utc_now()})
            attempts += 1
            recorder.active = dict(item)
            first, calls = len(recorder.requests), planner.calls
            planner.result = None
            case = next(c for c in cases if c.case_id == item["case_id"])
            started, exception = perf_counter(), None
            try:
                run = (await runner.run_case(case, variants[item["treatment"]], suite_id="final-engineering-closure"))[0]
            except Exception as exc:
                # 已有 Runner 保存失败；本入口同时保存原因，继续固定 schedule，不补跑。
                exception = {"type": type(exc).__name__, "message": runtime._redact(str(exc))}
                matching = store.list_runs(case_id=case.case_id)
                if not matching:
                    raise
                run = matching[-1]
            elapsed = (perf_counter() - started) * 1000
            result = results.get(run.query_request_id)
            requests = recorder.records(first)
            planned = item["treatment"] == "planned"
            planner_count = int(planned)
            trace = None if run.trace_id is None else traces.read_trace(run.trace_id)
            row = {**item, "execution_commit": commit, "run_id": run.run_id, "trace_id": run.trace_id,
                "snapshot_id": run.snapshot_id, "wall_clock_ms": elapsed, "exception": exception,
                "planner_calls": planner.calls - calls,
                "planner": None if planner.result is None else asdict(planner.result),
                "rendered_guidance": None if planner.result is None or planner.result.plan is None else render_plan_guidance(planner.result.plan),
                "evaluation_run": run.to_dict(), "provider_requests": requests,
                "usage": {"planner": usage_for(requests[:planner_count]), "runtime": usage_for(requests[planner_count:]), "total": usage_for(requests)},
                "query_result": None if result is None else asdict(result),
                "answer_artifact": None if result is None or result.answer_artifact is None else asdict(result.answer_artifact),
                "final_answer": None if result is None else result.final_answer,
                "automatic_evaluation": evaluate_end_to_end_case(build_case_ground_truth(case), run.query_result,
                    operational_measurements=run.operational_measurements)}
            name = f"{case.case_id}-{item['treatment']}"
            write_json(output / "raw" / f"{name}.json", row)
            write_json(output / "traces" / f"{name}.json", [] if trace is None else [e.to_row() for e in trace.events])
            write_json(output / "answers" / f"{name}.json", row["answer_artifact"])
            write_json(output / "evaluation" / f"{name}.json", row["automatic_evaluation"])
            append_json(output / "runs.jsonl", row)
            runs.append(row)
            # 正式 run 已落盘后核验调用 ownership，异常不能伪装成成功完成。
            if row["planner_calls"] != planner_count:
                raise ValueError("production Planner call count violated")
            planner_http = [r for r in requests if not r["serialized_request"].get("stream", False)]
            downstream = [r for r in requests if r["serialized_request"].get("stream", False)]
            if len(planner_http) != planner_count or any(r["serialized_request"]["reasoning_effort"] != "none" for r in planner_http):
                raise ValueError("actual Planner HTTP identity violated")
            if any(r["serialized_request"]["reasoning_effort"] != "low" for r in downstream):
                raise ValueError("actual Runtime reasoning violated")
            if downstream:
                initial_bodies[name] = downstream[0]["serialized_request"]
                if planned:
                    guidance_by_case[case.case_id] = row["rendered_guidance"]
                std_key, plan_key = f"{case.case_id}-standard", f"{case.case_id}-planned"
                if std_key in initial_bodies and plan_key in initial_bodies:
                    verify_initial_requests(initial_bodies[std_key], initial_bodies[plan_key], guidance_by_case[case.case_id])
            print(f"{item['order']}/16 {name}: {run.terminal_status}; HTTP={len(requests)}; wall={elapsed/1000:.2f}s", flush=True)
        write_json(output / "integrity.json", {"logical_runs": len(runs), "actual_provider_requests": len(recorder.requests),
            "provider_responses": len(recorder.responses), "planner_http": planner.calls, "retry_count": 0,
            "first_runtime_pair_checks": len(guidance_by_case), "code_and_cases_unchanged": code_identity(cases) == frozen,
            "snapshot_unchanged": snapshot_content(app.materialize_evaluation_snapshot().to_dict()) == snapshot_content(snapshot.to_dict())})
    except Exception as exc:
        # 预检失败和正式失败分别显式记录，保留全部已发生请求；不自动续跑。
        write_json(output / "failure.json", {"type": type(exc).__name__, "message": str(exc),
            "formal_attempts": attempts, "provider_calls": len(recorder.requests), "preflight_failure": attempts == 0})
        raise
    finally:
        if app is not None:
            await app.aclose()


def main() -> None:
    """没有扩样或 repeat 开关；一次命令只执行一个固定 create-only batch。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=ROOT / "data/trivae.sqlite3")
    parser.add_argument("--seed", type=int, default=20261004)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(execute(args.output, args.database, args.seed, args.preflight_only))


if __name__ == "__main__":
    main()
