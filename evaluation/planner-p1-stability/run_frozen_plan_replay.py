"""重放已验证的固定 Plan；只运行生产 Query/Runtime，不重新请求 Planner。"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import subprocess
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

from run_p1_e2e import HTTPRecorder, append_json, frozen_files, usage_for, write_json
from run_planner_only import ROOT

from trivae.bootstrap.application import create_application
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.conversation.sqlite import SQLiteConversationStore
from trivae.evaluation.benchmark.gt import build_case_ground_truth
from trivae.evaluation.benchmark.metrics import evaluate_end_to_end_case
from trivae.evaluation.contracts import EvaluationCaseBundle, utc_now
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.store import SQLiteEvaluationStore
from trivae.evaluation.variant import ControlledVariant
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryContext, QueryRequest
from trivae.query.planner import Plan, PlannerResult, SoftPlanner, render_plan_guidance
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter, _RunState

CASE_ID = "dev-cite-archify"
SOURCE = ROOT / ".trellis/tasks/10-02-planner-low-none-e2e/experiment/planner_reasoning_ab/e2e"


def replay_order(seed: int) -> list[dict[str, Any]]:
    """两块 AB/BA，每份 Plan 各两次；来源标签只存在于实验工件。"""
    first = ("low", "none") if random.Random(seed).randrange(2) == 0 else ("none", "low")
    return [{"case_id": CASE_ID, "order": 2 * block + position + 1,
             "treatment": treatment, "attempt": block + 1}
            for block in range(2) for position, treatment in enumerate(first if block == 0 else first[::-1])]


def load_plan(source: Path, treatment: str, tools: tuple[str, ...]) -> Plan:
    """沿用生产 parser 验证保存的 Plan，不把原 Provider 调用冒充本轮 observation。"""
    row = json.loads((source / "raw" / f"{CASE_ID}-{treatment}-a1.json").read_text())
    if row["case_id"] != CASE_ID or row["treatment"] != treatment or row["planner"]["failure"] is not None:
        raise ValueError("source must contain the original successful Plan")
    # 已解析的 Plan 再经同一契约读取；逐字段确认不能悄悄改变原 guidance。
    payload = row["planner"]["plan"]
    plan = SoftPlanner._parse(json.dumps(payload, ensure_ascii=False), tools)
    if json.loads(json.dumps(asdict(plan))) != payload:
        raise ValueError("saved Plan changed during production parsing")
    return plan


class FrozenPlanner:
    """既有 Planner protocol 注入点：返回固定 Plan，无 completion callback。"""

    def __init__(self, plans: dict[str, Plan]) -> None:
        self.plans = plans
        self.treatment = "low"
        self.calls = 0

    async def plan(self, context: QueryContext) -> PlannerResult:
        """每次生产 Query 调用一次；不创建或访问 Provider client。"""
        self.calls += 1
        return PlannerResult(self.plans[self.treatment])


def without_guidance(body: dict[str, Any], guidance: str) -> dict[str, Any]:
    """只剥离 production renderer 追加的 guidance，比较其余实际序列化字段。"""
    result = deepcopy(body)
    system = result["messages"][0]
    suffix = "\n" + guidance
    # 指定 guidance 必须是 system 末尾的精确文本，不能模糊删除其它 prompt 内容。
    if system["role"] != "system" or not system["content"].endswith(suffix):
        raise ValueError("actual request does not contain the exact frozen guidance")
    system["content"] = system["content"][:-len(suffix)]
    return result


def agent_projection(runtime: OpenAIAgentsRuntimeAdapter, request: QueryRequest, plan: Plan) -> dict[str, Any]:
    """从生产 Agent builder 读取输入/schema/档位，预检不调用网络。"""
    guidance = render_plan_guidance(plan)
    runtime_request = request.to_runtime_request(guidance)
    state = _RunState(provider="deepseek", model="deepseek-flash")
    agent = runtime._build_agent(runtime_request, runtime._build_context(runtime_request), state)
    return {"instructions": agent.instructions(None, agent), "input": runtime._build_input(runtime_request),
            # SDK 的 reasoning 是 Pydantic 对象，必须用其正式 JSON 投影，不能留下不可序列化对象。
            "model_settings": agent.model_settings.to_json_dict(),
            "tools": [{"name": t.name, "description": t.description, "parameters": t.params_json_schema,
                       "strict": t.strict_json_schema} for t in agent.tools]}


def snapshot_content(snapshot: dict[str, Any]) -> dict[str, Any]:
    """materialize 的 created_at 是本次观测时间；其余全部字段才描述被固定的数据。"""
    return {key: value for key, value in snapshot.items() if key != "created_at"}


async def execute(output: Path, source: Path, database: Path, seed: int, preflight_only: bool = False) -> None:
    """执行固定四次，不重试；任何异常和失败都保留原始工件。"""
    output.mkdir(parents=True, exist_ok=False)
    for name in ("raw", "traces", "answers", "evaluation", "frozen"):
        (output / name).mkdir()
    load_environment_file()
    settings = load_settings()
    source_manifest = json.loads((source / "manifest.json").read_text())
    # 本轮必须保持上轮全部 Runtime 设置，不重新选择 Provider/model/预算。
    if settings.to_safe_dict() != source_manifest["settings"]:
        raise ValueError("Runtime settings changed since the original experiment")
    case = EvaluationCaseBundle.from_json(ROOT / "evaluation/cases/benchmark/dev/dev-cite-archify.json")
    original_variants = json.loads((source / "variants.json").read_text())
    tools = tuple(original_variants["low"]["available_tools"])
    plans = {t: load_plan(source, t, tools) for t in ("low", "none")}
    planner = FrozenPlanner(plans)
    runtime = OpenAIAgentsRuntimeAdapter(settings=settings)
    traces = SQLiteTraceStore(output / "trace.sqlite3")
    store = SQLiteEvaluationStore(output / "evaluation.sqlite3")
    app = create_application(database, agent_runtime=runtime, planner=planner, trace_store=traces,
        conversation_store=SQLiteConversationStore(output / "conversation.sqlite3"), evaluation_store=store,
        feedback_database_path=output / "feedback.sqlite3")
    runtime.capability_registry = app.capability_registry
    recorder = HTTPRecorder(output / "raw")
    frozen = frozen_files([case])
    # 新 runner 和两份原始 Plan 文件也逐字冻结；不使用哈希。
    frozen[str(Path(__file__).relative_to(ROOT))] = Path(__file__).read_bytes()
    for t in plans:
        path = source / "raw" / f"{CASE_ID}-{t}-a1.json"
        frozen[str(path.relative_to(ROOT))] = path.read_bytes()

    def verify_frozen() -> None:
        """每次执行前确认代码、Case、源 Plan 与快照没有混入其它改动。"""
        if any((ROOT / path).read_bytes() != content for path, content in frozen.items()):
            raise RuntimeError("frozen code/case/source drift")
        if snapshot_content(app.materialize_evaluation_snapshot().to_dict()) != snapshot_content(source_manifest["snapshot"]):
            raise RuntimeError("snapshot changed since the original experiment")

    try:
        verify_frozen()
        # 上轮生产源码原样保留：不能一边修复引用错误一边重放。
        for path in (source / "frozen/src").rglob("*.py"):
            if path.read_bytes() != (ROOT / "src" / path.relative_to(source / "frozen/src")).read_bytes():
                raise ValueError("production source differs from the original experiment")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        variant = ControlledVariant(variant_id="frozen-plan-replay", code_version=commit,
            provider=settings.provider, model=settings.model_name, prompt_identity="production-P1-frozen-guidance",
            planner_configuration={"mode": "frozen_plan", "provider_requests": 0},
            runtime_configuration=original_variants["low"]["runtime_configuration"], available_tools=tools,
            index_identity=original_variants["low"]["index_identity"],
            execution_override=ExecutionOverride(forced_route="planned_execution"))
        request = QueryRequest(query=case.query, scope=case.data_access_scope, available_capabilities=tools,
            locale=case.locale, trace_profile="debug", execution_override=variant.execution_override)
        projections = {t: agent_projection(runtime, request, p) for t, p in plans.items()}
        normalized = deepcopy(projections)
        for t, p in plans.items():
            suffix = "\n" + render_plan_guidance(p)
            if not normalized[t]["instructions"].endswith(suffix):
                raise ValueError("builder did not append exact guidance")
            normalized[t]["instructions"] = normalized[t]["instructions"][:-len(suffix)]
        if normalized["low"] != normalized["none"]:
            raise ValueError("Agent builder contamination outside frozen guidance")
        write_json(output / "preflight.json", {"passed": True, "network_requests": 0,
            "statement": "唯一 treatment variable 为已保存 Plan 的 rendered guidance；没有 Planner HTTP 请求",
            "agent_projections": projections, "case": case.to_dict(), "source": str(source.relative_to(ROOT))})
        write_json(output / "plans.json", {t: {"plan": asdict(p), "guidance": render_plan_guidance(p)} for t, p in plans.items()})
        order = replay_order(seed)
        write_json(output / "run_order.json", {"seed": seed, "order": order})
        write_json(output / "manifest.json", {"execution_commit": commit,
            "dirty_state": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
            "timestamp": utc_now(), "source_experiment": str(source.relative_to(ROOT)),
            "snapshot": source_manifest["snapshot"], "settings": settings.to_safe_dict(),
            "case_id": CASE_ID, "logical_runs": 4, "planner_provider_requests": 0,
            "sdk_retries": runtime._provider_client.max_retries, "variant": variant.to_dict(),
            "semantic_index": asdict(app.semantic_index_status()), "monetary_cost": "Monetary cost unavailable"})
        if runtime._provider_client.max_retries != 0:
            raise ValueError("replay requires the original no-retry client")
        for relative, content in frozen.items():
            path = output / "frozen" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        if preflight_only:
            return
        warm_started = perf_counter()
        app.semantic_provider.preload()
        write_json(output / "warmup.json", {"duration_ms": (perf_counter() - warm_started) * 1000, "provider_requests": 0})
        runtime._provider_client._client.event_hooks = {"request": [recorder.request], "response": [recorder.response]}
        results: dict[str, Any] = {}

        async def query(req: QueryRequest) -> Any:
            """仅透传生产入口；保存完整 QueryResult，评测仍由既有 Runner 拥有。"""
            result = await app.query(req)
            results[req.request_id] = result
            return result

        runner = EvaluationRunner(query_executor=query, trace_reader=app.read_trace, store=store,
                                  snapshot_resolver=app.materialize_evaluation_snapshot)
        baseline = json.loads((source / "raw" / f"{CASE_ID}-low-a1.json").read_text())
        expected_body = without_guidance(baseline["provider_requests"][1]["serialized_request"], render_plan_guidance(plans["low"]))
        runs = []
        for item in order:
            verify_frozen()
            append_json(output / "attempts.jsonl", {**item, "started_at": utc_now()})
            planner.treatment = item["treatment"]
            recorder.active = dict(item)
            first = len(recorder.requests)
            started = perf_counter()
            exception = None
            try:
                run = (await runner.run_case(case, variant, suite_id="archify-frozen-plan-replay"))[0]
            except Exception as exc:
                # Runner 已保存失败；继续下一预定 attempt，绝不补跑或把异常伪装成成功。
                exception = {"type": type(exc).__name__, "message": runtime._redact(str(exc))}
                matching = store.list_runs(case_id=CASE_ID)
                if not matching:
                    raise
                run = matching[-1]
            elapsed = (perf_counter() - started) * 1000
            result = results.get(run.query_request_id)
            requests = recorder.records(first)
            trace = None if run.trace_id is None else traces.read_trace(run.trace_id)
            row = {**item, "execution_commit": commit, "snapshot_id": run.snapshot_id,
                "started_at": run.started_at, "completed_at": run.completed_at, "exception": exception,
                "run_id": run.run_id, "trace_id": run.trace_id, "wall_clock_ms": elapsed,
                "planner_mode": "frozen_plan_no_provider", "plan": asdict(plans[item["treatment"]]),
                "evaluation_run": run.to_dict(), "provider_requests": requests, "usage": usage_for(requests),
                "query_result": None if result is None else asdict(result),
                "answer_artifact": None if result is None or result.answer_artifact is None else asdict(result.answer_artifact),
                "final_answer": None if result is None else result.final_answer,
                "automatic_evaluation": evaluate_end_to_end_case(build_case_ground_truth(case), run.query_result,
                    operational_measurements=run.operational_measurements)}
            # 先落盘全部事实，再检查真实首个 HTTP 请求；若污染，保留失败证据并停止。
            name = f"{CASE_ID}-{item['treatment']}-r{item['attempt']}"
            write_json(output / "raw" / f"{name}.json", row)
            write_json(output / "traces" / f"{name}.json", [] if trace is None else [e.to_row() for e in trace.events])
            write_json(output / "answers" / f"{name}.json", row["answer_artifact"])
            write_json(output / "evaluation" / f"{name}.json", row["automatic_evaluation"])
            append_json(output / "runs.jsonl", row)
            runs.append(row)
            if requests and without_guidance(requests[0]["serialized_request"], render_plan_guidance(plans[item["treatment"]])) != expected_body:
                raise RuntimeError("actual initial HTTP body differs outside frozen guidance")
            print(f"{item['order']}/4 {name}: {run.terminal_status}; HTTP={len(requests)}; wall={elapsed/1000:.2f}s", flush=True)
        verify_frozen()
        write_json(output / "integrity.json", {"logical_runs": len(runs), "frozen_planner_calls": planner.calls,
            "planner_provider_requests": 0, "actual_provider_requests": len(recorder.requests),
            "provider_responses": len(recorder.responses), "retry_count": 0,
            "actual_initial_inputs_equal_except_guidance": True, "code_and_snapshot_unchanged": True})
    finally:
        await app.aclose()


def main() -> None:
    """显式单次执行四次重放；预检不会启动真实 API。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--database", type=Path, default=ROOT / "data/trivae.sqlite3")
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(execute(args.output, args.source, args.database, args.seed, args.preflight_only))


if __name__ == "__main__":
    main()
