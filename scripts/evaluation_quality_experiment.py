"""固定 Case 的生产链路实验：forced standard 隔离 Router/Planner，不修改生产预算或 Prompt。"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import subprocess
from dataclasses import asdict
from difflib import unified_diff
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch

import httpx2 as httpx

import trivae
from trivae.bootstrap.application import create_application
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.conversation import SQLiteConversationStore
from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationContractError, utc_now
from trivae.evaluation.prompt_screening import read_artifact, write_artifact
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.variant import ControlledVariant
from trivae.observability.collector import CapturePolicy
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter, _RunState
from trivae.query.runtime.prompt import SYSTEM_PROMPT

TOOLS = ("lexical_search", "semantic_search", "get_recent_messages", "get_message_context",
         "find_members", "get_schema", "execute_sql")
HTTP_LIMIT = 120


class BudgetExhausted(EvaluationContractError):
    """全局实际 HTTP 发送预算已耗尽。"""


class HttpLedger:
    """追加式发送账本；先持久化 debit，再进入真实 HTTP 发送边界。"""

    def __init__(self, path: Path, maximum: int = HTTP_LIMIT) -> None:
        if not 0 < maximum <= HTTP_LIMIT:
            raise EvaluationContractError("HTTP maximum must be between 1 and 120")
        self.path = path
        self.maximum = maximum
        path.parent.mkdir(parents=True, exist_ok=True)
        # 文件锁覆盖读取与追加，多个实验进程不能同时占用最后一个余额。
        with path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            rows = [json.loads(line) for line in stream if line.strip()]
            if not rows:
                self._append(stream, {"event": "budget", "maximum": maximum})
            elif rows[0] != {"event": "budget", "maximum": maximum}:
                raise EvaluationContractError("existing global HTTP budget differs")

    @staticmethod
    def _append(stream: Any, value: dict[str, Any]) -> None:
        """每次发送前 fsync，进程中断也保留已消耗预算。"""
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    @property
    def count(self) -> int:
        with self.path.open(encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_SH)
            return sum(json.loads(line).get("event") == "started" for line in stream if line.strip())

    def debit(self, *, arm: str, case_id: str, output: str) -> int:
        """发送事件只保存归属和时间，不复制请求正文、Header 或隐藏推理。"""
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            count = sum(json.loads(line).get("event") == "started" for line in stream if line.strip())
            if count >= self.maximum:
                raise BudgetExhausted("global HTTP budget exhausted before send")
            number = count + 1
            self._append(stream, {"event": "started", "number": number, "arm": arm,
                                  "case_id": case_id, "output": output, "at": utc_now()})
            return number

    def finish(self, number: int, **facts: Any) -> None:
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self._append(stream, {"event": "finished", "number": number, "at": utc_now(), **facts})


def verify_conditions(
    baseline: dict[str, Any], candidate: dict[str, Any], *, prompt_treatment: bool = False,
) -> str | None:
    """显式 treatment 只允许基础 Prompt 变化，动态后缀和其他执行条件必须相等。"""
    def comparable(value: dict[str, Any]) -> dict[str, Any]:
        result = {key: item for key, item in value.items() if key not in {"arm", "commit"}}
        if prompt_treatment:
            prompt, instructions = result["prompt"], result["initial_instructions"]
            # 每侧必须使用自己的真实基础 Prompt，不能拿忽略字段绕过动态 instructions 门禁。
            if not isinstance(prompt, str) or not prompt or not isinstance(instructions, str):
                raise EvaluationContractError("prompt treatment requires full prompt and initial_instructions")
            if not instructions.startswith(prompt):
                raise EvaluationContractError("initial_instructions must start with its own prompt")
            # 只剥离各自前缀；预算等动态后缀继续逐字比较。
            result["initial_instructions"] = instructions[len(prompt):]
            del result["prompt"]
        return result

    left, right = comparable(baseline), comparable(candidate)
    if left != right:
        changed = sorted(key for key in left.keys() | right.keys() if left.get(key) != right.get(key))
        raise EvaluationContractError(f"baseline execution conditions drifted: {', '.join(changed)}")
    if prompt_treatment:
        # 完整 Prompt 保留在两侧 conditions；协议额外保存可直接审阅的逐行差异。
        return "\n".join(unified_diff(
            baseline["prompt"].splitlines(), candidate["prompt"].splitlines(),
            fromfile="baseline/prompt", tofile="candidate/prompt", lineterm="",
        )) + "\n"
    return None


def load_cases(directory: Path, selected: list[str]) -> list[EvaluationCaseBundle]:
    """只加载显式 Case ID，避免把 targets sidecar 当成 Case 或自动扩大套件。"""
    if not selected or len(set(selected)) != len(selected):
        raise EvaluationContractError("select non-empty distinct cases explicitly")
    cases = [EvaluationCaseBundle.from_json(directory / f"{case_id}.json") for case_id in selected]
    if [case.case_id for case in cases] != selected:
        raise EvaluationContractError("case filename and case_id differ")
    return cases


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--database", type=Path, required=True)
    result.add_argument("--semantic-index", type=Path, required=True)
    result.add_argument("--cases-dir", type=Path, required=True)
    result.add_argument("--case", action="append", required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--arm", choices=("baseline", "candidate"), required=True)
    result.add_argument("--baseline-dir", type=Path)
    result.add_argument("--prompt-treatment", action="store_true",
                        help="显式允许 named_resource_sufficiency 基础 Prompt treatment；动态后缀严格不变")
    result.add_argument("--budget-ledger", type=Path, help="跨所有批次共享，默认 output 父目录/http-budget.jsonl")
    result.add_argument("--max-http-requests", type=int, default=HTTP_LIMIT, help="全局上限，最多 120")
    result.add_argument("--env-file", type=Path, default=Path(".env"))
    return result


async def execute(args: argparse.Namespace) -> None:
    """先验证整套固定条件，再按原始顺序运行；异常保留原始分母。"""
    cases = load_cases(args.cases_dir, args.case)
    if not args.database.is_file() or not args.semantic_index.is_file():
        raise EvaluationContractError("canonical and semantic snapshots must already exist")
    if args.output.exists():
        raise EvaluationContractError("output already exists; experiment is create-only")
    if args.prompt_treatment and (args.arm != "candidate" or args.baseline_dir is None):
        raise EvaluationContractError("prompt treatment requires candidate arm and --baseline-dir")
    if args.arm == "candidate" and args.baseline_dir is None:
        raise EvaluationContractError("candidate requires --baseline-dir")
    # 私有输出必须落在仓库忽略目录，防止逐 Case 正文进入 Git。
    if subprocess.run(["git", "check-ignore", "--quiet", str(args.output)]).returncode != 0:
        raise EvaluationContractError("private experiment output must be Git-ignored")
    load_environment_file(args.env_file)
    settings = load_settings()
    if (settings.provider, settings.model_name, settings.base_url) != (
        "deepseek", "deepseek-flash", "https://api.deepseek.com"
    ) or not settings.api_key:
        raise EvaluationContractError("experiment requires official DeepSeek Flash and a configured key")
    # 从实际导入的生产包定位 commit，支持冻结 worktree 的 PYTHONPATH 配对执行。
    source_root = Path(trivae.__file__).resolve().parents[2]
    commit = subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True).strip()
    ledger = HttpLedger(args.budget_ledger or args.output.parent / "http-budget.jsonl", args.max_http_requests)
    args.output.mkdir(parents=True, exist_ok=False)
    runtime = OpenAIAgentsRuntimeAdapter(settings=settings)
    trace_store = SQLiteTraceStore(args.output / "trace.sqlite3")
    application = create_application(
        args.database, agent_runtime=runtime, semantic_index_path=args.semantic_index,
        conversation_store=SQLiteConversationStore(args.output / "conversation.sqlite3"),
        trace_store=trace_store, evaluation_database_path=args.output / "evaluation.sqlite3",
        feedback_database_path=args.output / "feedback.sqlite3",
    )
    runtime.capability_registry = application.capability_registry
    captured: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    current: dict[str, str] = {}
    original_send = httpx.AsyncClient._send_single_request
    # 复用生产 CapturePolicy 的 secret filter；错误正文不直接写到控制台。
    capture_policy = CapturePolicy.for_profile("debug", secret_values=(settings.api_key,))

    async def query(request: QueryRequest) -> Any:
        captured["request_id"] = request.request_id
        result = await application.query(request)
        captured["result"] = result
        return result

    async def counted_send(client: Any, request: Any) -> Any:
        # 精确 host 与 HTTPS 校验先于发送，外部地址不能消耗或绕过实验账本。
        if request.url.host != "api.deepseek.com" or request.url.scheme != "https":
            raise EvaluationContractError("unexpected provider host or scheme")
        number = ledger.debit(arm=args.arm, case_id=current["case_id"], output=str(args.output))
        try:
            response = await original_send(client, request)
        except BaseException as exc:
            # cancellation 与普通异常一样留下发送尝试；不复制可能含敏感信息的异常文本。
            ledger.finish(number, error_type=type(exc).__name__)
            raise
        ledger.finish(number, status=response.status_code)
        return response

    runner = EvaluationRunner(query_executor=query, trace_reader=application.read_trace,
                              store=application.evaluation_store, database_path=args.database)
    try:
        semantic = application.semantic_index_status().to_dict()
        # updated_at 是派生索引写入时间；其余完整身份、状态和 watermark 均参与相等门禁。
        semantic.pop("updated_at")
        prepared = []
        prompt_diffs = {}
        for case in cases:
            if runner.resolve_snapshot(case).snapshot_id != case.dataset_snapshot.snapshot_id:
                raise EvaluationContractError("case snapshot drifted; create a new case version")
            request = QueryRequest(case.query, case.data_access_scope, locale=case.locale,
                                   available_capabilities=TOOLS).to_runtime_request()
            agent = runtime._build_agent(request, runtime._build_context(request),
                                         _RunState(settings.provider, settings.model_name))
            conditions = {
                "arm": args.arm, "commit": commit, "case": case.to_dict(),
                "settings": settings.to_safe_dict(), "runtime": runtime.safe_configuration(),
                "prompt": SYSTEM_PROMPT, "initial_instructions": agent.instructions(None, agent),
                "model_settings": agent.model_settings.to_json_dict(),
                "completion_request": runtime.completion_request_projection(),
                "tools": [{"name": tool.name, "description": tool.description,
                           "schema": tool.params_json_schema, "strict": tool.strict_json_schema}
                          for tool in agent.tools],
                "semantic_index": semantic, "forced_route": "standard_execution", "trace_profile": "debug",
                "route_boundary": "Router and Planner isolated by forced standard; production Agent unchanged",
                "http_limit": ledger.maximum, "application_retries": 0,
                "sdk_max_retries": runtime._provider_client.max_retries,
            }
            # JSON round-trip 统一 tuple/list，严格比较不受序列化形态影响。
            conditions = json.loads(json.dumps(conditions, ensure_ascii=False))
            if args.baseline_dir is not None:
                prompt_diff = verify_conditions(
                    read_artifact(args.baseline_dir / "conditions" / f"{case.case_id}.json"), conditions,
                    prompt_treatment=args.prompt_treatment,
                )
                if prompt_diff is not None:
                    prompt_diffs[case.case_id] = prompt_diff
            variant = ControlledVariant(
                variant_id=f"quality:{args.arm}", code_version=commit, provider=settings.provider,
                model=settings.model_name, available_tools=TOOLS, prompt_identity="production-system-prompt",
                runtime_configuration={"trace_profile": "debug"},
                execution_override=ExecutionOverride(forced_route="standard_execution"),
            )
            prepared.append((case, variant, conditions))
        # 整套条件门禁通过后再冻结；未通过的套件不会产生付费请求。
        (args.output / "cases").mkdir()
        for case, _, conditions in prepared:
            write_artifact(args.output / "conditions" / f"{case.case_id}.json", conditions)
            case.to_json(args.output / "cases" / f"{case.case_id}.json")
        write_artifact(args.output / "protocol.json", {
            "arm": args.arm, "commit": commit, "case_ids": args.case, "created_at": utc_now(),
            "execution_source": str(source_root),
            "treatment": "named_resource_sufficiency" if args.prompt_treatment else None,
            "prompt_diff": prompt_diffs,
            "budget_ledger": str(ledger.path), "http_limit": ledger.maximum,
            "review_status": "pending; execution success is not factual/citation correctness",
        })
        with patch.object(httpx.AsyncClient, "_send_single_request", counted_send):
            for case, variant, _ in prepared:
                current["case_id"] = case.case_id
                captured.clear()
                before, started = ledger.count, perf_counter()
                record: dict[str, Any] = {"case_id": case.case_id, "case_version": case.version,
                                          "arm": args.arm, "semantic_review": "pending", "currency_cost": None}
                if before >= ledger.maximum:
                    record["status"] = "not_run_budget"
                else:
                    try:
                        run = (await runner.run_case(case, variant))[0]
                        result = captured["result"]
                        record.update(status=result.execution_status, run=run.to_dict(), result=asdict(result))
                        try:
                            record["trace"] = asdict(application.read_trace(result.trace_id))
                            # canonical normalized events 经生产 capture 后保存，供 model-visible 归因。
                            write_artifact(args.output / "traces" / f"{case.case_id}.json",
                                           asdict(trace_store.read_trace(result.trace_id)))
                            application.export_trace_log(result.trace_id,
                                output_path=args.output / "traces" / f"{case.case_id}.log", context_mode="full")
                        except Exception as exc:
                            # 导出失败单列保存，不能抹掉已完成的 Query/Evaluation 事实。
                            error, _ = capture_policy.capture({"message": str(exc)})
                            record["artifact_capture_error"] = {"type": type(exc).__name__, **error}
                    except Exception as exc:
                        # Runner 已持久化失败 Evaluation；单 Case 失败不覆盖、不重试。
                        error, limitations = capture_policy.capture({"message": str(exc)})
                        record.update(status="exception", error_type=type(exc).__name__, error=error,
                                      error_limitations=limitations, request_id=captured.get("request_id"))
                    record.update(latency_ms=(perf_counter() - started) * 1000)
                record["http_requests"] = ledger.count - before
                records.append(record)
                write_artifact(args.output / f"{case.case_id}.json", record)
                print(case.case_id, args.arm, record["status"], record["http_requests"], flush=True)
    finally:
        await application.aclose()
        write_artifact(args.output / "summary.json", {
            "case_count": len(cases), "record_count": len(records), "records": records,
            "global_http_requests": ledger.count, "http_limit": ledger.maximum,
        })


if __name__ == "__main__":
    asyncio.run(execute(parser().parse_args()))
