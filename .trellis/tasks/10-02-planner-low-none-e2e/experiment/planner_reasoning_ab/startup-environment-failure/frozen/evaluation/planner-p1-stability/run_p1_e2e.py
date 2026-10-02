"""复用生产 Evaluation/Query 链路的有界 Planner effort A/B 实验。"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import subprocess
from dataclasses import asdict
from functools import partial
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx2 as httpx
from run_p1_low_none import write_json
from run_planner_only import CASE_IDS, ROOT, load_cases

from trivae.bootstrap.application import create_application
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import DEFAULT_DEEPSEEK_BASE_URL, load_settings
from trivae.conversation.sqlite import SQLiteConversationStore
from trivae.evaluation.benchmark.gt import build_case_ground_truth
from trivae.evaluation.benchmark.metrics import evaluate_end_to_end_case
from trivae.evaluation.contracts import EvaluationCaseBundle, utc_now
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.store import SQLiteEvaluationStore
from trivae.evaluation.variant import ControlledVariant, variant_diff
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.planner import SoftPlanner
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter, _RunState

EFFORTS = ("low", "none")
RETRIEVAL_TOOLS = {"lexical_search", "semantic_search", "get_recent_messages", "get_message_context"}


def append_json(path: Path, payload: Any) -> None:
    """每条事实立即关闭文件，避免失败或中断丢失已开始的 attempt。"""
    with path.open("a", encoding="utf-8") as sink:
        sink.write(json.dumps(payload, ensure_ascii=False) + "\n")


def public_fields(value: Any) -> Any:
    """只移除隐藏 reasoning 正文；usage 中 reasoning token 数保持原值。"""
    if isinstance(value, dict):
        return {k: public_fields(v) for k, v in value.items() if k not in {"reasoning_content", "reasoning"}}
    if isinstance(value, list):
        return [public_fields(v) for v in value]
    return value


def response_projection(body: bytes, streaming: bool) -> dict[str, Any]:
    """保留 Provider 的公开输出、usage 与 finish reason，不保存隐藏思维正文。"""
    if not streaming:
        return {"chunks": [public_fields(json.loads(body))], "stream_complete": True}
    # SSE 以行封装 JSON；transport chunk 的拆分不影响解析。
    chunks = []
    complete = False
    for line in body.decode("utf-8").splitlines():
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            complete = True
        else:
            chunks.append(public_fields(json.loads(data)))
    return {"chunks": chunks, "stream_complete": complete}


class ObservedStream(httpx.AsyncByteStream):
    """原样透传真实 stream；结束或异常时归档当前请求的公开响应。"""

    def __init__(self, source: httpx.AsyncByteStream, finish: Any) -> None:
        self.source, self.finish = source, finish
        self.body = bytearray()
        self.saved = False

    async def __aiter__(self):
        try:
            async for chunk in self.source:
                self.body.extend(chunk)
                yield chunk
        finally:
            if not self.saved:
                self.saved = True
                self.finish(bytes(self.body))

    async def aclose(self) -> None:
        await self.source.aclose()


class HTTPRecorder:
    """以 HTTP request-start 计真实请求数，和 SDK model-turn 数分开。"""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.active: dict[str, Any] = {}
        self.requests: list[dict[str, Any]] = []
        self.responses: dict[int, dict[str, Any]] = {}

    async def request(self, request: httpx.Request) -> None:
        payload = json.loads(request.content)
        number = len(self.requests) + 1
        # 不记录 header/API key；记录 SDK 已序列化的实际 body 和有效 timeout。
        row = {**self.active, "provider_request": number, "started_at": utc_now(),
               "serialized_request": public_fields(payload), "timeout": request.extensions.get("timeout")}
        request.extensions["experiment_request"] = number
        request.extensions["experiment_start"] = perf_counter()
        self.requests.append(row)
        append_json(self.directory / "provider_requests.jsonl", row)

    async def response(self, response: httpx.Response) -> None:
        number = response.request.extensions["experiment_request"]
        streaming = self.requests[number - 1]["serialized_request"].get("stream", False)

        def finish(body: bytes) -> None:
            # HTTP error 的 JSON 与成功 non-stream 响应用相同公开字段投影。
            projection = response_projection(body, streaming and response.status_code == 200)
            row = {"provider_request": number, "status_code": response.status_code,
                   "ended_at": utc_now(), "latency_ms": (perf_counter() - response.request.extensions["experiment_start"]) * 1000,
                   **projection}
            self.responses[number] = row
            append_json(self.directory / "provider_responses.jsonl", row)

        if streaming and response.status_code == 200:
            response.stream = ObservedStream(response.stream, finish)
        else:
            finish(await response.aread())

    def records(self, first: int) -> list[dict[str, Any]]:
        return [{**request, "response": self.responses.get(request["provider_request"])} for request in self.requests[first:]]


class TreatmentPlanner:
    """只在现有 Planner 注入边界切换 effort，始终调用生产 SoftPlanner。"""

    def __init__(self, planners: dict[str, SoftPlanner]) -> None:
        self.planners = planners
        self.effort = "low"
        self.result: Any = None

    async def plan(self, context: Any) -> Any:
        self.result = await self.planners[self.effort].plan(context)
        return self.result


def schedule(seed: int, attempt: int) -> list[dict[str, Any]]:
    """固定 seed 决定第一组 AB/BA，随后逐 Case 交替。"""
    initial = random.Random(seed).randrange(2)
    return [{"order": 2 * i + j + 1, "case_id": case, "treatment": effort, "attempt": attempt}
            for i, case in enumerate(CASE_IDS)
            for j, effort in enumerate(EFFORTS if (i + initial) % 2 == 0 else EFFORTS[::-1])]


def usage_for(requests: list[dict[str, Any]]) -> dict[str, Any]:
    """各字段独立计算 observed sum；任一次缺失时 total 保持 null。"""
    usages = []
    for request in requests:
        response = request.get("response")
        chunks = [] if response is None else response["chunks"]
        usages.append(next((c["usage"] for c in reversed(chunks) if c.get("usage") is not None), None))
    fields = {
        "input_tokens": lambda u: u.get("prompt_tokens"),
        "output_tokens": lambda u: u.get("completion_tokens"),
        "total_tokens": lambda u: u.get("total_tokens"),
        "reasoning_tokens": lambda u: (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "cached_input_tokens": lambda u: u.get("prompt_cache_hit_tokens", (u.get("prompt_tokens_details") or {}).get("cached_tokens")),
    }
    output = {}
    for field, extract in fields.items():
        values = [None if u is None else extract(u) for u in usages]
        observed = [v for v in values if v is not None]
        output[field] = {"total": sum(observed) if len(observed) == len(values) else None,
                         "observed_sum": sum(observed), "observed_requests": len(observed), "requests": len(values)}
    return output


def frozen_files(cases: list[EvaluationCaseBundle]) -> dict[str, bytes]:
    """逐字固定源码、runner、8 个 canonical bundle 和评测 manifest。"""
    paths = [*sorted((ROOT / "src").rglob("*.py")), Path(__file__),
             Path(__file__).with_name("run_planner_only.py"), Path(__file__).with_name("run_p1_low_none.py"),
             ROOT / "evaluation/planner-utility/manifest-v1.json", ROOT / "pyproject.toml", ROOT / "uv.lock"]
    paths.extend(ROOT / str(row["source"]) for row in load_cases())
    return {str(path.relative_to(ROOT)): path.read_bytes() for path in paths}


async def serialize_preflight(runtime: OpenAIAgentsRuntimeAdapter, prompt: str) -> dict[str, Any]:
    """在实际 SDK serializer 上做 provider-free diff；此阶段没有网络请求。"""
    client = runtime._provider_client._client
    transport = client._transport
    mounts = client._mounts
    bodies: dict[str, Any] = {}
    effort = "low"

    async def fake(request: httpx.Request) -> httpx.Response:
        bodies[effort] = json.loads(request.content)
        return httpx.Response(200, json={"id": "preflight-only", "object": "chat.completion", "created": 0,
                                       "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "stop",
                                       "message": {"role": "assistant", "content": "{}"}}]})
    client._transport = httpx.MockTransport(fake)
    # 显式清空 proxy mounts，保证预检绝不会绕过 MockTransport 发出真实请求。
    client._mounts = {}
    try:
        for effort in EFFORTS:
            await runtime.complete_text_with_observation(prompt, reasoning_effort_override=effort)
    finally:
        client._transport = transport
        client._mounts = mounts
    # 比较实际 SDK body 的所有字段；只有预期 effort 允许不同。
    differences = [k for k in set(bodies["low"]) | set(bodies["none"]) if bodies["low"].get(k) != bodies["none"].get(k)]
    if differences != ["reasoning_effort"]:
        raise ValueError(f"serialized treatment contamination: {differences}")
    return {"requests": bodies, "differences": differences, "network_requests": 0}


def blind_packet(directory: Path, cases: list[EvaluationCaseBundle], runs: list[dict[str, Any]], seed: int) -> None:
    """随机化 pair 与 A/B，移除 identity 元数据，避免工具 ID 暴露 treatment。"""
    rng = random.Random(seed)
    selected = list(cases)
    rng.shuffle(selected)
    mapping, packet = [], []
    by_case = {(r["case_id"], r["treatment"]): r for r in runs}
    for case in selected:
        treatments = list(EFFORTS)
        rng.shuffle(treatments)
        pair = {"case_id": case.case_id, "query": case.query,
                "reference_findings": [asdict(f) for f in case.reference_findings], "answers": {}}
        # reference provenance 包含评审时间但与执行顺序无关；移除不必要 provenance。
        for finding in pair["reference_findings"]:
            finding.pop("provenance", None)
        mapping.append({"case_id": case.case_id, "A": treatments[0], "B": treatments[1]})
        for label, effort in zip(("A", "B"), treatments, strict=True):
            row = by_case[(case.case_id, effort)]
            artifact = row["answer_artifact"]
            # 工具/运行 identity 不是语义证据；canonical message IDs 和引用绑定保留。
            def hide_ids(value: Any) -> Any:
                if isinstance(value, dict):
                    return {k: hide_ids(v) for k, v in value.items() if k not in {"tool_result_id", "run_id", "trace_id", "request_id", "created_at"}}
                if isinstance(value, list):
                    return [hide_ids(v) for v in value]
                return value
            pair["answers"][label] = {"answer": row["final_answer"], "artifact": hide_ids(artifact)}
        packet.append(pair)
    write_json(directory / "packet.json", packet)
    write_json(directory / "mapping.sealed.json", mapping)


async def execute(output: Path, database: Path, seed: int, attempt: int, preflight_only: bool = False) -> None:
    """预检、冻结、执行并逐次归档；不会补跑失败或自动进入第二阶段。"""
    output.mkdir(parents=True, exist_ok=False)
    for name in ("raw", "traces", "answers", "evaluation", "blind", "frozen"):
        (output / name).mkdir()
    load_environment_file()
    settings = load_settings()
    if (settings.provider, settings.model_name, settings.completion_max_tokens) != ("deepseek", "deepseek-flash", 2048):
        raise ValueError("requires official DeepSeek Flash and 2048 Planner budget")
    if settings.base_url.rstrip("/") != DEFAULT_DEEPSEEK_BASE_URL:
        raise ValueError("requires official DeepSeek endpoint")
    cases = [EvaluationCaseBundle.from_json(ROOT / str(row["source"])) for row in load_cases()]
    runtime = OpenAIAgentsRuntimeAdapter(settings=settings)
    traces = SQLiteTraceStore(output / "trace.sqlite3")
    store = SQLiteEvaluationStore(output / "evaluation.sqlite3")
    conversations = SQLiteConversationStore(output / "conversation.sqlite3")
    planners: dict[str, SoftPlanner] = {}
    treatment = TreatmentPlanner(planners)
    app = create_application(database, agent_runtime=runtime, planner=treatment, trace_store=traces, conversation_store=conversations,
                             evaluation_store=store, feedback_database_path=output / "feedback.sqlite3")
    runtime.capability_registry = app.capability_registry
    planners.update({effort: SoftPlanner(partial(runtime.complete_text_with_observation, reasoning_effort_override=effort),
                                   completion_request=runtime.completion_request_projection(reasoning_effort_override=effort),
                                   capability_metadata=app.capability_registry.metadata()) for effort in EFFORTS})
    order = schedule(seed, attempt)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    frozen = frozen_files(cases)
    runs: list[dict[str, Any]] = []
    recorder = HTTPRecorder(output / "raw")
    try:
        snapshot = app.materialize_evaluation_snapshot()
        if any(c.dataset_snapshot.deterministic_fingerprint != snapshot.deterministic_fingerprint for c in cases):
            raise ValueError("canonical snapshot drift")
        preflight_cases = []
        schemas = None
        variants = {}
        for effort in EFFORTS:
            variants[effort] = ControlledVariant(
                variant_id="p1-e2e", code_version=commit, provider=settings.provider, model=settings.model_name,
                prompt_identity="production-P1", planner_configuration={"reasoning_effort": effort},
                runtime_configuration={**{k: v for k, v in settings.to_safe_dict().items() if k != "api_key_configured"}, "trace_profile": "debug"},
                available_tools=QueryRequest(query="preflight", scope=cases[0].data_access_scope).available_capabilities,
                index_identity=json.dumps(snapshot.manifest["lexical_index"], sort_keys=True),
                execution_override=ExecutionOverride(forced_route="planned_execution"))
        diff = variant_diff(variants["low"], variants["none"])
        write_json(output / "variants.json", {e: v.to_dict() for e, v in variants.items()})
        for case in cases:
            # 与 EvaluationRunner._run_one 完全相同的动态 payload；不另写 query 执行链。
            request = QueryRequest(query=case.query, scope=case.data_access_scope, locale=case.locale,
                data_snapshot={"snapshot_id": case.dataset_snapshot.snapshot_id, "schema_version": case.dataset_snapshot.schema_version,
                               "message_count": case.dataset_snapshot.message_count, "relevant_time_range": list(case.dataset_snapshot.relevant_time_range),
                               "evaluation_case": case.identity, "repetition": 0},
                available_capabilities=variants["low"].available_tools, trace_profile="debug", execution_override=variants["low"].execution_override)
            prompts = {e: p._build_prompt(request.to_context(), p._capability_summaries) for e, p in planners.items()}
            if prompts["low"] != prompts["none"]:
                raise ValueError("Planner input drift")
            serialized = await serialize_preflight(runtime, prompts["low"])
            # 用实际 SDK agent builder 读取 schemas/instructions；不执行 Agent，不发 Provider 请求。
            req = request.to_runtime_request()
            agent = runtime._build_agent(req, runtime._build_context(req), _RunState(provider=settings.provider, model=settings.model_name))
            current_schemas = [{"name": t.name, "description": t.description, "parameters": t.params_json_schema,
                                "strict": t.strict_json_schema} for t in agent.tools]
            if schemas is None:
                schemas = current_schemas
            elif schemas != current_schemas:
                raise ValueError("tool schemas differ between cases")
            preflight_cases.append({"case_id": case.case_id, "case": case.to_dict(), "application_prompt": prompts["low"],
                                    "application_request": asdict(request), "serialized": serialized,
                                    "downstream_instructions": agent.instructions(None, agent)})
        write_json(output / "preflight.json", {"passed": True,
            "statement": "treatment request 的唯一预期语义差异是 reasoning_effort",
            "cases": preflight_cases, "capability_metadata": [asdict(m) for m in app.capability_registry.metadata()],
            "tool_schemas": schemas, "variant_diff": diff, "planner_timeout_seconds": 20,
            "sdk_retries": runtime._provider_client.max_retries, "network_requests": 0,
            "nuisance_identity": "fresh request/run/conversation IDs; no treatment labels in model input"})
        write_json(output / "run_order.json", {"seed": seed, "attempt": attempt, "order": order})
        write_json(output / "manifest.json", {"experiment_id": output.name, "execution_commit": commit,
            "dirty_state": dirty, "timestamp": utc_now(), "snapshot": snapshot.to_dict(), "settings": settings.to_safe_dict(),
            "case_ids": list(CASE_IDS), "logical_runs": 16, "attempt": attempt, "retry": False,
            "route": "existing forced planned evaluation override", "semantic_index": asdict(app.semantic_index_status()),
            "monetary_cost": "Monetary cost unavailable", "cache": "fresh conversations; no retrieval result cache; Provider prefix cache is measured per HTTP response"})
        (output / "execution.diff").write_text(subprocess.check_output(["git", "diff"], cwd=ROOT, text=True))
        for relative, content in frozen.items():
            path = output / "frozen" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        if preflight_only:
            return
        # 通过已有显式 preload 预热本地 embedding，避免第一侧承担模型加载耗时。
        warm_started = perf_counter()
        app.semantic_provider.preload()
        write_json(output / "warmup.json", {"preloaded": True, "duration_ms": (perf_counter() - warm_started) * 1000, "provider_requests": 0})
        runtime._provider_client._client.event_hooks = {"request": [recorder.request], "response": [recorder.response]}
        results: dict[str, Any] = {}

        async def query(request: QueryRequest) -> Any:
            result = await app.query(request)
            results[request.request_id] = result
            return result

        runner = EvaluationRunner(query_executor=query, trace_reader=app.read_trace, store=store,
                                  snapshot_resolver=app.materialize_evaluation_snapshot)
        cases_by_id = {c.case_id: c for c in cases}
        for item in order:
            # 先确认冻结数据未变，再将 attempt 写盘；失败不会被另一条成功 run 替换。
            if frozen_files(cases) != frozen:
                raise RuntimeError("code/case changed during execution")
            append_json(output / "attempts.jsonl", {**item, "started_at": utc_now()})
            recorder.active = dict(item)
            first = len(recorder.requests)
            treatment.effort = item["treatment"]
            treatment.result = None
            case = cases_by_id[item["case_id"]]
            started = perf_counter()
            exception = None
            try:
                eval_runs = await runner.run_case(case, variants[treatment.effort], suite_id="targeted-p1-e2e")
                run = eval_runs[0]
            except Exception as exc:
                # 现有 Runner 已保存失败 run；归档异常并继续下一预定 attempt，不重试本次。
                exception = {"type": type(exc).__name__, "message": runtime._redact(str(exc))}
                matching = store.list_runs(case_id=case.case_id)
                if not matching:
                    raise
                run = matching[-1]
            elapsed = (perf_counter() - started) * 1000
            result = results.get(run.query_request_id)
            requests = recorder.records(first)
            planner_result = treatment.result
            trace = None if run.trace_id is None else traces.read_trace(run.trace_id)
            trace_rows = [] if trace is None else [e.to_row() for e in trace.events]
            row = {**item, "experiment_id": output.name, "execution_commit": commit, "snapshot_id": run.snapshot_id,
                   "started_at": run.started_at, "completed_at": run.completed_at, "run_id": run.run_id,
                   "trace_id": run.trace_id, "exception": exception, "wall_clock_ms": elapsed,
                   "planner": None if planner_result is None else asdict(planner_result),
                   "evaluation_run": run.to_dict(), "provider_requests": requests,
                   "usage": {"planner": usage_for(requests[:1]), "downstream": usage_for(requests[1:]), "total": usage_for(requests)},
                   "query_result": None if result is None else asdict(result),
                   "answer_artifact": None if result is None or result.answer_artifact is None else asdict(result.answer_artifact),
                   "final_answer": None if result is None else result.final_answer,
                   "automatic_evaluation": evaluate_end_to_end_case(build_case_ground_truth(case), run.query_result, operational_measurements=run.operational_measurements)}
            # 每 run 的 raw/Trace/Answer/评测独立落盘，同时 append-only 汇总记录。
            name = f"{case.case_id}-{treatment.effort}-a{attempt}"
            write_json(output / "raw" / f"{name}.json", row)
            write_json(output / "traces" / f"{name}.json", trace_rows)
            write_json(output / "answers" / f"{name}.json", row["answer_artifact"])
            write_json(output / "evaluation" / f"{name}.json", row["automatic_evaluation"])
            append_json(output / "runs.jsonl", row)
            runs.append(row)
            print(f"{item['order']}/16 {name}: {run.terminal_status}; provider={len(requests)}; wall={elapsed/1000:.2f}s", flush=True)
        if frozen_files(cases) != frozen or app.materialize_evaluation_snapshot().deterministic_fingerprint != snapshot.deterministic_fingerprint:
            raise RuntimeError("postrun frozen identity drift")
        write_json(output / "integrity.json", {"logical_runs": len(runs), "actual_provider_requests": len(recorder.requests),
                                              "provider_responses": len(recorder.responses), "retry_count": 0,
                                              "code_and_cases_unchanged": True, "snapshot_unchanged": True})
        blind_packet(output / "blind", cases, runs, seed + 100)
    finally:
        await app.aclose()


def main() -> None:
    """显式阶段参数只运行一次固定 16-run batch。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=ROOT / "data/trivae.sqlite3")
    parser.add_argument("--seed", type=int, default=20261002)
    parser.add_argument("--attempt", type=int, choices=(1, 2), default=1)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(execute(args.output, args.database, args.seed, args.attempt, args.preflight_only))


if __name__ == "__main__":
    main()
