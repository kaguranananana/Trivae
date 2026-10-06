"""成本受控的 Prompt 实验入口；所有真实查询进入 Application.query。"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from trivae.bootstrap.application import create_application
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.conversation import SQLiteConversationStore
from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationContractError, EvaluationRun
from trivae.evaluation.prompt_screening import (
    ProviderCallBudget,
    ScreeningRuntime,
    candidate_repeat_count,
    read_artifact,
    screening_conditions,
    select_policy_cases,
    verify_frozen_baseline,
    write_artifact,
)
from trivae.evaluation.review import build_review_packet, create_paired_comparison
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.variant import ControlledVariant
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime.openai_adapter import _RunState
from trivae.query.runtime.prompt import SYSTEM_PROMPT


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--mode", required=True, choices=(
        "static", "first-tool", "targeted", "candidate-only", "freeze-baseline", "full-gate",
    ))
    result.add_argument("--case", action="append", type=Path, default=[])
    result.add_argument("--policy")
    result.add_argument("--candidate-prompt", type=Path)
    result.add_argument("--baseline-prompt", type=Path)
    result.add_argument("--baseline-dir", type=Path)
    result.add_argument("--database", type=Path)
    result.add_argument("--semantic-index", type=Path)
    result.add_argument("--output", type=Path)
    result.add_argument("--env-file", type=Path, default=Path(".env"))
    # 每轮先声明实际 HTTP 调用最大值，不能把一个完整 Query 当一次 API 请求。
    result.add_argument("--max-provider-calls", type=int, default=0)
    result.add_argument("--repeat", type=int, default=1, choices=(1,))
    result.add_argument("--repeat-on-failure", type=Path, help="单 case 已有 candidate artifact")
    result.add_argument("--candidate-extra", type=int, default=0)
    result.add_argument("--review", choices=("regression", "borderline"))
    result.add_argument("--repeat-reason", choices=("provider_randomness", "borderline"))
    result.add_argument("--order", choices=("AB", "BA"), default="AB")
    return result


def static_checks() -> None:
    """此分支不读密钥、不构造 Provider；只运行当前 scope 的零成本检查。"""

    commands = [
        ["uv", "run", "--all-extras", "ruff", "check", "src", "tests", "scripts/run_prompt_screening.py"],
        ["uv", "run", "--all-extras", "mypy", "src"],
        ["uv", "run", "--all-extras", "pytest", "-q", "tests/test_prompt_screening.py",
         "tests/test_prompt_fixtures.py", "tests/test_prompt_limit_contract.py",
         "tests/test_prompt_parameter_contracts.py",
         "tests/test_stage_c_tools.py",
         "tests/test_agent_tool_surface.py", "tests/test_context_source_contract.py",
         "tests/test_evaluation.py", "tests/test_no_result_finalization.py"],
    ]
    for command in commands:
        subprocess.run(command, check=True)
    print(json.dumps({"mode": "static", "provider_calls": 0, "tokens": 0, "cost": 0}))


async def execute(args: argparse.Namespace) -> None:
    # 所有选择和预算在构造真实 Provider 前校验，拒绝默认整套实验。
    cases = select_policy_cases([EvaluationCaseBundle.from_json(path) for path in args.case], args.policy)
    if args.mode == "targeted" and args.policy is None:
        raise EvaluationContractError("targeted requires --policy")
    if args.database is None or args.output is None or args.max_provider_calls <= 0:
        raise EvaluationContractError("real modes require database, new output and positive max-provider-calls")
    if args.mode in {"candidate-only", "targeted"} and args.baseline_dir is None:
        raise EvaluationContractError("development screening requires --baseline-dir")
    if args.mode != "freeze-baseline" and args.candidate_prompt is None:
        raise EvaluationContractError("candidate prompt must be explicit")
    extra = 0
    if args.candidate_extra or args.repeat_on_failure is not None:
        if args.mode not in {"candidate-only", "targeted"} or len(cases) != 1 or args.repeat_on_failure is None or args.review is None:
            raise EvaluationContractError("repeat-on-failure requires one case, prior artifact and explicit review")
        prior = read_artifact(args.repeat_on_failure)
        if prior.get("kind") != "candidate_screen":
            raise EvaluationContractError("repeat-on-failure requires a prior candidate, not baseline or probe")
        if prior.get("conditions", {}).get("case") != cases[0].identity:
            raise EvaluationContractError("repeat artifact does not belong to the selected case")
        extra = candidate_repeat_count(args.review, args.candidate_extra, args.repeat_reason)
        if extra == 0:
            print(json.dumps({"decision": "rejected", "provider_calls": 0}))
            return
    candidate = SYSTEM_PROMPT if args.candidate_prompt is None else args.candidate_prompt.read_text()
    baseline = SYSTEM_PROMPT if args.baseline_prompt is None else args.baseline_prompt.read_text()
    if baseline != SYSTEM_PROMPT:
        raise EvaluationContractError("baseline must be the current production prompt")
    load_environment_file(args.env_file)
    settings = load_settings()
    budget = ProviderCallBudget(args.max_provider_calls)
    # 输出目录只创建一次，避免覆盖旧成功或失败；实验输出应放 ignored data/evaluation 下。
    args.output.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    runtime = ScreeningRuntime(settings=settings, first_tool=args.mode == "first-tool")
    application = create_application(
        args.database, agent_runtime=runtime, semantic_index_path=args.semantic_index,
        conversation_store=SQLiteConversationStore(args.output / "conversation.sqlite3"),
        trace_store=SQLiteTraceStore(args.output / "trace.sqlite3"),
        evaluation_database_path=args.output / "evaluation.sqlite3",
        feedback_database_path=args.output / "feedback.sqlite3",
    )
    runtime.capability_registry = application.capability_registry
    runtime._provider_client._client.event_hooks["request"] = [budget.before_request]
    captured: list[Any] = []

    async def query(request: Any) -> Any:
        # EvaluationRunner 与 Query 的唯一业务入口相同，仅保留完整本地 artifact。
        result = await application.query(request)
        captured.append(result)
        return result

    runner = EvaluationRunner(query_executor=query, trace_reader=application.read_trace,
                              store=application.evaluation_store, database_path=args.database)
    try:
        # 先验证所有 frozen conditions 和 snapshot，再允许第一笔付费请求。
        prepared = []
        for case in cases:
            variant = ControlledVariant(
                variant_id=f"prompt-screen:{args.mode}", code_version=commit,
                provider=settings.provider, model=settings.model_name,
                available_tools=("lexical_search", "semantic_search", "get_recent_messages",
                                 "get_message_context", "find_members", "get_schema", "execute_sql"),
                prompt_identity=f"prompt:{commit}", runtime_configuration={"trace_profile": "debug"},
                execution_override=ExecutionOverride(forced_route="standard_execution"),
            )
            if runner.resolve_snapshot(case).snapshot_id != case.dataset_snapshot.snapshot_id:
                raise EvaluationContractError("case snapshot drifted before provider call")
            conditions = screening_conditions(case, provider=settings.provider, model=settings.model_name,
                settings=settings.to_safe_dict(), tool_budget=runtime.max_tool_rounds, tools=variant.available_tools)
            # 实物 SDK 合约也冻结；代码版本可变化，但非策略条件不能静默漂移。
            request = QueryRequest(case.query, case.data_access_scope,
                                   available_capabilities=variant.available_tools).to_runtime_request()
            initial = runtime._build_agent(request, runtime._build_context(request),
                                           _RunState(settings.provider, settings.model_name))
            conditions["tool_contract"] = [{"name": tool.name, "description": tool.description,
                "schema": tool.params_json_schema, "strict": tool.strict_json_schema} for tool in initial.tools]
            conditions["model_settings"] = initial.model_settings.to_json_dict()
            frozen = None
            if args.mode in {"candidate-only", "targeted"}:
                frozen = read_artifact(args.baseline_dir / f"{case.case_id}.json")
                verify_frozen_baseline(frozen, conditions, baseline)
            if args.repeat_on_failure is not None:
                if prior.get("conditions") != conditions or prior.get("prompt") != candidate:
                    raise EvaluationContractError("repeat candidate or execution conditions drifted")
            prepared.append((case, variant, conditions, frozen))
        for case, variant, conditions, frozen in prepared:
            variants = [("candidate", candidate)]
            if args.mode == "freeze-baseline":
                variants = [("baseline", baseline)]
            if args.mode == "full-gate":
                variants = [("baseline", baseline), ("candidate", candidate)]
                if args.order == "BA":
                    variants.reverse()
            paired = {}
            for label, prompt in variants:
                current_variant = replace(variant, variant_id=f"prompt-screen:{label}:{commit}",
                                          role="last_stable" if label == "baseline" else "candidate",
                                          prompt_identity=f"prompt:{label}:{commit}")
                for repeat in range(extra or 1):
                    runtime.screening_prompt = prompt
                    runtime.probe_calls.clear()
                    first_request = len(budget.requests)
                    run = (await runner.run_case(case, current_variant, repetitions=1))[0]
                    result = captured[-1]
                    artifact = {
                        "kind": "first_tool_probe" if runtime.first_tool else
                            "frozen_baseline" if label == "baseline" else "candidate_screen",
                        "commit": commit, "prompt": prompt, "conditions": conditions,
                        "variant": current_variant.to_dict(),
                        "run": run.to_dict(), "answer": result.final_answer,
                        "answer_artifact": None if result.answer_artifact is None else asdict(result.answer_artifact),
                        "review_packet": build_review_packet(run=run, query=case.query, result=result,
                                                            rubric_version=case.review_policy.rubric_version).to_dict(),
                        "trace": asdict(application.read_trace(result.trace_id)),
                        "probe_calls": list(runtime.probe_calls),
                        # 截断实验单独保存SDK观测，不回填或伪造canonical Trace/完整Run状态。
                        "probe_usage": runtime.probe_usage,
                        "probe_usage_source": "sdk_tool_context" if runtime.probe_usage is not None else None,
                        "provider_requests": budget.requests[first_request:],
                        "provider_calls": len(budget.requests) - first_request,
                        "frozen_baseline": None if frozen is None else frozen["run"]["run_id"],
                        "semantic_review": "pending", "currency_cost": None,
                    }
                    write_artifact(args.output / f"{case.case_id}-{label}-{repeat}.json", artifact)
                    if label == "baseline":
                        write_artifact(args.output / f"{case.case_id}.json", artifact)
                    paired[label] = (current_variant, run)
                    if label == "candidate" and frozen is not None:
                        paired["baseline"] = (ControlledVariant.from_dict(frozen["variant"]),
                                              EvaluationRun.from_dict(frozen["run"]))
                    if "baseline" in paired and "candidate" in paired:
                        comparison = create_paired_comparison(case=case,
                            baseline_variant=paired["baseline"][0], candidate_variant=paired["candidate"][0],
                            baseline_runs=(paired["baseline"][1],), candidate_runs=(paired["candidate"][1],))
                        write_artifact(args.output / f"{case.case_id}-comparison-{repeat}.json", comparison.to_dict())
                    probe_ok = runtime.first_tool and bool(runtime.probe_calls) and not result.runtime_result.tool_calls
                    # 明确工程失败停止所有后续付费；semantic_review 待人工，不冒充质量通过。
                    if not probe_ok and (run.has_hard_failure or not result.is_successful):
                        raise EvaluationContractError(f"{case.identity} failed; stopped subsequent provider calls")
    finally:
        # 即使付费/查询失败，也保存已发生的请求数量并关闭连接。
        write_artifact(args.output / "provider-ledger.json", {
            "provider_calls": len(budget.requests), "maximum": budget.maximum,
            "tokens": "see per-case run and trace usage", "currency_cost": None,
        })
        await application.aclose()


def main() -> None:
    args = parser().parse_args()
    if args.mode == "static":
        if args.max_provider_calls != 0:
            raise EvaluationContractError("static mode provider budget must be zero")
        static_checks()
    else:
        asyncio.run(execute(args))


if __name__ == "__main__":
    main()
